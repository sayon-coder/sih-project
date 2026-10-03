"""
BGE-M3 embedding provider via sentence-transformers.

Model: BAAI/bge-m3
Dimension: 1024 (dense output)
Language support: multilingual (English, Hindi, Bengali, etc.)

The model is loaded lazily on first use and cached as a module-level singleton.
Loading BAAI/bge-m3 for the first time requires ~1.8 GB download.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_MODEL_CACHE: Optional[object] = None  # SentenceTransformer instance


def _load_model(model_name: str):
    """Load and cache the sentence-transformers model."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        logger.info("Loading embedding model '%s' (first load may take time)…", model_name)
        _MODEL_CACHE = SentenceTransformer(model_name)
        logger.info("Embedding model loaded. Dimension: %d", _MODEL_CACHE.get_sentence_embedding_dimension())
    return _MODEL_CACHE


class BGEM3Provider(EmbeddingProvider):
    """BGE-M3 dense embedding provider.

    Uses sentence-transformers to load BAAI/bge-m3 and produce 1024-dimensional
    L2-normalized dense embeddings suitable for cosine similarity search.
    """

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self._model_name = model_name
        self._dim: Optional[int] = None

    @property
    def dimension(self) -> int:
        if self._dim is None:
            model = _load_model(self._model_name)
            self._dim = model.get_sentence_embedding_dimension()
        return self._dim  # type: ignore[return-value]

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed texts using BGE-M3.

        BGE-M3 recommends adding a query prefix for retrieval tasks.
        We detect whether the batch is a query or a passage and apply
        the appropriate prefix.  For simplicity, this provider does NOT
        auto-add prefixes; callers that need them (vector_search.py) should
        prepend "Represent this sentence for searching relevant passages: "
        to query texts themselves.
        """
        if not texts:
            return []

        model = _load_model(self._model_name)
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,   # L2-normalize → cosine sim = dot product
            show_progress_bar=False,
            batch_size=32,
        )
        # embeddings is a numpy array of shape (len(texts), dim)
        return embeddings.tolist()
