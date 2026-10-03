"""
pgvector cosine similarity search.

Uses PostgreSQL's array-to-vector cast with the pgvector ``<=>`` operator
(cosine distance).  Lower distance = higher similarity, so we return
1 - distance as the score.

Metadata filtering is applied in SQL for efficiency.
"""
from __future__ import annotations

import logging
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.schemas import MetadataFilter, RetrievedChunk

logger = logging.getLogger(__name__)

# BGE-M3 query prefix for retrieval
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def vector_search(
    db: Session,
    query_embedding: List[float],
    top_k: int = 20,
    filters: MetadataFilter = MetadataFilter(),
    user_id: int = None,
    embedding_dim: int = 1024,
) -> List[RetrievedChunk]:
    """
    Retrieve the top_k most similar chunks using pgvector cosine distance.

    The embedding vector is inlined directly into the SQL string as a
    PostgreSQL array literal (e.g. '[0.1,0.2,...]'::vector(1024)).
    This avoids the psycopg2 named-parameter conflict caused by the
    ``::`` cast operator immediately following a ``:name`` placeholder.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    query_embedding:
        Dense query embedding from the embedding provider.
    top_k:
        Maximum number of results to return.
    filters:
        Metadata filter constraints.
    user_id:
        The requesting user's ID — used to include their private documents.
    embedding_dim:
        Dimension of the embedding vector.

    Returns
    -------
    List of RetrievedChunk sorted by similarity (descending).
    """
    # Inline the embedding as a PostgreSQL vector literal to avoid
    # the psycopg2 ':param::type' syntax conflict.
    embedding_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
    vec_expr = f"'{embedding_literal}'::vector({embedding_dim})"

    # Build WHERE clause
    where_clauses = ["sc.embedding IS NOT NULL"]
    params: dict = {"top_k": top_k}

    # Public / private filter
    if user_id is not None:
        where_clauses.append("(sd.is_public = TRUE OR sd.uploader_id = :user_id)")
        params["user_id"] = user_id
    else:
        where_clauses.append("sd.is_public = TRUE")

    where_clauses.append("sd.status = 'INDEXED'")

    if filters.source_types:
        where_clauses.append("sd.source_type = ANY(:source_types)")
        params["source_types"] = filters.source_types

    if filters.jurisdictions:
        where_clauses.append("sd.jurisdiction = ANY(:jurisdictions)")
        params["jurisdictions"] = filters.jurisdictions

    if filters.language:
        where_clauses.append("sd.language = :language")
        params["language"] = filters.language

    where_sql = " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT
            sc.id          AS chunk_id,
            sc.document_id,
            sd.title,
            sd.source_type,
            sd.jurisdiction,
            sd.language,
            sd.publication_date::text,
            sd.source_url,
            sc.text,
            sc.page_number,
            1 - (sc.embedding::vector({embedding_dim}) <=> {vec_expr}) AS similarity
        FROM source_chunks sc
        JOIN source_documents sd ON sd.id = sc.document_id
        WHERE {where_sql}
        ORDER BY sc.embedding::vector({embedding_dim}) <=> {vec_expr} ASC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.error("Vector search failed: %s", exc)
        # Rollback so the session is clean for subsequent queries
        try:
            db.rollback()
        except Exception:
            pass
        return []

    results = []
    for row in rows:
        if row.similarity < 0.0:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                title=row.title,
                source_type=row.source_type,
                jurisdiction=row.jurisdiction,
                language=row.language or "en",
                publication_date=row.publication_date,
                source_url=row.source_url,
                text=row.text,
                page_number=row.page_number,
                vector_score=float(row.similarity),
            )
        )

    logger.debug("Vector search: %d results", len(results))
    return results
