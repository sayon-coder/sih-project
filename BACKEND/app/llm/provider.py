"""
LLM provider factory.

Reads LLM_PROVIDER from settings and returns the appropriate singleton.
Supported values: groq (default) | openai | gemini

When SARVAM_API_KEY is set, the primary provider is wrapped in a
FallbackLLMProvider so normal responses fall back to Sarvam AI if the
primary call fails.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from app.config import get_settings
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider (singleton).

    Primary comes from LLM_PROVIDER (groq by default); when SARVAM_API_KEY
    is present the result is a FallbackLLMProvider (primary -> Sarvam).
    """
    settings = get_settings()
    primary = _build_primary_provider(settings)

    sarvam_key = (settings.sarvam_api_key or "").strip()
    if sarvam_key:
        from app.llm.fallback import FallbackLLMProvider
        from app.llm.sarvam_provider import SarvamProvider

        logger.info(
            "Wrapping %s provider with Sarvam fallback (model '%s')",
            settings.llm_provider,
            settings.sarvam_model,
        )
        return FallbackLLMProvider(
            primary,
            SarvamProvider(api_key=sarvam_key, model=settings.sarvam_model),
            fallback_name="sarvam",
        )
    return primary


def _build_primary_provider(settings) -> LLMProvider:
    """Build the provider named by LLM_PROVIDER."""
    provider_name = settings.llm_provider.lower()

    if provider_name == "groq":
        if not settings.groq_api_key:
            raise ValueError("LLM_PROVIDER=groq but GROQ_API_KEY is not set in .env")
        from app.llm.groq_provider import GroqProvider
        logger.info("Initialising GroqProvider with model '%s'", settings.llm_model)
        return GroqProvider(api_key=settings.groq_api_key, model=settings.llm_model)

    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set in .env")
        # OpenAI provider can be added here when needed
        raise NotImplementedError("OpenAI provider not yet implemented. Use LLM_PROVIDER=groq.")

    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set in .env")
        raise NotImplementedError("Gemini provider not yet implemented. Use LLM_PROVIDER=groq.")

    raise ValueError(
        f"Unknown LLM provider: '{provider_name}'. "
        "Set LLM_PROVIDER=groq in .env."
    )


def get_llm_provider_for(choice: Optional[str] = None) -> LLMProvider:
    """Resolve the chat LLM from an explicit user choice.

    - ``None`` / ``"groq"`` — the default chain (GROQ primary, Sarvam fallback
      when SARVAM_API_KEY is set): what "Groq (default)" means in the UI.
    - ``"sarvam"`` — strictly the Sarvam provider, no silent failover. An
      explicit selection must answer with the selected key, otherwise the
      toggle would not reflect reality.

    Raises ValueError for unknown choices or a missing key.
    """
    if not choice or choice == "groq":
        return get_llm_provider()

    if choice == "sarvam":
        settings = get_settings()
        sarvam_key = (settings.sarvam_api_key or "").strip()
        if not sarvam_key:
            raise ValueError(
                "Sarvam was selected but SARVAM_API_KEY is not set in .env"
            )
        from app.llm.sarvam_provider import SarvamProvider

        return SarvamProvider(api_key=sarvam_key, model=settings.sarvam_model)

    raise ValueError(
        f"Unknown LLM choice: '{choice}'. Supported: groq, sarvam."
    )
