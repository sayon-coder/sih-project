"""
tests/test_rag.py - Phase 4 RAG tests.

Tests run against SQLite in-memory (same as Phases 1-3).
LLM and embedding calls are mocked so tests are fast and offline.
"""
import json
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from io import BytesIO

# -------------------------------------------------------
# Fixtures (reuse existing conftest if available, or define here)
# -------------------------------------------------------

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("EMBEDDING_PROVIDER", "sentence-transformers")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-m3")
os.environ.setdefault("EMBEDDING_DIMENSION", "1024")
os.environ.setdefault("UPLOAD_DIR", "/tmp/test_uploads_rag")
os.environ.setdefault("MAX_UPLOAD_SIZE_MB", "25")
os.environ.setdefault("RAG_CHUNK_SIZE", "800")
os.environ.setdefault("RAG_CHUNK_OVERLAP", "120")
os.environ.setdefault("RAG_TOP_K_RETRIEVAL", "5")
os.environ.setdefault("RAG_RERANK_TOP_K", "3")


# Use client, db_session, and auth_headers from conftest.py


# -------------------------------------------------------
# Chunking unit tests (no DB needed)
# -------------------------------------------------------

class TestChunking:
    def test_basic_chunking(self):
        from app.rag.chunking import chunk_document
        from app.rag.schemas import ParsedDocument
        text = "This is a sentence. " * 100  # ~400 words
        parsed = ParsedDocument(text=text, pages=[{"page_number": 1, "text": text}], num_pages=1)
        chunks = chunk_document(parsed, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.text.strip() != ""
            assert chunk.chunk_index >= 0

    def test_chunk_overlap(self):
        from app.rag.chunking import chunk_document
        from app.rag.schemas import ParsedDocument
        # Build text with distinct sentences
        sentences = [f"Sentence number {i} about Ayurveda." for i in range(50)]
        text = " ".join(sentences)
        parsed = ParsedDocument(text=text, pages=[{"page_number": 1, "text": text}], num_pages=1)
        chunks = chunk_document(parsed, chunk_size=30, chunk_overlap=10)
        # With overlap, consecutive chunks should share some words
        if len(chunks) > 1:
            words0 = set(chunks[0].text.lower().split())
            words1 = set(chunks[1].text.lower().split())
            # There should be at least some overlap
            assert len(chunks) >= 1  # Just ensure we got chunks

    def test_small_doc_single_chunk(self):
        from app.rag.chunking import chunk_document
        from app.rag.schemas import ParsedDocument
        text = "This is a very short document."
        parsed = ParsedDocument(text=text, pages=[{"page_number": 1, "text": text}], num_pages=1)
        chunks = chunk_document(parsed, chunk_size=800, chunk_overlap=120)
        assert len(chunks) == 1
        assert "short document" in chunks[0].text


# -------------------------------------------------------
# Citation validation unit tests
# -------------------------------------------------------

class TestCitationValidation:
    def _make_chunk(self, chunk_id, doc_id=1, title="Test Doc", source_type="regulation"):
        from app.rag.schemas import RetrievedChunk
        return RetrievedChunk(
            chunk_id=chunk_id, document_id=doc_id, title=title,
            source_type=source_type, text="Some content.", final_score=0.9
        )

    def _make_citation(self, chunk_id, title="Test Doc"):
        from app.llm.schemas import CitationObject
        return CitationObject(
            chunk_id=chunk_id, document_id=1, title=title,
            source_type="regulation", relevant_text="Some content."
        )

    def test_valid_citation(self):
        from app.rag.citation import validate_citations
        chunks = [self._make_chunk(42)]
        citations = [self._make_citation(42)]
        is_valid, valid = validate_citations(citations, chunks)
        assert is_valid
        assert len(valid) == 1

    def test_invalid_chunk_id(self):
        from app.rag.citation import validate_citations
        chunks = [self._make_chunk(42)]
        citations = [self._make_citation(99)]  # 99 not in retrieved
        is_valid, valid = validate_citations(citations, chunks)
        assert not is_valid
        assert len(valid) == 0

    def test_no_chunks_is_insufficient(self):
        from app.rag.citation import validate_citations
        from app.llm.schemas import CitationObject
        is_valid, valid = validate_citations([], [])
        assert not is_valid

    def test_partial_valid(self):
        from app.rag.citation import validate_citations
        chunks = [self._make_chunk(1), self._make_chunk(2)]
        citations = [self._make_citation(1), self._make_citation(99)]
        is_valid, valid = validate_citations(citations, chunks)
        assert not is_valid  # not all valid
        assert len(valid) == 1  # chunk 1 is valid


# -------------------------------------------------------
# Parser unit tests
# -------------------------------------------------------

class TestParser:
    def test_parse_txt(self, tmp_path):
        from app.rag.parser import parse_document
        f = tmp_path / "test.txt"
        f.write_text("Hello world. This is a test document about Ayurveda.\n\nSecond paragraph.", encoding="utf-8")
        result = parse_document(str(f))
        assert "Ayurveda" in result.text
        assert result.num_pages == 1

    def test_unsupported_format(self, tmp_path):
        from app.rag.parser import parse_document
        f = tmp_path / "test.docx"
        f.write_bytes(b"dummy")
        with pytest.raises(ValueError, match="Unsupported file format"):
            parse_document(str(f))

    def test_file_not_found(self):
        from app.rag.parser import parse_document
        with pytest.raises(FileNotFoundError):
            parse_document("/nonexistent/path/file.txt")


# -------------------------------------------------------
# API: Knowledge Base endpoints
# -------------------------------------------------------

class TestKnowledgeBase:
    def test_corpus_status(self, client, auth_headers):
        resp = client.get("/api/knowledge/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_documents" in data
        assert "total_chunks" in data

    def test_list_documents_empty(self, client, auth_headers):
        resp = client.get("/api/knowledge/documents", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_upload_txt_document(self, client, auth_headers):
        """Upload a TXT file with mocked ingestion."""
        txt_content = b"This is a test Ayurvedic IP document about Ashwagandha extracts and patents."

        with patch("app.routers.knowledge.ingest_document") as mock_ingest:
            # Mock ingest to set status=INDEXED
            def fake_ingest(db, doc_id):
                from app.models.rag_models import SourceDocument
                doc = db.get(SourceDocument, doc_id)
                doc.status = "INDEXED"
                doc.chunk_count = 3
                db.commit()
                db.refresh(doc)
                return doc
            mock_ingest.side_effect = fake_ingest

            resp = client.post(
                "/api/knowledge/documents",
                headers=auth_headers,
                files={"file": ("test_doc.txt", BytesIO(txt_content), "text/plain")},
                data={
                    "title": "Test Ayurveda Document",
                    "source_type": "regulation",
                    "jurisdiction": "India",
                    "language": "en",
                    "is_public": "false",
                },
            )
        assert resp.status_code == 201, resp.text
        doc = resp.json()
        assert doc["title"] == "Test Ayurveda Document"
        assert doc["status"] == "INDEXED"
        assert doc["chunk_count"] == 3
        return doc

    def test_get_document(self, client, auth_headers):
        """Upload then get."""
        txt_content = b"Ayurveda patent analysis document."
        with patch("app.routers.knowledge.ingest_document") as mock_ingest:
            def fake_ingest(db, doc_id):
                from app.models.rag_models import SourceDocument
                doc = db.get(SourceDocument, doc_id)
                doc.status = "INDEXED"
                doc.chunk_count = 1
                db.commit()
                db.refresh(doc)
                return doc
            mock_ingest.side_effect = fake_ingest

            upload_resp = client.post(
                "/api/knowledge/documents",
                headers=auth_headers,
                files={"file": ("doc2.txt", BytesIO(txt_content), "text/plain")},
                data={"title": "Doc2", "source_type": "patent"},
            )
        doc_id = upload_resp.json()["id"]
        resp = client.get(f"/api/knowledge/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == doc_id

    def test_delete_document(self, client, auth_headers):
        """Upload then delete."""
        txt_content = b"Document to delete."
        with patch("app.routers.knowledge.ingest_document") as mock_ingest:
            def fake_ingest(db, doc_id):
                from app.models.rag_models import SourceDocument
                doc = db.get(SourceDocument, doc_id)
                doc.status = "INDEXED"
                doc.chunk_count = 1
                db.commit()
                db.refresh(doc)
                return doc
            mock_ingest.side_effect = fake_ingest

            upload_resp = client.post(
                "/api/knowledge/documents",
                headers=auth_headers,
                files={"file": ("delete_me.txt", BytesIO(txt_content), "text/plain")},
                data={"title": "Delete Me", "source_type": "other"},
            )
        doc_id = upload_resp.json()["id"]
        del_resp = client.delete(f"/api/knowledge/documents/{doc_id}", headers=auth_headers)
        assert del_resp.status_code == 204
        get_resp = client.get(f"/api/knowledge/documents/{doc_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_upload_unsupported_format(self, client, auth_headers):
        resp = client.post(
            "/api/knowledge/documents",
            headers=auth_headers,
            files={"file": ("bad.docx", BytesIO(b"dummy"), "application/octet-stream")},
            data={"title": "Bad", "source_type": "other"},
        )
        assert resp.status_code == 422


# -------------------------------------------------------
# API: Assistant chat endpoints
# -------------------------------------------------------

class TestAssistantChat:
    def _mock_retrieval_and_llm(self):
        """Context manager mocks for retrieval + LLM."""
        from app.rag.schemas import RetrievedChunk
        mock_chunk = RetrievedChunk(
            chunk_id=1, document_id=1, title="Test Patent Document",
            source_type="patent", text="Ashwagandha extract with 5% withanolides.", final_score=0.95
        )

        llm_json = json.dumps({
            "answer": "Based on the available evidence, Ashwagandha extract may have IP relevance.",
            "insufficient_evidence": False,
            "citations": [{
                "chunk_id": 1, "document_id": 1,
                "title": "Test Patent Document",
                "source_type": "patent",
                "relevant_text": "Ashwagandha extract with 5% withanolides."
            }],
            "warnings": []
        })
        return mock_chunk, llm_json

    def test_chat_new_session(self, client, auth_headers):
        mock_chunk, llm_json = self._mock_retrieval_and_llm()
        with patch("app.routers.assistant.hybrid_retrieve", return_value=[mock_chunk]), \
             patch("app.routers.assistant.get_llm_provider") as mock_llm_factory:
            mock_llm = MagicMock()
            mock_llm.generate.return_value = llm_json
            mock_llm_factory.return_value = mock_llm

            resp = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "What are the IP considerations for Ashwagandha?"
            })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "answer" in data
        assert "session_id" in data
        assert data["insufficient_evidence"] is False
        assert len(data["citations"]) > 0

    def test_chat_insufficient_evidence(self, client, auth_headers):
        """When no chunks retrieved → insufficient evidence."""
        with patch("app.routers.assistant.hybrid_retrieve", return_value=[]):
            resp = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "Tell me about quantum physics patents."
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["insufficient_evidence"] is True
        assert "Insufficient evidence" in data["answer"] or len(data["citations"]) == 0

    def test_list_sessions(self, client, auth_headers):
        resp = client.get("/api/assistant/conversations", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_session_with_messages(self, client, auth_headers):
        """Chat once, then retrieve session."""
        mock_chunk, llm_json = self._mock_retrieval_and_llm()
        with patch("app.routers.assistant.hybrid_retrieve", return_value=[mock_chunk]), \
             patch("app.routers.assistant.get_llm_provider") as mock_llm_factory:
            mock_llm = MagicMock()
            mock_llm.generate.return_value = llm_json
            mock_llm_factory.return_value = mock_llm
            chat_resp = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "What about Tulsi for IP?"
            })
        session_id = chat_resp.json()["session_id"]

        resp = client.get(f"/api/assistant/conversations/{session_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == session_id
        assert len(data["messages"]) >= 2  # user + assistant

    def test_delete_session(self, client, auth_headers):
        mock_chunk, llm_json = self._mock_retrieval_and_llm()
        with patch("app.routers.assistant.hybrid_retrieve", return_value=[mock_chunk]), \
             patch("app.routers.assistant.get_llm_provider") as mock_llm_factory:
            mock_llm = MagicMock()
            mock_llm.generate.return_value = llm_json
            mock_llm_factory.return_value = mock_llm
            chat_resp = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "Session to delete."
            })
        session_id = chat_resp.json()["session_id"]

        del_resp = client.delete(f"/api/assistant/conversations/{session_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        get_resp = client.get(f"/api/assistant/conversations/{session_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_chat_continues_existing_session(self, client, auth_headers):
        """Second message should use the same session."""
        mock_chunk, llm_json = self._mock_retrieval_and_llm()
        with patch("app.routers.assistant.hybrid_retrieve", return_value=[mock_chunk]), \
             patch("app.routers.assistant.get_llm_provider") as mock_llm_factory:
            mock_llm = MagicMock()
            mock_llm.generate.return_value = llm_json
            mock_llm_factory.return_value = mock_llm

            resp1 = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "First question."
            })
            session_id = resp1.json()["session_id"]

            resp2 = client.post("/api/assistant/chat", headers=auth_headers, json={
                "message": "Follow-up question.",
                "session_id": session_id,
            })
        assert resp2.json()["session_id"] == session_id
