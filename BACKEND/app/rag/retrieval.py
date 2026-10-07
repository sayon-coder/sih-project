"""
Hybrid retrieval: vector + BM25/FTS merged with Reciprocal Rank Fusion (RRF).

Pipeline:
  1. Embed query with BGE-M3
  2. Vector search  (pgvector cosine)
  3. Keyword search (PostgreSQL FTS / BM25-style ts_rank_cd)
  4. RRF merge
  5. Cross-encoder rerank
  6. Return top-k chunks with full metadata
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.embeddings.provider import get_embedding_provider
from app.rag.keyword_search import keyword_search
from app.rag.query_expansion import expand_query_terms
from app.rag.reranker import rerank
from app.rag.schemas import MetadataFilter, RetrievedChunk
from app.rag.vector_search import QUERY_PREFIX, vector_search
from app.utils.cache import cache

logger = logging.getLogger(__name__)

# RRF constant — higher values dampen the effect of rank position
RRF_K = 60


def _rrf_score(rank: int) -> float:
    """Reciprocal Rank Fusion score for a given rank (1-based)."""
    return 1.0 / (RRF_K + rank)


def hybrid_retrieve(
    db: Session,
    query: str,
    filters: MetadataFilter = MetadataFilter(),
    user_id: Optional[int] = None,
    top_k_retrieval: Optional[int] = None,
    top_k_final: Optional[int] = None,
) -> List[RetrievedChunk]:
    """
    Hybrid retrieval pipeline.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    query:
        Raw user query string.
    filters:
        Metadata filter constraints.
    user_id:
        Requesting user ID for private document access.
    top_k_retrieval:
        Number of candidates from each search arm (default from settings).
    top_k_final:
        Number of chunks to return after reranking (default from settings).

    Returns
    -------
    Reranked list of RetrievedChunk, best first.
    """
    settings = get_settings()
    k_retrieval = top_k_retrieval or settings.rag_top_k_retrieval
    k_final = top_k_final or settings.rag_rerank_top_k

    # -------------------------------------------------------
    # 0. Term expansion — widen recall with domain synonyms
    # (ashwagandha <-> Withania somnifera, 4°C <-> temperature, ...)
    # -------------------------------------------------------
    expanded_query, added_terms = expand_query_terms(query)
    if added_terms:
        logger.info("Query expansion: %s", ", ".join(added_terms))

    # -------------------------------------------------------
    # 1. Embed the query (keyword-only fallback when embeddings
    # are unavailable - retrieval degrades openly, never 500s)
    # -------------------------------------------------------
    query_embedding = None
    embedding_dim = None
    try:
        embedding_provider = get_embedding_provider()
        prefixed_query = QUERY_PREFIX + expanded_query
        # Embedding the same text twice is pure waste (deterministic model
        # output, CPU-bound). Cache by normalised text; filters still apply
        # downstream in vector_search, so sharing the vector is safe.
        emb_key = f"emb:{prefixed_query.strip().lower()}" if settings.cache_enabled else None
        if emb_key is not None:
            cached_vec = cache.get(emb_key)
            if cached_vec is not None:
                query_embedding, embedding_dim = cached_vec
        if query_embedding is None:
            query_embedding = embedding_provider.embed_one(prefixed_query)
            embedding_dim = embedding_provider.dimension
            if emb_key is not None:
                cache.set(
                    emb_key,
                    (query_embedding, embedding_dim),
                    ttl=settings.cache_embedding_ttl_seconds,
                )
    except Exception as exc:
        logger.warning("Embedding unavailable, using keyword search only: %s", exc)

    # -------------------------------------------------------
    # 2. Parallel search arms
    # -------------------------------------------------------
    vector_results = (
        vector_search(
            db=db,
            query_embedding=query_embedding,
            top_k=k_retrieval,
            filters=filters,
            user_id=user_id,
            embedding_dim=embedding_dim,
        )
        if query_embedding is not None
        else []
    )

    keyword_results = keyword_search(
        db=db,
        query=expanded_query,
        top_k=k_retrieval,
        filters=filters,
        user_id=user_id,
    )

    logger.info(
        "Retrieval arms: vector=%d, keyword=%d (filters=%s, user_id=%s)",
        len(vector_results),
        len(keyword_results),
        filters.model_dump(exclude_none=True),
        user_id,
    )

    # -------------------------------------------------------
    # 3. RRF merge
    # -------------------------------------------------------
    merged = _rrf_merge(vector_results, keyword_results)

    if not merged:
        logger.info("No results from hybrid retrieval for query: '%s'", query[:80])
        return []

    # -------------------------------------------------------
    # 4. Cross-encoder rerank
    # -------------------------------------------------------
    reranked = rerank(query=query, chunks=merged, top_k=k_final)

    logger.info(
        "Hybrid retrieval: %d final chunks (from %d candidates)",
        len(reranked),
        len(merged),
    )
    return reranked


def _rrf_merge(
    vector_results: List[RetrievedChunk],
    keyword_results: List[RetrievedChunk],
) -> List[RetrievedChunk]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    Deduplicates by chunk_id, preserving per-chunk vector/keyword scores.
    """
    chunk_map: Dict[int, RetrievedChunk] = {}

    # Score from vector arm
    for rank, chunk in enumerate(vector_results, start=1):
        chunk.vector_score = chunk.vector_score  # already set
        chunk.rrf_score = _rrf_score(rank)
        chunk_map[chunk.chunk_id] = chunk

    # Score from keyword arm (accumulate RRF)
    for rank, chunk in enumerate(keyword_results, start=1):
        kw_rrf = _rrf_score(rank)
        if chunk.chunk_id in chunk_map:
            existing = chunk_map[chunk.chunk_id]
            existing.keyword_score = chunk.keyword_score
            existing.rrf_score += kw_rrf
        else:
            chunk.rrf_score = kw_rrf
            chunk_map[chunk.chunk_id] = chunk

    # Sort by combined RRF score
    merged = list(chunk_map.values())
    merged.sort(key=lambda c: c.rrf_score, reverse=True)
    return merged
