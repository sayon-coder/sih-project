"""
Fallback LLM provider: primary first, fallback provider on failure.

Keeps normal chat responses working when the primary provider is
unavailable — the configured primary (GROQ by default) is tried first, and
Sarvam AI answers when it is set as the fallback via SARVAM_API_KEY.
"""
from __future__ import annotations

import logging

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class FallbackLLMProvider(LLMProvider):
    """Try ``primary``; on any failure, try ``fallback`` once."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        fallback_name: str = "fallback",
    ):
        self._primary = primary
        self._fallback = fallback
        self._fallback_name = fallback_name

    @property
    def primary(self) -> LLMProvider:
        return self._primary

    @property
    def fallback(self) -> LLMProvider:
        return self._fallback

    def supports_structured_output(self) -> bool:
        # Delegates to the primary - callers build prompts for the primary's
        # capabilities, and the fallback (JSON-mode capable) is only a safety net.
        return self._primary.supports_structured_output()

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            return self._primary.generate(system_prompt, user_prompt)
        except Exception as primary_exc:
            logger.warning(
                "Primary LLM failed (%s); trying %s provider",
                primary_exc,
                self._fallback_name,
            )
            try:
                return self._fallback.generate(system_prompt, user_prompt)
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"All LLM providers failed. Fallback ({self._fallback_name}) "
                    f"also failed: {fallback_exc}"
                ) from primary_exc
