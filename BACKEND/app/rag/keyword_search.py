"""
Keyword / full-text search arm of the hybrid retriever.

Two dialect paths:

* **PostgreSQL** — ``tsvector @@ to_tsquery`` with an **OR** of every query
  term and ``ts_rank_cd`` ranking. The previous build used
  ``plainto_tsquery``, which ANDs all terms; against ~250-word chunks a
  multi-part question matched nothing (``0`` rows even for simple questions)
  and every such question fell through to the global abstention message.
  With OR semantics a chunk matching any subset of the terms is a
  candidate, and cover-density ranking prefers chunks matching more of them.

* **Portable fallback** (SQLite in tests/dev) — ``LOWER(text) LIKE`` per term
  with a match-count score, so non-PostgreSQL environments exercise *real*
  keyword retrieval instead of silently returning nothing.

Access control, status and metadata filters behave identically in both paths.
Results are combined with the vector arm via RRF in retrieval.py.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.schemas import MetadataFilter, RetrievedChunk

logger = logging.getLogger(__name__)

# Maximum terms sent to the search engine. Long queries are capped to the
# most specific (longest) terms so ranking stays meaningful.
MAX_QUERY_TERMS = 24

# Small closed stop-word list: removes glue words before matching so the
# cap is spent on content terms. The English dictionary would drop these
# anyway, but doing it here also keeps the portable path precise.
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "being", "it", "its", "this",
    "that", "these", "those", "with", "as", "at", "by", "from", "into",
    "than", "then", "there", "their", "they", "them", "we", "you", "your",
    "our", "us", "i", "he", "she", "his", "her", "him", "my", "me", "not",
    "no", "if", "but", "so", "do", "does", "did", "done", "have", "has",
    "had", "will", "would", "can", "could", "should", "shall", "may",
    "might", "must", "about", "also", "any", "all", "each", "such", "per",
    "via", "etc", "am", "get", "got", "please", "tell", "give", "show",
    "what", "which", "who", "whom", "how", "when", "where", "why",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’%°\-]*")


def query_terms(query: str, limit: int = MAX_QUERY_TERMS) -> List[str]:
    """Sanitised, de-duplicated, stop-word-free terms for matching.

    Longest first: the cap is spent on the most specific words, which is
    what raises precision for long multi-part questions.
    """
    seen: List[str] = []
    for raw in _TOKEN_RE.findall(query.lower()):
        if raw in _STOP_WORDS or raw in seen:
            continue
        # Guard against pathological tokens (e.g. 200-character words)
        if len(raw) > 60:
            continue
        seen.append(raw)
    seen.sort(key=len, reverse=True)
    return seen[:limit]


def _access_and_filters(
    filters: MetadataFilter,
    user_id: Optional[int],
    params: Dict,
    pg: bool,
) -> List[str]:
    """WHERE fragments shared by both dialect paths."""
    where = ["sd.status = 'INDEXED'"]

    if user_id is not None:
        where.append("(sd.is_public = :is_public_true OR sd.uploader_id = :user_id)")
        params["user_id"] = user_id
    else:
        where.append("sd.is_public = :is_public_true")
    params["is_public_true"] = True

    if filters.source_types:
        if pg:
            where.append("sd.source_type = ANY(:source_types)")
            params["source_types"] = filters.source_types
        else:
            placeholders = []
            for i, st in enumerate(filters.source_types):
                placeholders.append(f":source_type_{i}")
                params[f"source_type_{i}"] = st
            where.append(f"sd.source_type IN ({', '.join(placeholders)})")

    if filters.jurisdictions:
        if pg:
            where.append("sd.jurisdiction = ANY(:jurisdictions)")
            params["jurisdictions"] = filters.jurisdictions
        else:
            placeholders = []
            for i, jur in enumerate(filters.jurisdictions):
                placeholders.append(f":jurisdiction_{i}")
                params[f"jurisdiction_{i}"] = jur
            where.append(f"sd.jurisdiction IN ({', '.join(placeholders)})")

    if filters.language:
        where.append("sd.language = :language")
        params["language"] = filters.language

    return where


def keyword_search(
    db: Session,
    query: str,
    top_k: int = 20,
    filters: MetadataFilter = MetadataFilter(),
    user_id: Optional[int] = None,
) -> List[RetrievedChunk]:
    """
    Keyword search: OR-of-terms full-text ranking (PostgreSQL) or a
    portable match-count fallback (SQLite and other dialects).

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    query:
        The raw (possibly expanded) query string.
    top_k:
        Maximum number of results to return.
    filters:
        Metadata filter constraints.
    user_id:
        Requesting user's ID for private document access.

    Returns
    -------
    List of RetrievedChunk sorted by keyword relevance (descending).
    """
    terms = query_terms(query)
    if not terms:
        logger.info("Keyword search: no usable terms in query %r", query[:80])
        return []

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return _keyword_search_postgres(db, query, terms, top_k, filters, user_id)
    return _keyword_search_portable(db, query, terms, top_k, filters, user_id)


def _rows_to_chunks(rows) -> List[RetrievedChunk]:
    results = []
    for row in rows:
        pub = row.publication_date
        results.append(
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                title=row.title,
                source_type=row.source_type,
                jurisdiction=row.jurisdiction,
                language=row.language or "en",
                publication_date=str(pub) if pub else None,
                source_url=row.source_url,
                text=row.text,
                page_number=row.page_number,
                keyword_score=float(row.rank_score or 0.0),
            )
        )
    return results


def _keyword_search_postgres(
    db: Session,
    query: str,
    terms: List[str],
    top_k: int,
    filters: MetadataFilter,
    user_id: Optional[int],
) -> List[RetrievedChunk]:
    """tsvector OR-query with cover-density ranking."""
    params: Dict = {"query": query, "top_k": top_k}
    where = _access_and_filters(filters, user_id, params, pg=True)
    where.append("sc.search_vector IS NOT NULL")

    # OR of stemmed terms; every token is \w-safe (from query_terms).
    tsquery = " | ".join(terms)
    params["tsquery"] = tsquery
    where_sql = " AND ".join(where)

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
            ts_rank_cd(sc.search_vector, to_tsquery('english', :tsquery)) AS rank_score
        FROM source_chunks sc
        JOIN source_documents sd ON sd.id = sc.document_id
        WHERE {where_sql}
        ORDER BY rank_score DESC, sc.id ASC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.error("Keyword search failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return []

    results = _rows_to_chunks(rows)
    logger.info(
        "Keyword search (OR of %d terms): %d result(s) for %r",
        len(terms),
        len(results),
        query[:60],
    )
    return results


def _keyword_search_portable(
    db: Session,
    query: str,
    terms: List[str],
    top_k: int,
    filters: MetadataFilter,
    user_id: Optional[int],
) -> List[RetrievedChunk]:
    """Portable fallback: per-term LIKE matching scored by match count.

    Used when the database is not PostgreSQL (tests run on in-memory
    SQLite). Without it, keyword retrieval would return nothing outside
    production and tests could never prove uploaded evidence is findable.
    """
    params: Dict = {"top_k": top_k}
    where = _access_and_filters(filters, user_id, params, pg=False)
    # search_vector is a Postgres tsvector column; on other dialects it is
    # never populated, so matching runs on the chunk text itself.
    where.append("sc.text IS NOT NULL")

    match_parts = []
    score_parts = []
    for i, term in enumerate(terms):
        params[f"term_{i}"] = f"%{term.lower()}%"
        # Case-insensitive substring match on the lowercased text.
        match_parts.append(f"LOWER(sc.text) LIKE :term_{i}")
        score_parts.append(f"CASE WHEN LOWER(sc.text) LIKE :term_{i} THEN 1 ELSE 0 END")

    where.append("(" + " OR ".join(match_parts) + ")")
    where_sql = " AND ".join(where)

    # Portable dialects have no ::text cast; CAST(... AS TEXT) works on
    # SQLite and other non-PostgreSQL engines.
    pub_col = "CAST(sd.publication_date AS TEXT)"

    sql = text(
        f"""
        SELECT
            sc.id          AS chunk_id,
            sc.document_id,
            sd.title,
            sd.source_type,
            sd.jurisdiction,
            sd.language,
            {pub_col}      AS publication_date,
            sd.source_url,
            sc.text,
            sc.page_number,
            ({' + '.join(score_parts)}) AS rank_score
        FROM source_chunks sc
        JOIN source_documents sd ON sd.id = sc.document_id
        WHERE {where_sql}
        ORDER BY rank_score DESC, sc.id ASC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.error("Portable keyword search failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return []

    results = _rows_to_chunks(rows)
    logger.info(
        "Keyword search portable (%d terms): %d result(s) for %r",
        len(terms),
        len(results),
        query[:60],
    )
    return results
