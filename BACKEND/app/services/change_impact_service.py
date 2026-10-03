"""
Change-impact service (Phase 7).

Runs the formulation change-impact simulator for two versions of one product and
persists each run as an immutable ``change_impacts`` row pinned to both versions.

Safety rules carried over from earlier phases:

* the comparison is **advisory** - it never edits either version;
* **version-pinned** - a run always records the two exact versions it compared,
  so a later version cannot silently change a historical comparison;
* a run is never rewritten - re-running writes a new row.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis.change_impact import build_change_impact
from app.analysis.change_impact_schemas import ChangeImpactResult
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisType,
    ChangeImpact,
    ProductVersion,
)
from app.services.audit_service import AuditService
from app.services.version_content import load_version_content
from app.utils.authorization import get_accessible_product, get_accessible_version

logger = logging.getLogger(__name__)


class ChangeImpactService:
    """Run and retrieve change-impact comparisons."""

    # ============================================
    # Helpers
    # ============================================

    @staticmethod
    def _latest_classification(db: Session, version_id: int) -> Optional[str]:
        """
        The preliminary category from the newest comprehensive analysis, if any.

        Reusing a recorded classification keeps this endpoint deterministic and
        free of any model call; when neither version has one, the report says the
        category could not be compared instead of guessing.
        """
        analysis = (
            db.query(Analysis)
            .filter(
                Analysis.product_version_id == version_id,
                Analysis.analysis_type == AnalysisType.COMPREHENSIVE,
                Analysis.status == AnalysisStatus.COMPLETED,
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .first()
        )
        if analysis is None or not analysis.results:
            return None
        try:
            results = json.loads(analysis.results)
        except (json.JSONDecodeError, TypeError):
            return None
        classification = (results or {}).get("product_classification") or {}
        return classification.get("category")

    # ============================================
    # Run
    # ============================================

    @staticmethod
    def run(
        db: Session,
        product_id: int,
        old_version_id: int,
        new_version_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> ChangeImpact:
        """Compare two versions of a product and record the run."""
        product = get_accessible_product(db, product_id, user_id)

        if old_version_id == new_version_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "old_version_id and new_version_id must differ; a version cannot be "
                    "compared with itself."
                ),
            )

        # Both versions must belong to this product (404 otherwise).
        old_version: ProductVersion = get_accessible_version(db, product_id, old_version_id, user_id)
        new_version: ProductVersion = get_accessible_version(db, product_id, new_version_id, user_id)

        old_content = load_version_content(db, old_version)
        new_content = load_version_content(db, new_version)

        try:
            from app.services.disclosure_service import DisclosureService

            result: ChangeImpactResult = build_change_impact(
                product,
                old_version,
                new_version,
                old_content,
                new_content,
                old_classification=ChangeImpactService._latest_classification(db, old_version.id),
                new_classification=ChangeImpactService._latest_classification(db, new_version.id),
                old_disclosure_types=DisclosureService.types_for_version(db, old_version.id),
                new_disclosure_types=DisclosureService.types_for_version(db, new_version.id),
            )
        except Exception as exc:  # noqa: BLE001 - record a failed run, never a silent one
            logger.error("Change-impact analysis failed for product %s: %s", product_id, exc, exc_info=True)
            impact = ChangeImpact(
                product_id=product_id,
                old_version_id=old_version_id,
                new_version_id=new_version_id,
                status=AnalysisStatus.FAILED,
                results=None,
                summary=None,
                review_questions=json.dumps([]),
                warnings=json.dumps([f"The change-impact analysis could not be completed: {exc}"]),
                created_by=user_id,
            )
            db.add(impact)
            db.commit()
            db.refresh(impact)
            raise HTTPException(
                status_code=500,
                detail=(
                    "The change-impact analysis could not be completed. A failed run has been "
                    "recorded; please retry."
                ),
            )

        results = result.model_dump()
        impact = ChangeImpact(
            product_id=product_id,
            old_version_id=old_version_id,
            new_version_id=new_version_id,
            status=AnalysisStatus.COMPLETED,
            results=json.dumps(results),
            summary=result.summary,
            review_questions=json.dumps([q.model_dump() for q in result.review_questions]),
            warnings=json.dumps(result.warnings),
            created_by=user_id,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(impact)
        db.commit()
        db.refresh(impact)

        AuditService.log_action(
            db=db,
            user_id=user_id,
            action="change_impact",
            resource="change_impact",
            resource_id=impact.id,
            details={
                "product_id": product_id,
                "old_version_id": old_version_id,
                "new_version_id": new_version_id,
                "old_content_hash": old_version.content_hash,
                "new_content_hash": new_version.content_hash,
                "change_count": result.change_count,
                "categories_changed": result.categories_changed,
                "expert_review_recommended": result.expert_review_recommended,
            },
            request=request,
        )
        return impact

    # ============================================
    # Retrieval
    # ============================================

    @staticmethod
    def list(db: Session, product_id: int, user_id: int) -> List[ChangeImpact]:
        """List change-impact runs for a product, newest first."""
        get_accessible_product(db, product_id, user_id)
        return (
            db.query(ChangeImpact)
            .filter(ChangeImpact.product_id == product_id)
            .order_by(ChangeImpact.created_at.desc(), ChangeImpact.id.desc())
            .all()
        )

    @staticmethod
    def get(db: Session, product_id: int, impact_id: int, user_id: int) -> ChangeImpact:
        """Fetch one run, scoped to an accessible product."""
        get_accessible_product(db, product_id, user_id)
        impact = (
            db.query(ChangeImpact)
            .filter(ChangeImpact.id == impact_id, ChangeImpact.product_id == product_id)
            .first()
        )
        if impact is None:
            raise HTTPException(status_code=404, detail="Change impact not found")
        return impact

    # ============================================
    # Serialisation
    # ============================================

    @staticmethod
    def serialize(impact: ChangeImpact) -> Dict[str, Any]:
        """Convert a ChangeImpact row into the API representation."""
        return {
            "id": impact.id,
            "product_id": impact.product_id,
            "old_version_id": impact.old_version_id,
            "new_version_id": impact.new_version_id,
            "status": impact.status.value if hasattr(impact.status, "value") else str(impact.status),
            "summary": impact.summary,
            "results": _load_json(impact.results),
            "review_questions": _load_json(impact.review_questions, default=[]),
            "warnings": _load_json(impact.warnings, default=[]),
            "created_by": impact.created_by,
            "created_at": impact.created_at.isoformat() if impact.created_at else None,
            "completed_at": impact.completed_at.isoformat() if impact.completed_at else None,
        }


def _load_json(value: Optional[str], default: Any = None) -> Any:
    """Parse a JSON text column, tolerating legacy/empty values."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
