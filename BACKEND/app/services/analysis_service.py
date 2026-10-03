"""
Analysis service (Phase 5).

Owns the two analysis workflows exposed by the API and their persistence:

* ``analyze_claims``  - a claim-to-evidence review (``POST .../claims/analyze``)
* ``analyze_product`` - a comprehensive, orchestrated review (``POST .../analyze``)

Design rules that apply to both:

* **Analysis is advisory.** Running an analysis never mutates the underlying
  claims, evidence or ingredients. It writes one immutable ``analyses`` row that
  references the exact product version it reviewed, so a later version cannot
  silently change a historical result.
* **Version-pinned.** Results carry the ``product_version_id`` they were
  computed from, and the version's ``content_hash`` is recorded in the audit
  trail, so a reader can tell whether the content has changed since.
* **An AI outage is a controlled failure, not a silent success.** If the model
  is unreachable or returns unusable output, a ``FAILED`` row is persisted for
  auditability and the caller receives an explicit error. The service never
  fabricates an assessment.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis.claim_analyzer import analyze_claims_content
from app.analysis.classifier import classify_product
from app.analysis.ip_routes import build_ip_route_map
from app.analysis.patent_screening import screen_patents
from app.analysis.prompts import (
    ANALYSIS_DISCLAIMER,
    BIODIVERSITY_DISCLAIMER,
    CLAIM_ANALYSIS_DISCLAIMER,
    CLASSIFICATION_DISCLAIMER,
    IP_ROUTE_DISCLAIMER,
    PATENT_DISCLAIMER,
    TRADITIONAL_KNOWLEDGE_DISCLAIMER,
)
from app.analysis.screening import screen_biodiversity, screen_traditional_knowledge
from app.analysis.schemas import (
    AnalysisSummary,
    ClaimAnalysisResult,
    ComprehensiveAnalysisResult,
    MarketConsideration,
)
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisType,
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    Product,
    ProductVersion,
    TargetMarket,
)
from app.services.audit_service import AuditService
from app.utils.authorization import get_accessible_version

logger = logging.getLogger(__name__)

#: Analysis stages that belong to later phases. They are reported explicitly so
#: a comprehensive analysis cannot be mistaken for a complete IP assessment.
#:
#: All single-version stages are now implemented (Phase 6 screens, Phase 8
#: disclosure review and reports), so nothing is deferred.
DEFERRED_COMPONENTS: list = []


class AnalysisService:
    """Run and retrieve analysis results for a product version."""

    # ============================================
    # Shared helpers
    # ============================================

    @staticmethod
    def _version(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> ProductVersion:
        """Resolve a version the caller may analyse (404 on anything else)."""
        return get_accessible_version(db, product_id, version_id, user_id)

    @staticmethod
    def _persist(
        db: Session,
        *,
        version: ProductVersion,
        analysis_type: AnalysisType,
        status: AnalysisStatus,
        results: Optional[Dict[str, Any]],
        summary: Optional[str],
        recommendations: Optional[List[str]],
        warnings: Optional[List[str]],
        flags: Optional[List[str]],
        user_id: int,
    ) -> Analysis:
        """Write one analysis row. Results and lists are stored as JSON text."""
        analysis = Analysis(
            product_version_id=version.id,
            analysis_type=analysis_type,
            status=status,
            results=(
                # The run's content hash travels with the result so a reader can
                # tell whether the version changed after this run (spec item 1).
                json.dumps({**results, "content_hash": version.content_hash})
                if results is not None
                else None
            ),
            summary=summary,
            recommendations=json.dumps(recommendations or []),
            warnings=json.dumps(warnings or []),
            flags=json.dumps(flags or []),
            created_by=user_id,
            completed_at=datetime.now(timezone.utc) if status == AnalysisStatus.COMPLETED else None,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis

    @staticmethod
    def _finalize(
        db: Session,
        *,
        version: ProductVersion,
        analysis: Analysis,
        action: str,
        user_id: int,
        request: Optional[Request],
    ) -> Analysis:
        """Audit the analysis run, recording the content hash it was based on."""
        AuditService.log_action(
            db=db,
            user_id=user_id,
            action=action,
            resource="analysis",
            resource_id=analysis.id,
            details={
                "product_version_id": version.id,
                "analysis_type": analysis.analysis_type.value
                if hasattr(analysis.analysis_type, "value")
                else str(analysis.analysis_type),
                "status": analysis.status.value
                if hasattr(analysis.status, "value")
                else str(analysis.status),
                "content_hash": version.content_hash,
            },
            request=request,
        )
        return analysis

    # ============================================
    # Claim analysis
    # ============================================

    @staticmethod
    def analyze_claims(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Analysis:
        """
        Review every claim on a version against the accessible corpus.

        Returns the persisted ``Analysis`` row (type ``CLAIM_ANALYSIS``).
        """
        version = AnalysisService._version(db, product_id, version_id, user_id)

        claims = (
            db.query(Claim)
            .filter(Claim.product_version_id == version.id)
            .order_by(Claim.id.asc())
            .all()
        )
        evidence = (
            db.query(Evidence)
            .filter(Evidence.product_version_id == version.id)
            .order_by(Evidence.id.asc())
            .all()
        )

        try:
            result: ClaimAnalysisResult = analyze_claims_content(
                db, version, claims, evidence, user_id=user_id
            )
        except Exception as exc:
            logger.error("Claim analysis failed for version %s: %s", version.id, exc, exc_info=True)
            AnalysisService._persist(
                db,
                version=version,
                analysis_type=AnalysisType.CLAIM_ANALYSIS,
                status=AnalysisStatus.FAILED,
                results=None,
                summary=None,
                recommendations=None,
                warnings=[f"The AI analysis could not be completed: {exc}"],
                flags=["ai_unavailable"],
                user_id=user_id,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI analysis service is temporarily unavailable or returned "
                    "unusable output. A failed run has been recorded; please retry."
                ),
            )

        warnings = list(result.warnings) + [CLAIM_ANALYSIS_DISCLAIMER]
        flags = (
            ["expert_verified_claims_present"]
            if any(a.expert_verified_locked for a in result.assessments)
            else []
        )
        recommendations = [
            f"Provide evidence for claim {a.claim_id}: {a.claim_text[:80]}"
            for a in result.assessments
            if a.suggested_evidence_status == "needs_evidence"
        ]

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.CLAIM_ANALYSIS,
            status=AnalysisStatus.COMPLETED,
            results=result.model_dump(),
            summary=result.summary,
            recommendations=recommendations,
            warnings=warnings,
            flags=flags,
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="analyze_claims",
            user_id=user_id,
            request=request,
        )

    # ============================================
    # Comprehensive analysis
    # ============================================

    @staticmethod
    def analyze_product(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Analysis:
        """
        Orchestrate a comprehensive preliminary review of a version.

        Runs the claim review and a preliminary classification, then derives
        target-market considerations and expert-review recommendations. Stages
        owned by later phases are reported as ``deferred_components``.
        """
        version = AnalysisService._version(db, product_id, version_id, user_id)
        product: Product = version.product

        claims = (
            db.query(Claim)
            .filter(Claim.product_version_id == version.id)
            .order_by(Claim.id.asc())
            .all()
        )
        evidence = (
            db.query(Evidence)
            .filter(Evidence.product_version_id == version.id)
            .order_by(Evidence.id.asc())
            .all()
        )
        ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.product_version_id == version.id)
            .order_by(Ingredient.id.asc())
            .all()
        )
        formulation = (
            db.query(Formulation)
            .filter(Formulation.product_version_id == version.id)
            .first()
        )
        markets = (
            db.query(TargetMarket)
            .filter(TargetMarket.product_version_id == version.id)
            .order_by(TargetMarket.id.asc())
            .all()
        )

        failure_warnings: List[str] = []

        # --- claim review (a failure here degrades, it does not abort) ---
        try:
            claim_review = analyze_claims_content(db, version, claims, evidence, user_id=user_id)
        except Exception as exc:
            logger.error("Claim review failed inside product analysis: %s", exc, exc_info=True)
            failure_warnings.append(
                "The claim/evidence review could not be completed because the AI service "
                f"was unavailable ({exc}). This part of the analysis is missing."
            )
            claim_review = ClaimAnalysisResult(
                product_id=version.product_id,
                product_version_id=version.id,
                claim_count=len(claims),
                summary="Claim review unavailable.",
                warnings=list(failure_warnings),
            )

        # --- preliminary classification (optional) ---
        classification = None
        try:
            classification = classify_product(
                db, product, version, ingredients, formulation, claims, markets, evidence
            )
        except Exception as exc:
            logger.error("Product classification failed: %s", exc, exc_info=True)
            failure_warnings.append(
                "A preliminary product classification could not be produced because the AI "
                f"service was unavailable ({exc})."
            )

        # --- Phase 6 components (deterministic; no records are persisted here) ---
        # The dedicated Phase 6 endpoints record their own runs. Here we embed the
        # same analysis so a comprehensive run is not missing stages it can compute.
        # Screening is called with db=None so the comprehensive run does not trigger
        # corpus retrieval; the dedicated endpoints attach corpus sources.
        ip_route_map = None
        try:
            ip_route_map = build_ip_route_map(
                product, version, ingredients, formulation, claims, evidence, markets
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("IP route map failed: %s", exc, exc_info=True)
            failure_warnings.append(
                f"The IP route map could not be produced ({exc})."
            )

        patent_signals = None
        try:
            patent_signals = screen_patents(
                version, ingredients, formulation, claims, evidence, markets
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Patent signals failed: %s", exc, exc_info=True)
            failure_warnings.append(f"Patent signals could not be produced ({exc}).")

        biodiversity = None
        try:
            biodiversity = screen_biodiversity(
                version, ingredients, formulation, claims, evidence, markets, db=None
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Biodiversity screening failed: %s", exc, exc_info=True)
            failure_warnings.append(f"Biodiversity/ABS screening could not be produced ({exc}).")

        traditional_knowledge = None
        try:
            traditional_knowledge = screen_traditional_knowledge(
                version, ingredients, formulation, claims, evidence, markets, db=None
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Traditional-knowledge screening failed: %s", exc, exc_info=True)
            failure_warnings.append(
                f"Traditional-knowledge screening could not be produced ({exc})."
            )

        # --- derivations that need no model ---
        market_considerations = _market_considerations(markets)
        missing_information = _missing_information(
            ingredients, formulation, claims, evidence, markets
        )
        expert_review = _expert_review_recommendations(claim_review, missing_information, classification)

        warnings = list(claim_review.warnings) + failure_warnings
        warnings.append(
            "This is a preliminary, source-backed screening. "
            "It does not determine IP routes, patentability, biodiversity/ABS obligations, "
            "or regulatory approval."
        )
        if classification is not None:
            warnings.append(CLASSIFICATION_DISCLAIMER)
        if ip_route_map is not None:
            warnings.append(IP_ROUTE_DISCLAIMER)
        if patent_signals is not None:
            warnings.append(PATENT_DISCLAIMER)
        if biodiversity is not None:
            warnings.append(BIODIVERSITY_DISCLAIMER)
        if traditional_knowledge is not None:
            warnings.append(TRADITIONAL_KNOWLEDGE_DISCLAIMER)
        warnings.append(ANALYSIS_DISCLAIMER)

        analysis_summary = _build_analysis_summary(
            version=version,
            claims=claims,
            evidence=evidence,
            claim_review=claim_review,
            classification=classification,
            patent_signals=patent_signals,
            biodiversity=biodiversity,
        )

        result = ComprehensiveAnalysisResult(
            product_id=version.product_id,
            product_version_id=version.id,
            analysis_summary=analysis_summary,
            product_classification=classification,
            claim_review=claim_review,
            market_considerations=market_considerations,
            expert_review_recommendations=expert_review,
            missing_information=missing_information,
            ip_route_map=ip_route_map,
            patent_signals=patent_signals,
            biodiversity_screening=biodiversity,
            traditional_knowledge_screening=traditional_knowledge,
            deferred_components=list(DEFERRED_COMPONENTS),
            warnings=warnings,
        )

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.COMPREHENSIVE,
            status=AnalysisStatus.COMPLETED,
            results=result.model_dump(),
            summary=_comprehensive_summary(classification, claim_review),
            recommendations=expert_review,
            warnings=warnings,
            flags=["preliminary_screening"],
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="analyze_product",
            user_id=user_id,
            request=request,
        )

    # ============================================
    # Retrieval
    # ============================================

    @staticmethod
    def list_analyses(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        analysis_type: Optional[str] = None,
    ) -> List[Analysis]:
        """List analyses recorded for a version, newest first."""
        version = AnalysisService._version(db, product_id, version_id, user_id)

        query = db.query(Analysis).filter(Analysis.product_version_id == version.id)
        if analysis_type:
            try:
                query = query.filter(Analysis.analysis_type == AnalysisType(analysis_type.lower()))
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Unknown analysis_type '{analysis_type}'. Allowed values: "
                        f"{sorted(t.value for t in AnalysisType)}"
                    ),
                )
        return query.order_by(Analysis.created_at.desc(), Analysis.id.desc()).all()

    @staticmethod
    def get_analysis(
        db: Session,
        product_id: int,
        version_id: int,
        analysis_id: int,
        user_id: int,
    ) -> Analysis:
        """Fetch one analysis, scoped to an accessible version."""
        version = AnalysisService._version(db, product_id, version_id, user_id)
        analysis = (
            db.query(Analysis)
            .filter(Analysis.id == analysis_id, Analysis.product_version_id == version.id)
            .first()
        )
        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis not found")
        return analysis

    # ============================================
    # Serialisation
    # ============================================

    @staticmethod
    def serialize(analysis: Analysis) -> Dict[str, Any]:
        """Convert an Analysis row into the API representation."""
        data = _load_json(analysis.results)
        return {
            "id": analysis.id,
            "product_version_id": analysis.product_version_id,
            "analysis_type": analysis.analysis_type.value
            if hasattr(analysis.analysis_type, "value")
            else str(analysis.analysis_type),
            "status": analysis.status.value if hasattr(analysis.status, "value") else str(analysis.status),
            "summary": analysis.summary,
            "results": data,
            # Content hash this run was based on (None for rows written before
            # hash tracking); the UI compares it with the version's current hash.
            "content_hash": data.get("content_hash") if isinstance(data, dict) else None,
            "recommendations": _load_json(analysis.recommendations, default=[]),
            "warnings": _load_json(analysis.warnings, default=[]),
            "flags": _load_json(analysis.flags, default=[]),
            "created_by": analysis.created_by,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
            "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        }


# ============================================
# Derivations
# ============================================

def _market_considerations(markets: List[TargetMarket]) -> List[MarketConsideration]:
    """Build preliminary, review-oriented notes for each declared target market."""
    considerations: List[MarketConsideration] = []
    for market in markets:
        considerations.append(
            MarketConsideration(
                country=market.country,
                region=market.region,
                declared_regulatory_status=market.regulatory_status,
                consideration=(
                    f"Marketing this product in {market.country} may involve that market's own "
                    "requirements for Ayurvedic, herbal, food or medicinal products. The "
                    "applicable regime is not determined by this platform."
                ),
                review_questions=[
                    f"Which authority in {market.country} regulates this product category?",
                    f"Is the intended use for {market.country} consistent with the product classification?",
                    "Do any claims need to be reformulated or substantiated for this market?",
                ],
            )
        )
    return considerations


def _missing_information(
    ingredients: List[Ingredient],
    formulation: Optional[Formulation],
    claims: List[Claim],
    evidence: List[Evidence],
    markets: List[TargetMarket],
) -> List[str]:
    """List the gaps that most limit any analysis of this version."""
    missing: List[str] = []
    if not ingredients:
        missing.append("No ingredients recorded for this version.")
    else:
        if any(not ing.botanical_name for ing in ingredients):
            missing.append("One or more ingredients have no botanical name recorded.")
        if any(not ing.source_location for ing in ingredients):
            missing.append("Source/geographic origin is not recorded for one or more ingredients.")
        if any((ing.source_type is None) for ing in ingredients):
            missing.append("Cultivated/wild status is unknown for one or more ingredients.")
    if formulation is None:
        missing.append("No formulation or extraction process recorded.")
    if not claims:
        missing.append("No claims recorded, so claim/evidence review is not possible.")
    if not evidence:
        missing.append("No evidence documents attached to this version.")
    if not markets:
        missing.append("No target markets recorded.")
    return missing


def _expert_review_recommendations(
    claim_review: ClaimAnalysisResult,
    missing_information: List[str],
    classification: Any,
) -> List[str]:
    """Derive the questions a human expert would need to consider."""
    recommendations: List[str] = []

    for assessment in claim_review.assessments:
        if assessment.expert_verified_locked:
            continue
        if assessment.risk_level == "high":
            recommendations.append(
                f"Expert review recommended for high-risk claim {assessment.claim_id}: "
                f"{assessment.claim_text[:100]}"
            )
        elif assessment.suggested_evidence_status == "needs_evidence":
            recommendations.append(
                f"Provide evidence for claim {assessment.claim_id} before relying on it: "
                f"{assessment.claim_text[:100]}"
            )

    if classification is not None:
        if getattr(classification, "status", "PRELIMINARY") == "UNRESOLVED":
            recommendations.append(
                "Classification is UNRESOLVED: supply the missing information "
                "(intended use, dosage form, complete ingredient list, exact label "
                "claims) so a preliminary category can be indicated, then confirm it "
                "with a regulatory expert."
            )
        else:
            recommendations.append(
                f"Confirm the preliminary classification '{classification.category}' "
                f"(confidence: {classification.confidence}) with a regulatory expert."
            )

    if missing_information:
        recommendations.append(
            "Supply the missing product information listed in this analysis; "
            "each gap weakens the reliability of the screening."
        )

    if not recommendations:
        recommendations.append(
            "No specific expert-review triggers were identified from the available data. "
            "This is not an assurance that review is unnecessary."
        )
    return recommendations


def _comprehensive_summary(
    classification: Any,
    claim_review: ClaimAnalysisResult,
) -> str:
    """One-line summary of a comprehensive analysis (status-led, spec item 4)."""
    parts: List[str] = []
    if classification is not None:
        if getattr(classification, "status", "PRELIMINARY") == "UNRESOLVED":
            parts.append(
                f"Classification: UNRESOLVED (confidence {classification.confidence}) - "
                "more information needed; possible pathways are listed instead of a "
                "single main conclusion."
            )
        else:
            parts.append(
                f"Preliminary category: {classification.category} (confidence {classification.confidence})."
            )
    parts.append(claim_review.summary or "Claim review produced no summary.")
    return " ".join(parts)


def _build_analysis_summary(
    *,
    version: ProductVersion,
    claims: List[Claim],
    evidence: List[Evidence],
    claim_review: ClaimAnalysisResult,
    classification: Any,
    patent_signals: Any,
    biodiversity: Any,
) -> AnalysisSummary:
    """
    Derive the ANALYSIS SUMMARY card (spec item 8).

    Deterministic over recorded data only: nothing here comes from the model.
    """
    has_claims = bool(claims)

    if not has_claims:
        overall_status = "NOT_ASSESSED"
    else:
        # The provenance firewall means no machine run can ever report SUPPORTED.
        overall_status = "PARTIALLY_SUPPORTED"

    verified_evidence = any(
        (e.verification_status.value if hasattr(e.verification_status, "value") else str(e.verification_status))
        == "verified"
        for e in evidence
    )
    all_cited = bool(claim_review.assessments) and all(
        a.citations or a.expert_verified_locked for a in claim_review.assessments
    )
    evidence_completeness = "COMPLETE" if (verified_evidence and all_cited) else "INCOMPLETE"

    classification_status = "NOT_RUN"
    if classification is not None:
        classification_status = getattr(classification, "status", "PRELIMINARY")

    expert_review = (
        "RECOMMENDED"
        if any(a.review_required for a in claim_review.assessments)
        or classification_status == "UNRESOLVED"
        else "OPTIONAL"
    )

    return AnalysisSummary(
        product_version=f"V{version.version_number}",
        overall_status=overall_status,
        evidence_completeness=evidence_completeness,
        claim_review="REQUIRED" if has_claims else "NOT_REQUIRED",
        patent_screening=(
            getattr(patent_signals, "corpus_type", "NOT_SCREENED")
            if patent_signals is not None
            else "NOT_SCREENED"
        ),
        biodiversity_screening=(
            getattr(biodiversity, "status", "NOT_SCREENED")
            if biodiversity is not None
            else "NOT_SCREENED"
        ),
        classification=classification_status,
        expert_review=expert_review,
    )


def _load_json(value: Optional[str], default: Any = None) -> Any:
    """Parse a JSON text column, tolerating legacy/empty values."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
