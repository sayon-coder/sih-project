"""
Tests for chat PDF attachments + the Groq/Sarvam provider toggle.

Covers:
  - POST /api/assistant/attachments: extraction, validation (non-PDF, corrupt,
    no-text scan, auth, size), session binding and ownership rules
  - Chat with attachments: document injected into the LLM prompt, follow-up
    reuse within the session, provenance, honest failures (404/400)
  - Provider toggle: strict Sarvam selection, default Groq path, 422 on junk
  - generate_rag_answer with document_context and no corpus chunks
  - _build_document_context size cap

No network: the LLM is a fake injected through get_llm_provider /
get_llm_provider_for patches at the router boundary.
"""
import io
import json
from types import SimpleNamespace

import pytest

from app.llm.base import LLMProvider
from app.rag.generation import generate_rag_answer
from app.routers.assistant import _build_document_context


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def make_pdf(text_lines):
    """Build a small single-page PDF containing the given text lines."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 700
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def make_blank_pdf():
    """A PDF with no selectable text (a rectangle only) — like a scan."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 400, 200, 200)
    c.save()
    return buf.getvalue()


class FakeLLM(LLMProvider):
    """Records the prompt it received and returns a fixed JSON answer."""

    def __init__(self, answer="The document states curcumin content was 3.2%."):
        self.answer = answer
        self.calls = 0
        self.last_user_prompt = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.last_user_prompt = user_prompt
        return json.dumps(
            {
                "answer": self.answer,
                "insufficient_evidence": False,
                "citations": [],
                "warnings": [],
            }
        )


def upload_pdf(client, auth_headers, text_lines, filename="research.pdf", session_id=None):
    data = {"session_id": str(session_id)} if session_id else {}
    return client.post(
        "/api/assistant/attachments",
        headers=auth_headers,
        files={"file": (filename, make_pdf(text_lines), "application/pdf")},
        data=data,
    )


def chat(client, auth_headers, payload):
    return client.post("/api/assistant/chat", json=payload, headers=auth_headers)


# -------------------------------------------------------
# Upload endpoint
# -------------------------------------------------------

class TestUploadAttachment:
    def test_upload_extracts_text(self, client, auth_headers):
        resp = upload_pdf(
            client,
            auth_headers,
            ["Curcumin Yield Optimization Study 2026", "Marker QUANTUM-73: 3.2 percent"],
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["filename"] == "research.pdf"
        assert body["char_count"] > 50
        assert body["id"] > 0
        assert body["truncated"] is False
        assert body["session_id"] is None

    def test_upload_requires_auth(self, client):
        resp = client.post(
            "/api/assistant/attachments",
            files={"file": ("research.pdf", make_pdf(["hi"]), "application/pdf")},
        )
        assert resp.status_code == 401

    def test_upload_rejects_non_pdf_extension(self, client, auth_headers):
        resp = client.post(
            "/api/assistant/attachments",
            headers=auth_headers,
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_upload_rejects_invalid_pdf_bytes(self, client, auth_headers):
        resp = client.post(
            "/api/assistant/attachments",
            headers=auth_headers,
            files={"file": ("fake.pdf", b"this is not a pdf at all", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_pdf_without_text(self, client, auth_headers):
        resp = client.post(
            "/api/assistant/attachments",
            headers=auth_headers,
            files={"file": ("scan.pdf", make_blank_pdf(), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "no selectable text" in resp.json()["detail"]

    def test_upload_binds_to_own_session(self, client, auth_headers):
        # create a session (no corpus chunks + no attachment → early exit, no LLM)
        resp = chat(client, auth_headers, {"message": "start a session"})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        resp = upload_pdf(client, auth_headers, ["Session-bound document body."], session_id=session_id)
        assert resp.status_code == 201, resp.text
        assert resp.json()["session_id"] == session_id

    def test_upload_session_of_other_user_404(self, client, auth_headers, second_user_headers):
        resp = chat(client, second_user_headers, {"message": "their session"})
        assert resp.status_code == 200
        other_session = resp.json()["session_id"]

        resp = upload_pdf(client, auth_headers, ["mine"], session_id=other_session)
        assert resp.status_code == 404


# -------------------------------------------------------
# Chat with attachments
# -------------------------------------------------------

class TestChatWithAttachments:
    def test_attached_document_is_passed_to_the_llm(self, client, auth_headers, monkeypatch):
        fake = FakeLLM()
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        up = upload_pdf(
            client,
            auth_headers,
            ["Curcumin Yield Optimization Study 2026.", "Marker QUANTUM-73 measured 3.2 percent."],
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        resp = chat(
            client,
            auth_headers,
            {"message": "What was the QUANTUM-73 reading?", "attachment_ids": [att_id]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert fake.calls == 1
        assert "QUANTUM-73" in fake.last_user_prompt
        assert "USER-ATTACHED DOCUMENT" in fake.last_user_prompt
        assert body["answer"].startswith("The document states")
        assert body["insufficient_evidence"] is False
        assert body["citations"] == []
        assert "USER_PROVIDED" in body["provenance"]
        assert body["provider"] == "groq"

    def test_followup_reuses_session_attachment(self, client, auth_headers, monkeypatch):
        fake = FakeLLM()
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        up = upload_pdf(client, auth_headers, ["Persistent marker ALPHA-99 in the study."])
        att_id = up.json()["id"]

        r1 = chat(client, auth_headers, {"message": "Summarise this.", "attachment_ids": [att_id]})
        assert r1.status_code == 200
        session_id = r1.json()["session_id"]

        # follow-up WITHOUT re-attaching: the document must still be in context
        r2 = chat(client, auth_headers, {"message": "What marker was mentioned?", "session_id": session_id})
        assert r2.status_code == 200
        assert fake.calls == 2
        assert "ALPHA-99" in fake.last_user_prompt

    def test_attachment_of_other_user_404(self, client, auth_headers, second_user_headers, monkeypatch):
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: FakeLLM())
        up = upload_pdf(client, second_user_headers, ["private research of user B"])
        att_id = up.json()["id"]

        resp = chat(client, auth_headers, {"message": "use this", "attachment_ids": [att_id]})
        assert resp.status_code == 404

    def test_attachment_from_other_session_400(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: FakeLLM())

        r1 = chat(client, auth_headers, {"message": "session one"})
        s1 = r1.json()["session_id"]
        up = upload_pdf(client, auth_headers, ["bound to session one"], session_id=s1)
        att_id = up.json()["id"]

        r2 = chat(client, auth_headers, {"message": "session two"})
        s2 = r2.json()["session_id"]

        resp = chat(
            client, auth_headers,
            {"message": "try reusing", "session_id": s2, "attachment_ids": [att_id]},
        )
        assert resp.status_code == 400
        assert "different conversation" in resp.json()["detail"]

    def test_unknown_attachment_id_404(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: FakeLLM())
        resp = chat(client, auth_headers, {"message": "hi", "attachment_ids": [999999]})
        assert resp.status_code == 404


# -------------------------------------------------------
# Provider toggle
# -------------------------------------------------------

class TestProviderToggle:
    # These tests attach a small document so generation reaches the LLM
    # (an empty corpus with no attachment exits early, before provider use).

    def test_sarvam_selection_uses_strict_provider(self, client, auth_headers, monkeypatch):
        fake = FakeLLM(answer="Sarvam says hi.")
        monkeypatch.setattr("app.routers.assistant.get_llm_provider_for", lambda choice: fake)
        called = {}

        def _default():
            called["default"] = True
            raise AssertionError("default provider must not be used when sarvam is selected")

        monkeypatch.setattr("app.routers.assistant.get_llm_provider", _default)

        att_id = upload_pdf(client, auth_headers, ["Provider toggle document body."]).json()["id"]
        resp = chat(
            client, auth_headers,
            {"message": "hello", "provider": "sarvam", "attachment_ids": [att_id]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["provider"] == "sarvam"
        assert resp.json()["answer"] == "Sarvam says hi."
        assert "default" not in called

    def test_groq_selection_uses_default_chain(self, client, auth_headers, monkeypatch):
        fake = FakeLLM(answer="Groq says hi.")
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
        called = {}

        def _strict(choice):
            called["strict"] = choice
            raise AssertionError("strict provider resolver must not be used for groq")

        monkeypatch.setattr("app.routers.assistant.get_llm_provider_for", _strict)

        att_id = upload_pdf(client, auth_headers, ["Provider toggle document body."]).json()["id"]
        resp = chat(
            client, auth_headers,
            {"message": "hello", "provider": "groq", "attachment_ids": [att_id]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["provider"] == "groq"
        assert resp.json()["answer"] == "Groq says hi."
        assert "strict" not in called

    def test_omitted_provider_defaults_to_groq(self, client, auth_headers, monkeypatch):
        fake = FakeLLM()
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
        att_id = upload_pdf(client, auth_headers, ["Default provider document."]).json()["id"]
        resp = chat(client, auth_headers, {"message": "hello", "attachment_ids": [att_id]})
        assert resp.status_code == 200
        assert resp.json()["provider"] == "groq"
        assert fake.calls == 1

    def test_unknown_provider_rejected(self, client, auth_headers):
        resp = chat(client, auth_headers, {"message": "hello", "provider": "openai"})
        assert resp.status_code == 422


# -------------------------------------------------------
# Generation layer (document context, no corpus chunks)
# -------------------------------------------------------

class TestGenerateWithDocumentContext:
    def test_answers_from_document_when_corpus_is_empty(self):
        fake = FakeLLM(answer="3.2 percent.")
        resp = generate_rag_answer(
            query="What was the reading?",
            chunks=[],
            llm=fake,
            document_context="Attached: study.pdf\nMarker QUANTUM-73 = 3.2 percent",
        )
        assert fake.calls == 1
        assert "QUANTUM-73" in fake.last_user_prompt
        assert resp.insufficient_evidence is False
        assert resp.answer == "3.2 percent."
        assert resp.citations == []

    def test_still_insufficient_without_document_or_chunks(self):
        class Boom:
            def generate(self, system_prompt, user_prompt):
                raise AssertionError("must not call the LLM")

        resp = generate_rag_answer(query="q", chunks=[], llm=Boom())
        assert resp.insufficient_evidence is True

    def test_hallucinated_citations_dropped_for_attachment_only_answers(self):
        class CitingLLM:
            def generate(self, system_prompt, user_prompt):
                return json.dumps(
                    {
                        "answer": "From your document: 3.2 percent.",
                        "insufficient_evidence": False,
                        "citations": [
                            {"chunk_id": 999, "document_id": 999, "title": "x", "source_type": "USER_PROVIDED", "relevant_text": "y"}
                        ],
                        "warnings": [],
                    }
                )

        resp = generate_rag_answer(
            query="q", chunks=[], llm=CitingLLM(), document_context="doc text"
        )
        assert resp.insufficient_evidence is False
        assert resp.citations == []
        assert any("not verified against the corpus" in w for w in resp.warnings)


# -------------------------------------------------------
# Document context builder cap
# -------------------------------------------------------

class TestBuildContextCap:
    def test_no_attachments_returns_none(self):
        assert _build_document_context([]) == (None, None)

    def test_short_context_kept_whole(self):
        att = SimpleNamespace(filename="a.pdf", extracted_text="short text")
        context, warning = _build_document_context([att])
        assert "short text" in context
        assert "a.pdf" in context
        assert warning is None

    def test_long_context_capped_with_warning(self):
        from app.routers.assistant import CHAT_DOC_CONTEXT_CHARS

        att = SimpleNamespace(filename="big.pdf", extracted_text="x" * (CHAT_DOC_CONTEXT_CHARS + 50_000))
        context, warning = _build_document_context([att])
        assert context is not None
        assert len(context) <= CHAT_DOC_CONTEXT_CHARS
        assert warning is not None
        assert "characters" in warning
