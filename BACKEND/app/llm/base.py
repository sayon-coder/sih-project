"""Abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract LLM provider.

    Subclasses implement ``generate`` which takes a system prompt and a user
    prompt and returns the model's text response.

    The design keeps business logic independent of any specific provider.
    Switching providers only requires changing the PROVIDER env variable.
    """

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM and return the raw text response.

        Parameters
        ----------
        system_prompt:
            System/instruction context for the model.
        user_prompt:
            The user's (or pipeline's) query including retrieved context.

        Returns
        -------
        The model's raw text response (may be JSON that callers must parse).
        """

    def supports_structured_output(self) -> bool:
        """Return True if the provider natively supports JSON mode."""
        return False
