"""
Sarvam AI LLM provider — fallback for normal (text) chat responses.

Uses the official `sarvamai` SDK (Chat Completions V1).
Default model: sarvam-105b-conversations (configurable via SARVAM_MODEL).

JSON mode uses response_format={"type": "json_object"}; thinking is disabled
(reasoning_effort=None) so pipeline replies stay fast and parseable.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class SarvamProvider(LLMProvider):
    """Sarvam-hosted LLM provider (sarvam-105b-conversations by default)."""

    def __init__(self, api_key: str, model: str = "sarvam-105b-conversations"):
        self._api_key = api_key
        self._model = model
        self._client: Optional[object] = None

    def _get_client(self):
        if self._client is None:
            try:
                from sarvamai import SarvamAI  # type: ignore
                self._client = SarvamAI(api_subscription_key=self._api_key)
            except ImportError as exc:
                raise RuntimeError(
                    "sarvamai package is not installed. Run: pip install sarvamai"
                ) from exc
        return self._client

    def supports_structured_output(self) -> bool:
        return True  # Sarvam chat completions support JSON mode

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call the Sarvam Chat Completions API and return the text response."""
        client = self._get_client()
        logger.debug("Calling Sarvam model '%s'", self._model)
        try:
            response = client.chat.completions(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                reasoning_effort=None,  # thinking off: fast, deterministic replies
                temperature=0.1,
                max_tokens=4096,
            )
            content = response.choices[0].message.content
            logger.debug("Sarvam response received (%d chars)", len(content or ""))
            return content or ""
        except Exception as exc:
            logger.error("Sarvam API error: %s", exc)
            raise
