"""Abstract base class for embedding providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Abstract embedding provider.

    Subclasses must implement ``embed`` which converts a list of text strings
    into a list of float vectors of a fixed dimension.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension produced by this provider."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts.

        Parameters
        ----------
        texts:
            Non-empty list of strings to embed.

        Returns
        -------
        List of float vectors, one per input text.
        """

    def embed_one(self, text: str) -> List[float]:
        """Convenience wrapper for embedding a single text."""
        return self.embed([text])[0]
