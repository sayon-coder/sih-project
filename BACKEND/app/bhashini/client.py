"""
BHASHINI API client (Phase 11).

Thin wrapper over the configured BHASHINI inference endpoint. When no API key
or base URL is configured - or the call fails - every method raises
``BhashiniUnavailable`` so callers degrade honestly (preserve the original
text, warn, offer English fallback) instead of inventing a translation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.bhashini.exceptions import BhashiniUnavailable
from app.config import get_settings

logger = logging.getLogger(__name__)


class BhashiniClient:
    """Minimal client for text translation via BHASHINI."""

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = (settings.bhashini_api_key or "").strip()
        self.base_url = (settings.bhashini_base_url or "").strip().rstrip("/")
        self.timeout = 15.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def translate_text(self, text: str, source_language: str, target_language: str) -> str:
        """Translate via the configured endpoint; raise BhashiniUnavailable on any failure."""
        if not self.configured:
            raise BhashiniUnavailable("BHASHINI is not configured")
        payload: Dict[str, Any] = {
            "input": [{"source": text}],
            "config": {
                "language": {"sourceLanguage": source_language, "targetLanguage": target_language},
            },
        }
        headers = {"Authorization": self.api_key, "Content-Type": "application/json"}
        try:
            response = httpx.post(
                f"{self.base_url}/v1/translate",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("BHASHINI translate call failed: %s", exc)
            raise BhashiniUnavailable(f"BHASHINI request failed: {exc}") from exc
        try:
            return data["output"][0]["target"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("BHASHINI response shape unexpected: %s", data)
            raise BhashiniUnavailable("BHASHINI returned an unexpected response") from exc
