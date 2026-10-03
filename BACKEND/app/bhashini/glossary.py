"""
Controlled glossary (Phase 11).

BHASHINI is the language-access layer, not the reasoning layer. These terms
have fixed translations that must survive translation without shifting meaning:
"Potentially relevant" must not become "legally required".

Identifiers (patent/application/publication numbers, section numbers, URLs,
DOIs, document IDs, dates) are never translated or altered - the translator
extracts and restores them verbatim.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

SUPPORTED_LANGUAGES = ("en", "hi", "bn")

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (हिन्दी)",
    "bn": "Bengali (বাংলা)",
}

# Controlled glossary: canonical English term -> per-language fixed rendering.
GLOSSARY: Dict[str, Dict[str, str]] = {
    "patent": {"en": "patent", "hi": "पेटेंट", "bn": "পেটেন্ট"},
    "prior art": {"en": "prior art", "hi": "पूर्व कला", "bn": "পূর্ব কলা"},
    "trademark": {"en": "trademark", "hi": "ट्रेडमार्क", "bn": "ট্রেডমার্ক"},
    "copyright": {"en": "copyright", "hi": "कॉपीराइट", "bn": "কপিরাইট"},
    "design": {"en": "design", "hi": "डिज़ाइन", "bn": "নকশা"},
    "geographical indication": {"en": "geographical indication", "hi": "भौगोलिक संकेत", "bn": "ভৌগোলিক নির্দেশক"},
    "trade secret": {"en": "trade secret", "hi": "व्यापार रहस्य", "bn": "বাণিজ্য গোপনীয়তা"},
    "plant variety": {"en": "plant variety", "hi": "पादप किस्म", "bn": "উদ্ভিদ জাত"},
    "traditional knowledge": {"en": "traditional knowledge", "hi": "पारंपरिक ज्ञान", "bn": "ঐতিহ্যগত জ্ঞান"},
    "biological resource": {"en": "biological resource", "hi": "जैविक संसाधन", "bn": "জৈব সম্পদ"},
    "access and benefit-sharing": {"en": "access and benefit-sharing", "hi": "पहुंच और लाभ-साझाकरण", "bn": "অ্যাক্সেস ও সুবিধা-ভাগাভাগি"},
    "disclosure": {"en": "disclosure", "hi": "प्रकटीकरण", "bn": "প্রকাশ"},
    "invention": {"en": "invention", "hi": "आविष्कार", "bn": "উদ্ভাবন"},
    "claim": {"en": "claim", "hi": "दावा", "bn": "দাবি"},
    "evidence": {"en": "evidence", "hi": "साक्ष्य", "bn": "প্রমাণ"},
    "jurisdiction": {"en": "jurisdiction", "hi": "अधिकार क्षेत्र", "bn": "এখতিয়ার"},
    "classification": {"en": "classification", "hi": "वर्गीकरण", "bn": "শ্রেণিবিন্যাস"},
    "expert review": {"en": "expert review", "hi": "विशेषज्ञ समीक्षा", "bn": "বিশেষজ্ঞ পর্যালোচনা"},
}

# Cautious phrases whose strength must be preserved in translation.
CAUTIOUS_PHRASES = (
    "potentially relevant",
    "possible technical overlap",
    "further review recommended",
    "review recommended",
    "preliminary",
    "insufficient evidence",
)

_IDENTIFIER_PATTERNS = (
    re.compile(r"https?://\S+"),  # URLs
    re.compile(r"\b10\.\d{4,}/\S+"),  # DOIs
    re.compile(r"\b(?:IN|WO|EP|US|DE|GB)\s?\d[\d/\-]*", re.IGNORECASE),  # patent numbers
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),  # other dates
)


def mask_identifiers(text: str) -> Tuple[str, List[str]]:
    """Replace identifiers with positional placeholders, returning (masked, originals)."""
    originals: List[str] = []
    masked = text
    for pattern in _IDENTIFIER_PATTERNS:
        def _swap(match: "re.Match") -> str:
            originals.append(match.group(0))
            return f"⟦ID{len(originals) - 1}⟧"
        masked = pattern.sub(_swap, masked)
    return masked, originals


def unmask_identifiers(text: str, originals: List[str]) -> str:
    """Restore masked identifiers verbatim."""
    for i, original in enumerate(originals):
        text = text.replace(f"⟦ID{i}⟧", original)
    return text
