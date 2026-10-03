"""
Cross-encoder reranker.

Uses sentence-transformers cross-encoder (ms-marco-MiniLM-L-6-v2) to score
(query, passage) pairs.  The cross-encoder reads both texts jointly, giving
a much more accurate relevance estimate than bi-encoder cosine similarity.

Falls back to RRF score ordering if the model is unavailable.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from app.rag.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

# Module-level singleton
_RERANKER = None
_RERANKER_AVAILABLE: Optional[bool] = None


def _get_reranker():
    """Lazy-load the cross-encoder model."""
    global _RERANKER, _RERANKER_AVAILABLE
    if _RERANKER_AVAILABLE is None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            _RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
            _RERANKER_AVAILABLE = True
            logger.info("Cross-encoder reranker loaded: cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as exc:
            logger.warning("Reranker unavailable (%s); falling back to RRF ordering.", exc)
            _RERANKER_AVAILABLE = False
    return _RERANKER if _RERANKER_AVAILABLE else None


def rerank(
    query: str,
    chunks: List[RetrievedChunk],
    top_k: int = 6,
) -> List[RetrievedChunk]:
    """
    Rerank retrieved chunks using a cross-encoder.

    Parameters
    ----------
    query:
        The original user query.
    chunks:
        Candidate chunks from hybrid retrieval (already RRF-fused).
    top_k:
        Number of top chunks to return after reranking.

    Returns
    -------
    Top-k chunks sorted by rerank_score descending.
    """
    if not chunks:
        return []

    reranker = _get_reranker()

    if reranker is not None:
        pairs: List[Tuple[str, str]] = [(query, c.text) for c in chunks]
        try:
            scores = reranker.predict(pairs, show_progress_bar=False)
            for chunk, score in zip(chunks, scores):
                chunk.rerank_score = float(score)
                chunk.final_score = float(score)
            chunks.sort(key=lambda c: c.final_score, reverse=True)
        except Exception as exc:
            logger.warning("Reranker prediction failed: %s; using RRF scores", exc)
            _fallback_sort(chunks)
    else:
        _fallback_sort(chunks)

    return chunks[:top_k]


def _fallback_sort(chunks: List[RetrievedChunk]) -> None:
    """Sort chunks by their RRF score when the reranker is unavailable."""
    for c in chunks:
        c.final_score = c.rrf_score
    chunks.sort(key=lambda c: c.final_score, reverse=True)
