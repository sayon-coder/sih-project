"""
Structured schemas for the Phase 6 screening workflows.

Three result families, each deliberately cautious:

* ``IPRouteMapResult``       - candidate IP routes, never "legally applicable";
* ``PatentScreeningResult``  - identified candidate records + feature comparison,
  never a patentability/validity/infringement/priority conclusion;
* ``ScreeningResult``        - biodiversity/ABS and traditional-knowledge
  screening, never an official determination of legal requirements.

A note on ``provenance``: these results are machine-generated (rule-based and/or
corpus-grounded), never verified by a human expert. They therefore carry
``AI_ANALYSIS`` provenance, matching the platform's single "machine-produced,
not expert-verified" bucket. Only the expert-review workflow (Phase 9) may move
a record past that.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ============================================
# Shared
# ============================================

#: Provenance for machine-generated screening output. See module docstring.
SCREENING_PROVENANCE = "AI_ANALYSIS"


class TechnicalFeature(BaseModel):
    """One technical feature extracted from a product version."""

    feature_type: str = Field(..., description="One of the canonical feature types")
    value: str
    source: str = Field(..., description="Where the feature came from, e.g. ingredient:3")


class SignalExplanation(BaseModel):
    """
    A "Why this result?" block for one important signal (spec item 9).

    Defined here (rather than in ``analysis.schemas``) because both the claim
    review and the Phase 6 screening results attach it, and ``analysis.schemas``
    imports this module.

    ``signal`` is the headline, ``why`` the evidence-based reason, ``missing``
    what would strengthen it, and ``limit`` the explicit boundary of the
    statement. Everything here is deterministic text over recorded data -
    never a new conclusion.
    """

    signal: str = ""
    why: str = ""
    missing: List[str] = Field(default_factory=list)
    limit: str = ""


class ScreeningSource(BaseModel):
    """
    A source attached to a screening result, with its metadata made explicit
    (spec item 7): ``source_type`` from the controlled vocabulary, a human
    ``jurisdiction``, ``authority``, ``access_status``, ``verification_status``,
    ``source_url`` and ``retrieved_at``. ``availability`` is kept for backward
    compatibility (available | restricted).
    """

    title: str
    source_type: str
    availability: str = "available"  # available | restricted
    jurisdiction: Optional[str] = None
    url: Optional[str] = None
    note: str = ""
    chunk_id: Optional[int] = None

    # Explicit source metadata (spec item 7).
    authority: Optional[str] = None
    access_status: str = "PUBLIC"  # PUBLIC | RESTRICTED_NOT_ACCESSED | PENDING_REVIEW
    verification_status: str = "PENDING_REVIEW"  # VERIFIED | PENDING_REVIEW | SYNTHETIC_DEMO
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None


#: Controlled vocabulary for ``source_type`` (spec item 7).
SOURCE_TYPE_VOCAB = (
    "classical_text",
    "statute",
    "rule",
    "patent",
    "scientific_article",
    "official_guidance",
)

#: Human-readable names for jurisdiction codes seen across the platform.
JURISDICTION_NAMES = {
    "IN": "India",
    "IND": "India",
    "DE": "Germany",
    "DEU": "Germany",
    "INT": "International",
    "INTL": "International",
    "JP": "Japan",
    "US": "United States",
}


def human_jurisdiction(value: Optional[str]) -> Optional[str]:
    """Render a jurisdiction code (``IN``, ``INT``) as a human name.

    Prevents the ambiguous ``AVAILABLE IN`` / ``AVAILABLE INT`` style labels the
    spec bans (item 7): callers always show ``India`` / ``International``.
    """
    if not value:
        return value
    stripped = value.strip()
    if not stripped:
        return None
    return JURISDICTION_NAMES.get(stripped.upper(), stripped)


# ============================================
# IP route map
# ============================================

class IPRouteSuggestion(BaseModel):
    """
    A candidate IP route.

    ``label`` is always a careful, review-oriented value - never a statement that
    the route is legally applicable. ``signals`` lists what in the product data
    triggered the suggestion so a reader can see the reasoning.

    The five spec fields (item 5) make every route evidence-based and explicit:
    ``status`` (one of the four careful statuses), ``why_flagged`` (the specific
    evidence), ``missing_information`` (what the route still needs),
    ``next_action`` and ``limitation``.
    """

    route: str
    route_label: str
    label: str = Field(..., description="Potentially Relevant | Further Review Recommended | Not Indicated | Insufficient Information")
    status: str = Field(
        default="ADDITIONAL_INFORMATION_NEEDED",
        description="POTENTIALLY_RELEVANT | REVIEW_RECOMMENDED | ADDITIONAL_INFORMATION_NEEDED | NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
    )
    why_flagged: str = ""
    missing_information: List[str] = Field(default_factory=list)
    next_action: str = ""
    limitation: str = ""
    rationale: str
    signals: List[str] = Field(default_factory=list)
    review_questions: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE


#: Machine status -> the careful display label every route must carry.
STATUS_TO_LABEL = {
    "POTENTIALLY_RELEVANT": "Potentially Relevant",
    "REVIEW_RECOMMENDED": "Further Review Recommended",
    "ADDITIONAL_INFORMATION_NEEDED": "Insufficient Information",
    "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED": "Not Indicated",
}


class IPRouteMapResult(BaseModel):
    """Result payload for ``GET .../ip-routes``."""

    kind: str = "ip_route_map"
    product_id: int
    product_version_id: int
    preliminary: bool = True
    routes: List[IPRouteSuggestion] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE


# ============================================
# Patent screening
# ============================================

#: The visible label for records that come from the frozen demo corpus.
DEMO_RECORD_LABEL = "DEMO CORPUS — SYNTHETIC RECORDS — NOT LIVE PATENT DATA"
#: The visible label for an independently verified public record.
VERIFIED_RECORD_LABEL = "VERIFIED PUBLIC RECORD"

#: Verification statuses a record may carry.
VERIFICATION_SYNTHETIC = "SYNTHETIC_DEMO"
VERIFICATION_VERIFIED = "VERIFIED_PUBLIC_RECORD"


def record_verification_fields(
    record_source: Optional[str],
    is_demo: bool,
    verification_status: Optional[str] = None,
) -> Dict[str, str]:
    """
    Derive a record's verification status and its visible label (spec item 6).

    Data-driven by design: a corpus entry (or persisted row) that carries
    ``verification_status = "VERIFIED_PUBLIC_RECORD"`` surfaces as a verified
    public record without any change to the analysis code - and every demo
    record carries the synthetic-corpus banner.
    """
    if (
        verification_status == VERIFICATION_VERIFIED
        or (verification_status is None and record_source not in (None, "DEMO_CORPUS") and not is_demo)
    ):
        return {
            "verification_status": VERIFICATION_VERIFIED,
            "record_label": VERIFIED_RECORD_LABEL,
        }
    return {
        "verification_status": VERIFICATION_SYNTHETIC,
        "record_label": DEMO_RECORD_LABEL,
    }


class PatentFeatureComparison(BaseModel):
    """How one patent feature compares with the screened version."""

    feature_type: str
    patent_value: Optional[str] = None
    user_value: Optional[str] = None
    verdict: str = Field(..., description="match | different | unknown")


class PatentRecordResult(BaseModel):
    """A candidate patent record identified for a version, with its comparison."""

    id: int
    record_id: str
    patent_number: Optional[str] = None
    title: str
    assignee: Optional[str] = None
    jurisdiction: Optional[str] = None
    publication_date: Optional[str] = None
    abstract: Optional[str] = None
    source_url: Optional[str] = None
    source_passage: Optional[str] = None
    record_source: str = "DEMO_CORPUS"  # DEMO_CORPUS | LIVE_SOURCE
    is_demo: bool = True
    corpus_version: Optional[str] = None
    #: Per-record verification (spec item 6): SYNTHETIC_DEMO | VERIFIED_PUBLIC_RECORD.
    verification_status: str = VERIFICATION_SYNTHETIC
    #: The visible per-record banner rendered next to the record.
    record_label: str = DEMO_RECORD_LABEL
    relevance_label: str
    similarity: float = 0.0
    similarity_band: str = "none"  # none | low | medium | high
    uncertainty: str = ""
    provenance: str = SCREENING_PROVENANCE
    features: List[PatentFeatureComparison] = Field(default_factory=list)


class PatentScreeningResult(BaseModel):
    """
    Result payload for a patent search or a feature comparison.

    ``matching_features`` / ``different_features`` / ``unknown_features`` are the
    aggregate comparison across the identified records, using the master prompt's
    vocabulary (matching / different / unknown + a similarity indicator).
    """

    kind: str = "patent_screening"
    product_id: int
    product_version_id: int
    retrieval_mode: str = "DEMO_CORPUS"
    search_is_live: bool = False
    corpus_version: Optional[str] = None
    #: Corpus provenance for the whole response (spec item 6).
    corpus_type: str = "DEMO_CORPUS"
    live_search_performed: bool = False
    records_verified: bool = False
    technical_features: List[TechnicalFeature] = Field(default_factory=list)
    records: List[PatentRecordResult] = Field(default_factory=list)
    record_count: int = 0
    matching_features: List[str] = Field(default_factory=list)
    different_features: List[str] = Field(default_factory=list)
    unknown_features: List[str] = Field(default_factory=list)
    similarity_indicator: str = "none"  # none | low | medium | high
    missing_information: List[str] = Field(default_factory=list)
    explanation: Optional[SignalExplanation] = None
    warnings: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE


class PatentComparisonResult(BaseModel):
    """Result payload for ``POST .../patents/compare`` (no new records created)."""

    kind: str = "patent_feature_comparison"
    product_id: int
    product_version_id: int
    corpus_type: str = "DEMO_CORPUS"
    live_search_performed: bool = False
    records_verified: bool = False
    technical_features: List[TechnicalFeature] = Field(default_factory=list)
    records: List[PatentRecordResult] = Field(default_factory=list)
    record_count: int = 0
    matching_features: List[str] = Field(default_factory=list)
    different_features: List[str] = Field(default_factory=list)
    unknown_features: List[str] = Field(default_factory=list)
    similarity_indicator: str = "none"
    warnings: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE


# ============================================
# Biodiversity / ABS and traditional knowledge
# ============================================

#: The four statuses the master prompt allows for screening.
SCREENING_STATUSES = (
    "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
    "ADDITIONAL_INFORMATION_NEEDED",
    "POTENTIALLY_RELEVANT",
    "REVIEW_RECOMMENDED",
)


class ScreeningResult(BaseModel):
    """
    Result payload for ``POST .../biodiversity/screen`` and
    ``POST .../traditional-knowledge/screen``.

    ``collected`` echoes the fields the analysis was based on (biological
    resource, botanical species, plant part, origin, cultivated/wild status,
    source documentation, TK involvement, documented traditional use,
    research/commercial use, target market) so a reviewer can see exactly what
    was - and was not - available.
    """

    kind: str = "biodiversity_screening"
    screening_type: str = "biodiversity"
    product_id: int
    product_version_id: int
    status: str = "ADDITIONAL_INFORMATION_NEEDED"
    status_label: str = "Additional information needed"
    potential_considerations: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    review_questions: List[str] = Field(default_factory=list)
    sources: List[ScreeningSource] = Field(default_factory=list)
    collected: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[SignalExplanation] = None
    warnings: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE
