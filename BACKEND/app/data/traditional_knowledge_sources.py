"""
Traditional-knowledge source registry (Phase 6).

The master prompt is explicit: the platform must never pretend to have
unrestricted access to restricted TKDL data, must never reproduce restricted
TKDL material, and must clearly distinguish **public**, **permitted** and
**restricted/unavailable** sources.

This module is that distinction made concrete. It is a *registry of source
categories the platform is allowed to draw on* - not a set of citations. A
citation is only ever emitted when a real passage is retrieved from the corpus
(Phase 4 retrieval), and the retrieval layer never ingests restricted material.

Each entry now carries explicit source metadata (spec item 7):

* ``source_type``        - controlled vocabulary (classical_text | statute | rule
                           | patent | scientific_article | official_guidance);
* ``jurisdiction``       - human-readable (India | International | Germany);
* ``authority``          - who publishes/maintains the source;
* ``access_status``      - PUBLIC | RESTRICTED_NOT_ACCESSED;
* ``verification_status``- VERIFIED (curated official/public source) |
                           PENDING_REVIEW (retrieved corpus passages, set at
                           retrieval time) | SYNTHETIC_DEMO (demo patent data).

``kind`` / ``availability`` are kept for backward compatibility:
  * ``public``      - publicly available, may be consulted and cited.
  * ``permitted``   - consultable under its own terms, may be cited.
  * ``restricted``  - NOT accessible to the platform and never reproduced.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: Registry version, exposed with screening results.
SOURCES_VERSION = "tk-sources-2026.09"

#: The explicit status used for anything the platform cannot access.
RESTRICTED_AVAILABILITY = "restricted"

#: Access statuses (spec item 7).
ACCESS_PUBLIC = "PUBLIC"
ACCESS_RESTRICTED = "RESTRICTED_NOT_ACCESSED"

#: Verification statuses (spec item 7).
VERIFICATION_VERIFIED = "VERIFIED"
VERIFICATION_PENDING = "PENDING_REVIEW"

#: The exact label the spec requires for the restricted TKDL entry.
TKDL_RESTRICTED_LABEL = "TKDL: RESTRICTED — NOT ACCESSED OR REPRODUCED"


TRADITIONAL_KNOWLEDGE_SOURCES: List[Dict[str, Any]] = [
    {
        "source_id": "public-ayurvedic-classics",
        "title": "Public-domain translations of classical Ayurvedic texts",
        "kind": "public",
        "availability": "available",
        "source_type": "classical_text",
        "jurisdiction": "India",
        "authority": "Public-domain Ayurvedic compendia (Charaka Samhita, Sushruta Samhita)",
        "access_status": ACCESS_PUBLIC,
        "verification_status": VERIFICATION_VERIFIED,
        "description": (
            "Publicly available English translations and commentaries of classical "
            "Ayurvedic compendia (for example Charaka Samhita and Sushruta Samhita "
            "translations). Used only where the platform's corpus actually contains a "
            "passage; no text is reproduced beyond the retrieved passage."
        ),
        "url": "https://ayush.gov.in/research-portal",
        "note": "Citation only when a passage is genuinely retrieved from the corpus.",
    },
    {
        "source_id": "public-pharmacopoeia-monographs",
        "title": "Public pharmacopoeial and WHO monographs",
        "kind": "public",
        "availability": "available",
        "source_type": "official_guidance",
        "jurisdiction": "International",
        "authority": "Pharmacopoeial commissions and the World Health Organization (WHO)",
        "access_status": ACCESS_PUBLIC,
        "verification_status": VERIFICATION_VERIFIED,
        "description": (
            "Publicly published monographs describing botanical identity, plant part "
            "and documented traditional use."
        ),
        "url": "https://www.who.int/medicines/areas/traditional/en/",
        "note": "Used for botanical and traditional-use signals; not legal advice.",
    },
    {
        "source_id": "public-ethnopharmacology",
        "title": "Peer-reviewed ethnopharmacology literature",
        "kind": "public",
        "availability": "available",
        "source_type": "scientific_article",
        "jurisdiction": "International",
        "authority": "Peer-reviewed scientific publishers",
        "access_status": ACCESS_PUBLIC,
        "verification_status": VERIFICATION_VERIFIED,
        "description": (
            "Openly published scientific literature documenting traditional use of "
            "botanical resources."
        ),
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
        "note": "Only openly accessible literature already present in the corpus.",
    },
    {
        "source_id": "permitted-national-abs-guidance",
        "title": "National biodiversity / ABS guidance (public guidance documents)",
        "kind": "permitted",
        "availability": "available",
        "source_type": "official_guidance",
        "jurisdiction": "India",
        "authority": "National biodiversity authority (India)",
        "access_status": ACCESS_PUBLIC,
        "verification_status": VERIFICATION_VERIFIED,
        "description": (
            "Publicly issued guidance describing access-and-benefit-sharing processes. "
            "Consulted for orientation only; the platform never determines whether "
            "approval is required."
        ),
        "url": "https://nbaindia.org",
        "note": "Guidance, not an official determination.",
    },
    {
        "source_id": "restricted-tkdl",
        "title": "Traditional Knowledge Digital Library (TKDL)",
        "kind": "restricted",
        "availability": RESTRICTED_AVAILABILITY,
        "source_type": "classical_text",
        "jurisdiction": "India",
        "authority": "CSIR-National Physical Laboratory / IP India (TKDL)",
        "access_status": ACCESS_RESTRICTED,
        "verification_status": VERIFICATION_VERIFIED,
        "description": (
            "TKDL is a restricted-access database. The platform has no access to it, "
            "cannot search it, and will never reproduce its contents. TKDL entries are "
            "surfaced only as a *citation to the database itself*, so that a reviewer "
            "knows to consult it directly through the authorised channel."
        ),
        "url": "https://tkdl.res.in",
        "note": TKDL_RESTRICTED_LABEL,
    },
]


def get_traditional_knowledge_sources() -> List[Dict[str, Any]]:
    """Return a defensive copy of the registry."""
    return [dict(entry) for entry in TRADITIONAL_KNOWLEDGE_SOURCES]


def get_restricted_source() -> Dict[str, Any]:
    """Return the single restricted/unavailable source entry (TKDL)."""
    return dict(TRADITIONAL_KNOWLEDGE_SOURCES[-1])
