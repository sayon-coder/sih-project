"""
Groq LLM provider.

Uses the official `groq` Python SDK.
Default model: llama-3.3-70b-versatile (configurable via LLM_MODEL in .env).

JSON mode is enabled by setting response_format={"type": "json_object"}.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class GroqProvider(LLMProvider):
    """Groq-hosted LLM provider (gpt-oss-120b by default)."""

    def __init__(self, api_key: str, model: str = "gpt-oss-120b"):
        self._api_key = api_key
        self._model = model
        self._client: Optional[object] = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq  # type: ignore
                self._client = Groq(api_key=self._api_key)
            except ImportError as exc:
                raise RuntimeError(
                    "groq package is not installed. Run: pip install groq"
                ) from exc
        return self._client

    def supports_structured_output(self) -> bool:
        return True  # Groq supports JSON mode

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call the Groq API and return the model's text response."""
        client = self._get_client()
        logger.debug("Calling Groq model '%s'", self._model)
        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096,
            )
            content = response.choices[0].message.content
            logger.debug("Groq response received (%d chars)", len(content or ""))
            return content or ""
        except Exception as exc:
            logger.error("Groq API error: %s", exc)
            raise
