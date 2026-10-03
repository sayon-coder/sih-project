"""
Translator (Phase 11).

``translate()`` is the only translation entry point used by the assistant and
the API. Contract:

* unknown languages -> ValueError (callers turn it into 422);
* same language -> returned as-is, translated=False;
* BHASHINI available -> identifiers masked before the call and restored after,
  translated=True;
* BHASHINI unavailable -> the ORIGINAL text is returned with translated=False
  and a warning. Nothing is ever silently "translated".
"""
from __future__ import annotations

from typing import Tuple

from app.bhashini.client import BhashiniClient
from app.bhashini.exceptions import BhashiniUnavailable
from app.bhashini.glossary import SUPPORTED_LANGUAGES, mask_identifiers, unmask_identifiers
from app.bhashini.language_detector import normalize

SERVICE_UNAVAILABLE_WARNING = (
    "BHASHINI translation is unavailable, so the original text is preserved. "
    "English is used as a fallback where shown."
)


def translate(
    text: str, source_language: str, target_language: str
) -> Tuple[str, bool, str | None]:
    """Translate text; return (output, translated, warning_or_None)."""
    if source_language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported source language: {source_language}")
    if target_language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported target language: {target_language}")
    cleaned = normalize(text, source_language)
    if source_language == target_language:
        return cleaned, False, None
    masked, originals = mask_identifiers(cleaned)
    try:
        translated = BhashiniClient().translate_text(masked, source_language, target_language)
    except BhashiniUnavailable:
        return cleaned, False, SERVICE_UNAVAILABLE_WARNING
    return unmask_identifiers(translated, originals), True, None


def to_canonical_query(message: str, input_language: str) -> Tuple[str, list]:
    """Map a user message to the English canonical query used by RAG.

    Returns (canonical_text, warnings). When translation is unavailable the
    original message is used and the caller is told, so retrieval degrades
    openly instead of pretending.
    """
    if (input_language or "en") == "en":
        return message, []
    try:
        output, translated, warning = translate(message, input_language, "en")
    except ValueError as exc:
        return message, [str(exc)]
    if translated:
        return output, []
    return message, [warning or SERVICE_UNAVAILABLE_WARNING]


def from_canonical_answer(answer: str, output_language: str) -> Tuple[str, list]:
    """Map the canonical English answer back to the user's language."""
    if (output_language or "en") == "en":
        return answer, []
    try:
        output, translated, warning = translate(answer, "en", output_language)
    except ValueError as exc:
        return answer, [str(exc)]
    if translated:
        return output, []
    return answer, [warning or SERVICE_UNAVAILABLE_WARNING]
