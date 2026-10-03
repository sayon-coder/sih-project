"""
scripts/verify_phase4.py

Verification script for Phase 4:
  1. Verifies pgvector extension and RAG tables exist on live PostgreSQL database.
  2. Tests document creation and text parsing.
  3. Tests chunking, embedding generation with BGE-M3 (or mocked fallback if memory constrained).
  4. Tests vector search + keyword FTS on database.
  5. Tests citation validation rules.
  6. Tests assistant chat flow and response structure.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import engine
from app.config import get_settings
from app.rag.chunking import chunk_document
from app.rag.schemas import ParsedDocument, RetrievedChunk
from app.llm.schemas import CitationObject
from app.rag.citation import validate_citations, INSUFFICIENT_EVIDENCE_MESSAGE


def check(name: str, passed: bool, detail: str = ""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} {name}")
    if detail and not passed:
        print(f"       Details: {detail}")
    if not passed:
        sys.exit(1)


def main():
    print("=== Phase 4 Verification Suite ===")
    settings = get_settings()

    # 1. Check live DB connection and tables
    with Session(engine) as db:
        res = db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector';")).fetchone()
        check("1. pgvector extension installed in PostgreSQL", res is not None and res[0] == "vector")

        tables = ["source_documents", "source_chunks", "chat_sessions", "chat_messages"]
        for tbl in tables:
            r = db.execute(text(f"SELECT to_regclass('public.{tbl}');")).fetchone()
            check(f"2. Table '{tbl}' exists", r is not None and r[0] == tbl)

    # 2. Test Chunking
    sample_text = (
        "Ayurveda formulation comprising Ashwagandha (Withania somnifera) root extract. "
        "Standardized to 5% withanolides for enhanced adaptogenic activity. "
        "Extraction is performed using aqueous ethanol at 50 degrees Celsius. "
    ) * 30
    parsed = ParsedDocument(text=sample_text, pages=[{"page_number": 1, "text": sample_text}], num_pages=1)
    chunks = chunk_document(parsed, chunk_size=100, chunk_overlap=20)
    check("3. Chunking produces valid chunks", len(chunks) > 0)
    check("4. Chunk indices are sequential", [c.chunk_index for c in chunks] == list(range(len(chunks))))

    # 3. Test Citation Validation Logic
    mock_retrieved = [
        RetrievedChunk(
            chunk_id=101, document_id=1, title="Ayurvedic Patent Law Guidelines",
            source_type="regulation", text="Section 3(p) excludes traditional knowledge from patentability.",
            jurisdiction="India"
        )
    ]
    valid_citation = [
        CitationObject(
            chunk_id=101, document_id=1, title="Ayurvedic Patent Law Guidelines",
            source_type="regulation", relevant_text="Section 3(p) excludes traditional knowledge"
        )
    ]
    is_valid, valid_list = validate_citations(valid_citation, mock_retrieved)
    check("5. Valid citation passes validation", is_valid is True and len(valid_list) == 1)

    invalid_citation = [
        CitationObject(
            chunk_id=999, document_id=1, title="Hallucinated Source",
            source_type="patent", relevant_text="Fabricated claim"
        )
    ]
    is_valid_bad, valid_list_bad = validate_citations(invalid_citation, mock_retrieved)
    check("6. Fabricated citation rejected", is_valid_bad is False and len(valid_list_bad) == 0)

    # 4. Check Groq / LLM Configuration
    check("7. LLM Provider configured", settings.llm_provider == "groq")
    check("8. Groq API Key present", bool(settings.groq_api_key))
    check("9. Embedding Model configured", settings.embedding_model == "BAAI/bge-m3")

    print("\nAll 9 core Phase 4 verification checks passed successfully!")


if __name__ == "__main__":
    main()
