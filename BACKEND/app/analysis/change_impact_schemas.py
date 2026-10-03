"""
Structured schemas for the Phase 7 change-impact simulator.

The report is a list of **named differences** plus the questions they raise. Two
properties matter:

* every difference is labelled with the category the master prompt asks about
  (ingredients, botanical species, plant parts, quantities, origin,
  cultivation/wild status, formulation, extraction, claims, evidence, target
  markets, public disclosure, patent signals, biodiversity/TK, classification);
* each difference carries a cautious ``note`` and a significance level, never a
  conclusion. Nothing here is legal, patent or regulatory advice.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

#: Provenance for machine-generated output (see app/analysis/ip_schemas.py).
SCREENING_PROVENANCE = "AI_ANALYSIS"

#: How much attention a difference deserves.
SIGNIFICANCE_INFORMATIONAL = "informational"
SIGNIFICANCE_REVIEW = "review_recommended"
SIGNIFICANCE_SIGNIFICANT = "significant"


class FieldChange(BaseModel):
    """One meaningful difference between the two versions."""

    category: str = Field(
        ...,
        description=(
            "ingredients | botanical | plant_part | quantities | origin | cultivation | "
            "formulation | extraction | claims | evidence | markets | public_disclosure | "
            "patent_signals | biodiversity_tk | classification"
        ),
    )
    change_type: str = Field(..., description="added | removed | modified")
    field: str
    subject: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    significance: str = SIGNIFICANCE_INFORMATIONAL
    note: str = ""


class ImpactReviewQuestion(BaseModel):
    """A question the difference raises for a human reviewer."""

    category: str
    question: str
    rationale: str = ""


class NotCompared(BaseModel):
    """A category the report could not compare, and why (never silently omitted)."""

    category: str
    reason: str


class ChangeImpactResult(BaseModel):
    """Result payload for ``POST /api/products/{id}/change-impact``."""

    kind: str = "change_impact"
    product_id: int
    old_version_id: int
    new_version_id: int
    old_version_number: int
    new_version_number: int
    old_content_hash: Optional[str] = None
    new_content_hash: Optional[str] = None

    identical: bool = False
    summary: str = ""
    changes: List[FieldChange] = Field(default_factory=list)
    change_count: int = 0
    categories_changed: List[str] = Field(default_factory=list)

    #: Human review areas the changed categories pull in (spec item 10).
    affected_areas: List[str] = Field(default_factory=list)
    #: Screens/analyses worth re-running for the new version (spec item 10).
    reassessment_recommended: List[str] = Field(default_factory=list)
    #: What is still needed to assess these changes (spec item 10).
    missing_information: List[str] = Field(default_factory=list)

    significant_changes: List[str] = Field(default_factory=list)
    expert_review_recommended: bool = False
    expert_review_reasons: List[str] = Field(default_factory=list)

    review_questions: List[ImpactReviewQuestion] = Field(default_factory=list)
    not_compared: List[NotCompared] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    provenance: str = SCREENING_PROVENANCE
