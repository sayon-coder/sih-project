"""BHASHINI package."""
from app.bhashini.client import BhashiniClient
from app.bhashini.exceptions import BhashiniError, BhashiniUnavailable
from app.bhashini.glossary import GLOSSARY, LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from app.bhashini.language_detector import detect_language, normalize
from app.bhashini.translator import from_canonical_answer, to_canonical_query, translate

__all__ = [
    "BhashiniClient",
    "BhashiniError",
    "BhashiniUnavailable",
    "GLOSSARY",
    "LANGUAGE_NAMES",
    "SUPPORTED_LANGUAGES",
    "detect_language",
    "normalize",
    "translate",
    "to_canonical_query",
    "from_canonical_answer",
]
