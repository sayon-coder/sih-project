"""
Explicit jurisdiction switch (SIH: national vs international layers kept
separate).

The chat toolbar's Both / India / International switch sends
``jurisdiction_mode``; the backend resolves retrieval scope from it BEFORE the
passport-market scope ("both" preserves the market-derived behaviour
exactly). Unlabelled documents cannot be verified as either regime, so the
strict modes exclude them.

No network: the LLM is scripted through a get_llm_provider patch at the
router boundary (same convention as test_chat_jurisdiction). Retrieval is
real (SQLite keyword arm of hybrid_retrieve on seeded corpus documents).
"""
import json

from tests.test_chat_jurisdiction import ScriptedLLM, chat, seed_corpus

QUESTION = "What are the patent requirements for Ayurvedic formulations?"


def seed_three(db_session):
    """One India, one International, one unlabelled document on one topic."""
    india = seed_corpus(
        db_session,
        "India Patent Guide",
        "Ayurvedic formulation patent requirements under the Indian Patents "
        "Act include a complete specification and Section 3 exclusions.",
        jurisdiction="India",
    )
    intl = seed_corpus(
        db_session,
        "PCT International Guide",
        "Ayurvedic formulation patent requirements under the PCT route use "
        "an international search and national phase entry.",
        jurisdiction="International",
    )
    untagged = seed_corpus(
        db_session,
        "Undated Patent Memo",
        "Ayurvedic formulation patent requirements memo with no recorded "
        "jurisdiction and no verifiable regime.",
        jurisdiction=None,
    )
    return india, intl, untagged


def answer_citing(*seeded, answer="Patent requirements differ by regime."):
    """Scripted single-path answer citing every seeded chunk."""
    citations = [
        {
            "chunk_id": chunk.id,
            "document_id": doc.id,
            "title": doc.title,
            "source_type": "official_guidance",
            "relevant_text": chunk.text[:120],
        }
        for doc, chunk in seeded
    ]
    return json.dumps({
        "answer": answer,
        "insufficient_evidence": False,
        "citations": citations,
        "warnings": [],
    })


def cited_titles(body):
    return {c["title"] for c in body["citations"]}


def test_india_mode_cites_only_indian_sources(
    client, auth_headers, db_session, monkeypatch
):
    india, intl, untagged = seed_three(db_session)
    fake = ScriptedLLM(answer_citing(india, intl, untagged))
    monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
    resp = chat(client, auth_headers, {
        "message": QUESTION, "jurisdiction_mode": "india",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jurisdiction_mode"] == "india"
    assert body["jurisdiction_filter"] == ["India"]
    assert cited_titles(body) == {"India Patent Guide"}


def test_international_mode_excludes_india_and_unlabelled(
    client, auth_headers, db_session, monkeypatch
):
    india, intl, untagged = seed_three(db_session)
    fake = ScriptedLLM(answer_citing(india, intl, untagged))
    monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
    resp = chat(client, auth_headers, {
        "message": QUESTION, "jurisdiction_mode": "international",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jurisdiction_mode"] == "international"
    assert "India" not in body["jurisdiction_filter"]
    assert "International" in body["jurisdiction_filter"]
    assert cited_titles(body) == {"PCT International Guide"}


def test_both_default_preserves_unscoped_behaviour(
    client, auth_headers, db_session, monkeypatch
):
    india, intl, untagged = seed_three(db_session)
    fake = ScriptedLLM(answer_citing(india, intl, untagged))
    monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
    resp = chat(client, auth_headers, {"message": QUESTION})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jurisdiction_mode"] == "both"
    assert cited_titles(body) == {
        "India Patent Guide", "PCT International Guide", "Undated Patent Memo",
    }


def test_invalid_mode_rejected(client, auth_headers, db_session):
    seed_three(db_session)
    resp = chat(client, auth_headers, {
        "message": QUESTION, "jurisdiction_mode": "europe",
    })
    assert resp.status_code == 422


def test_strict_mode_reaches_the_model_prompt(
    client, auth_headers, db_session, monkeypatch
):
    india, intl, untagged = seed_three(db_session)
    fake = ScriptedLLM(answer_citing(india))
    monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
    resp = chat(client, auth_headers, {
        "message": QUESTION, "jurisdiction_mode": "india",
    })
    assert resp.status_code == 200, resp.text
    assert fake.calls >= 1
    assert (
        "Human-selected jurisdiction scope: INDIA ONLY"
        in fake.system_prompts[-1] + fake.user_prompts[-1]
    )
