"""
Script-based language detection (Phase 11).

Deterministic and offline: Devanagari -> Hindi, Bengali script -> Bengali,
otherwise English. Confidence is high only when the matching script dominates
the text; mixed or script-free text reports low confidence so callers can ask
rather than assume.
"""
from __future__ import annotations


def _script_ratio(text: str, start: int, end: int) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if start <= ord(c) <= end) / len(letters)


def detect_language(text: str) -> dict:
    """Return {"language": "en"|"hi"|"bn", "confidence": "high"|"low"}."""
    if not text or not text.strip():
        return {"language": "en", "confidence": "low"}
    devanagari = _script_ratio(text, 0x0900, 0x097F)
    bengali = _script_ratio(text, 0x0980, 0x09FF)
    if devanagari >= 0.3 and devanagari >= bengali:
        return {
            "language": "hi",
            "confidence": "high" if devanagari >= 0.6 else "low",
        }
    if bengali >= 0.3 and bengali > devanagari:
        return {
            "language": "bn",
            "confidence": "high" if bengali >= 0.6 else "low",
        }
    return {"language": "en", "confidence": "high" if devanagari + bengali < 0.05 else "low"}


def normalize(text: str, language: str) -> str:
    """Light normalization: strip and collapse whitespace (never alters identifiers)."""
    return " ".join((text or "").split())
