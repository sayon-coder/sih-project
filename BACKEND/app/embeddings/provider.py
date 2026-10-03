"""
Embedding provider factory.

Reads EMBEDDING_PROVIDER from settings and returns the appropriate singleton.
Currently supported: sentence-transformers (BAAI/bge-m3 default).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (singleton)."""
    settings = get_settings()
    provider_name = settings.embedding_provider.lower()

    if provider_name == "sentence-transformers":
        from app.embeddings.bge_m3_provider import BGEM3Provider
        logger.info("Initialising BGEM3Provider with model '%s'", settings.embedding_model)
        return BGEM3Provider(model_name=settings.embedding_model)

    raise ValueError(
        f"Unknown embedding provider: '{provider_name}'. "
        "Set EMBEDDING_PROVIDER=sentence-transformers in .env."
    )
