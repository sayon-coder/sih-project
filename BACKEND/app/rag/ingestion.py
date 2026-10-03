"""
RAG ingestion pipeline.

Orchestrates: parse → chunk → embed (when available) → store → index.

Entry point:
    ingest_document(db, document_id)          # file on disk
    store_parsed_chunks(db, doc, parsed)      # text already parsed

Embedding is deliberately **non-fatal**: when the embedding model is not
available, chunks are stored without vectors and the document is still
marked INDEXED, because the keyword arm can search them. Failing the whole
upload (the old behaviour) left user documents invisible to retrieval and
produced the "insufficient evidence" experience for content that was really
there. Every degradation is logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.embeddings.provider import get_embedding_provider
from app.models.rag_models import SourceChunk, SourceDocument
from app.rag.chunking import chunk_document
from app.rag.parser import parse_document
from app.rag.schemas import ParsedDocument

logger = logging.getLogger(__name__)

# BGE-M3 passage prefix used when indexing chunks
PASSAGE_PREFIX = "Represent this passage for retrieval: "


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file for duplicate detection."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            sha256.update(block)
    return sha256.hexdigest()


def compute_text_hash(text_value: str) -> str:
    """SHA-256 of a text value (per-chunk content hash)."""
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def provenance_for_document(doc: SourceDocument) -> str:
    """Provenance label for chunks of a document (spec vocabulary)."""
    if (doc.source_type or "").upper() == "EXPERT_VERIFIED":
        return "EXPERT_VERIFIED"
    return "VERIFIED_PUBLIC_SOURCE" if doc.is_public else "USER_PROVIDED"


def ingest_document(db: Session, document_id: int) -> SourceDocument:
    """Ingest a document: parse → chunk → embed → store chunks → mark INDEXED.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    document_id:
        ID of the SourceDocument row that has already been created.

    Returns
    -------
    The updated SourceDocument row.

    Raises
    ------
    ValueError:
        If the document is not found or its file_path is missing.
    """
    doc = db.get(SourceDocument, document_id)
    if doc is None:
        raise ValueError(f"SourceDocument {document_id} not found")
    if not doc.file_path:
        raise ValueError(f"SourceDocument {document_id} has no file_path set")

    # Mark as in-progress
    doc.status = "INDEXING"
    db.commit()

    try:
        logger.info("Ingesting document %d: '%s'", document_id, doc.title)
        parsed = parse_document(doc.file_path)
        return store_parsed_chunks(db, doc, parsed)
    except Exception as exc:
        logger.error("Ingestion failed for document %d: %s", document_id, exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        doc.status = "FAILED"
        doc.error_message = str(exc)[:1000]
        db.commit()
        raise


def store_parsed_chunks(
    db: Session,
    doc: SourceDocument,
    parsed: ParsedDocument,
    replace: bool = True,
) -> int:
    """Chunk an already-parsed document, store it and mark it INDEXED.

    This is the shared store step used by both the knowledge-base file
    ingestion and the chat PDF attachment upload (which parses in memory).

    Guarantees
    ----------
    * empty chunks are never stored;
    * every chunk carries page number, section, provenance and a
      per-chunk ``content_hash`` in ``metadata_json``;
    * embedding failure degrades to keyword-only search instead of
      failing the upload;
    * the full-text index is only touched on PostgreSQL;
    * duplicate ingestion of the same content is prevented by the caller
      (``document_hash`` on SourceDocument).
    """
    settings = get_settings()

    chunks = chunk_document(
        parsed,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        extra_metadata={
            "source_type": doc.source_type,
            "jurisdiction": doc.jurisdiction,
            "language": doc.language,
            "document_id": doc.id,
            "title": doc.title,
        },
    )
    chunks = [c for c in chunks if c.text and c.text.strip()]

    if replace:
        db.query(SourceChunk).filter(SourceChunk.document_id == doc.id).delete()
        db.flush()

    # Embeddings: optional, degrade openly.
    embeddings: Optional[list] = None
    if chunks:
        try:
            provider = get_embedding_provider()
            prefixed = [PASSAGE_PREFIX + c.text for c in chunks]
            embeddings = provider.embed(prefixed)
        except Exception as exc:
            logger.warning(
                "Embeddings unavailable for document %s (%s) — storing keyword-only chunks",
                doc.id,
                exc,
            )
            embeddings = None

    provenance = provenance_for_document(doc)
    rows = []
    for idx, chunk in enumerate(chunks):
        metadata_dict = {
            "source_type": doc.source_type,
            "jurisdiction": doc.jurisdiction,
            "language": doc.language,
            "title": doc.title,
            "document_id": doc.id,
            "is_public": doc.is_public,
            "uploader_id": doc.uploader_id,
            "page": chunk.page_number,
            "section": (chunk.metadata or {}).get("section", ""),
            "provenance": provenance,
            "content_hash": compute_text_hash(chunk.text),
        }
        rows.append(
            SourceChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                page_number=chunk.page_number,
                embedding=(embeddings[idx] if embeddings is not None else None),
                metadata_json=json.dumps(metadata_dict, ensure_ascii=False),
            )
        )

    if rows:
        db.add_all(rows)
        db.flush()

    # Full-text index refresh (PostgreSQL only - other dialects have no
    # tsvector; their keyword path matches on the text column directly).
    if db.get_bind().dialect.name == "postgresql" and rows:
        db.execute(
            text(
                """
                UPDATE source_chunks
                SET search_vector = to_tsvector('english', text)
                WHERE document_id = :doc_id
                """
            ),
            {"doc_id": doc.id},
        )

    doc.status = "INDEXED"
    doc.chunk_count = len(rows)
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    logger.info(
        "Indexed document %s '%s': %d page(s), %d char(s), %d chunk(s), embeddings=%s",
        doc.id,
        doc.title,
        parsed.num_pages,
        len(parsed.text),
        len(rows),
        "yes" if embeddings is not None else "no (keyword-only)",
    )
    return len(rows)
