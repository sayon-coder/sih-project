"""Analysis package (Phase 5).

Structured, citation-checked analysis workflows for a product version:

* ``claim_analyzer``  - claim-to-evidence review backed by hybrid retrieval.
* ``classifier``      - preliminary product classification.

Both follow the master prompt's structured-AI-output pipeline: LLM -> JSON ->
Pydantic validation -> citation validation -> scope/safety validation.
"""
from app.analysis.schemas import (
    AnalysisCitation,
    ClaimAssessment,
    ClaimAnalysisResult,
    PreliminaryClassification,
    MarketConsideration,
    ComprehensiveAnalysisResult,
)

__all__ = [
    "AnalysisCitation",
    "ClaimAssessment",
    "ClaimAnalysisResult",
    "PreliminaryClassification",
    "MarketConsideration",
    "ComprehensiveAnalysisResult",
]
