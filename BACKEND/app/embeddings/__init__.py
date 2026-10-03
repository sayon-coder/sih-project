"""Embedding provider package."""
from app.embeddings.base import EmbeddingProvider
from app.embeddings.provider import get_embedding_provider

__all__ = ["EmbeddingProvider", "get_embedding_provider"]
