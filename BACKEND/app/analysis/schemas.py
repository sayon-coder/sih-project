"""
Structured schemas for the Phase 5 analysis workflows.

Two layers, mirroring the Phase 4 RAG design:

* the ``*LLMOutput`` models are what we *ask the model for* - kept deliberately
  small so a weak model can still produce valid JSON;
* the public ``*Result`` models are what the API returns, enriched with real
  metadata (citations resolved from the database) and clamped by the safety
  rules in ``app.services.provenance``.

Keeping them separate is what lets us never trust the model's own metadata: the
model names chunk ids, and everything else is looked up server-side.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.analysis.ip_schemas import (
    IPRouteMapResult,
    PatentScreeningResult,
    ScreeningResult,
    SignalExplanation,
)


# ============================================
# Citations
# ============================================

class AnalysisCitation(BaseModel):
    """A citation resolved server-side from a real retrieved chunk."""

    chunk_id: int
    document_id: int
    title: str
    source_type: str
    jurisdiction: Optional[str] = None
    publication_date: Optional[str] = None
    page_number: Optional[int] = None
    url: Optional[str] = None
    relevant_text: str = Field(..., description="Passage from the chunk supporting the assessment")


# ============================================
# Claim analysis
# ============================================

class ClaimAnalysisLLMItem(BaseModel):
    """One claim as the model sees and answers it."""

    claim_id: int
    suggested_evidence_status: str = Field(
        ...,
        description="One of: user_provided | needs_evidence | partially_supported",
    )
    risk_level: str = Field(..., description="low | medium | high")
    rationale: str = Field(..., description="Why this status was suggested, in cautious language")
    missing_evidence: List[str] = Field(default_factory=list)
    citation_chunk_ids: List[int] = Field(
        default_factory=list,
        description="chunk_id values copied from the passages provided for this claim",
    )


class ClaimAnalysisLLMOutput(BaseModel):
    """The raw structured answer for a whole claim review."""

    assessments: List[ClaimAnalysisLLMItem] = Field(default_factory=list)
    summary: str = ""
    warnings: List[str] = Field(default_factory=list)


class ClaimAssessment(BaseModel):
    """
    A validated claim assessment.

    ``suggested_evidence_status`` has already passed
    ``clamp_ai_evidence_status``: it can never be ``supported`` or
    ``expert_verified``. ``expert_verified`` marks a claim that was locked by the
    expert workflow, in which case the AI did not propose anything at all.

    The ``claim_provenance`` / ``evidence_status`` / ``independent_verification``
    / ``review_required`` / ``reason`` fields describe the *claim's* standing on
    the record (spec item 1, requirement 5). They are computed server-side from
    stored data only, independently of anything the model said.
    """

    claim_id: int
    claim_text: str
    claim_type: Optional[str] = None
    current_evidence_status: str
    suggested_evidence_status: str
    risk_level: str = "medium"
    review_status: str = "pending"
    rationale: str = ""
    missing_evidence: List[str] = Field(default_factory=list)
    citations: List[AnalysisCitation] = Field(default_factory=list)
    provenance: str = "AI_ANALYSIS"
    expert_verified_locked: bool = False

    # Claim-level standing (deterministic; see docstring).
    claim_provenance: str = "USER_PROVIDED"
    evidence_status: str = "USER_PROVIDED_ONLY"
    independent_verification: str = "NOT_FOUND"
    review_required: bool = True
    reason: str = ""


class ClaimAnalysisResult(BaseModel):
    """Result payload for a claim-to-evidence review."""

    kind: str = "claim_analysis"
    product_id: int
    product_version_id: int
    claim_count: int = 0
    #: REVIEWED when claims were assessed; NO_CLAIMS_RECORDED only when this
    #: very version has no claims (scoped by product_version_id, never global).
    claim_status: str = "REVIEWED"
    assessments: List[ClaimAssessment] = Field(default_factory=list)
    summary: str = ""
    explanation: Optional[SignalExplanation] = None
    warnings: List[str] = Field(default_factory=list)


# ============================================
# Product classification
# ============================================

class ClassificationLLMOutput(BaseModel):
    """Raw preliminary classification answer."""

    preliminary_category: str = ""
    confidence: str = "low"
    rationale: str = ""
    ip_and_abs_posture: str = ""  # per-category IP and ABS posture (SIH A2)
    alternative_categories: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)


class PreliminaryClassification(BaseModel):
    """
    Validated preliminary classification. Always labelled preliminary.

    ``status`` carries the headline the spec asks for: ``UNRESOLVED`` while
    intended use, dosage form, ingredients or claims are incomplete, otherwise
    ``PRELIMINARY``. ``possible_categories`` lists the candidate pathways when
    unresolved; ``category`` remains the model's single best candidate and is
    never presented as a final legal or regulatory decision
    (``review_required`` stays True).
    """

    preliminary: bool = True
    status: str = "UNRESOLVED"  # UNRESOLVED | PRELIMINARY
    category: str
    confidence: str = "LOW"
    rationale: str = ""
    # Per-category IP and ABS posture — what the category means for IP protection
    # and Access-and-Benefit-Sharing duties (SIH requirement A2).
    ip_and_abs_posture: str = ""
    alternative_categories: List[str] = Field(default_factory=list)
    possible_categories: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    review_required: bool = True


#: The six candidate pathways the SIH problem statement specifies while a classification is unresolved.
UNRESOLVED_PATHWAYS = [
    "classical_traditional",        # First-Schedule text; Section 3(p) bar; TKDL defence
    "proprietary_ayurvedic",        # Registered patent/proprietary Ayurvedic medicine
    "new_drug",                     # Non-classical drug; requires safety & effectiveness proof
    "phytopharmaceutical",          # 2015 Drugs & Cosmetics Rules; genuine patent potential
    "ayurveda_aahara",              # FSSAI Ayurveda-Aahar / nutraceutical
    "possible_cosmetic",            # Cosmetics Rules 2020
]


class AnalysisSummary(BaseModel):
    """
    The concise ANALYSIS SUMMARY card shown at the beginning of every
    comprehensive analysis (spec item 8). Derived deterministically from
    recorded data - never by the model.
    """

    product_version: str = "V1"
    overall_status: str = "NOT_ASSESSED"
    evidence_completeness: str = "INCOMPLETE"
    claim_review: str = "NOT_REQUIRED"
    patent_screening: str = "NOT_SCREENED"
    biodiversity_screening: str = "NOT_SCREENED"
    classification: str = "NOT_RUN"
    expert_review: str = "OPTIONAL"


# ============================================
# Comprehensive analysis
# ============================================

class MarketConsideration(BaseModel):
    """A preliminary, non-conclusive consideration for one target market."""

    country: str
    region: Optional[str] = None
    declared_regulatory_status: Optional[str] = None
    consideration: str
    review_questions: List[str] = Field(default_factory=list)


class ComprehensiveAnalysisResult(BaseModel):
    """
    Result payload for ``POST .../analyze``.

    ``deferred_components`` names the analysis stages that belong to later
    phases. They are listed explicitly (rather than omitted) so the response
    cannot be mistaken for a complete IP assessment - the master prompt requires
    that an unimplemented feature never be presented as working.
    """

    kind: str = "comprehensive_analysis"
    product_id: int
    product_version_id: int
    analysis_summary: Optional[AnalysisSummary] = None
    product_classification: Optional[PreliminaryClassification] = None
    claim_review: ClaimAnalysisResult
    market_considerations: List[MarketConsideration] = Field(default_factory=list)
    expert_review_recommendations: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)

    # Phase 6 components, produced inside the comprehensive run (no records are
    # persisted here; the dedicated endpoints record their own runs).
    ip_route_map: Optional[IPRouteMapResult] = None
    patent_signals: Optional[PatentScreeningResult] = None
    biodiversity_screening: Optional[ScreeningResult] = None
    traditional_knowledge_screening: Optional[ScreeningResult] = None

    deferred_components: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
