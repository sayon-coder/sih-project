"""
Dashboard router (Phase 10).

  GET /api/dashboard

One honest roll-up over the caller's own products (ADMIN users see the whole
platform): product/version counts, pending reviews, analyses, claims needing
evidence, screening coverage, recent disclosures and recent activity.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Analysis,
    AuditLog,
    Claim,
    Disclosure,
    EvidenceStatus,
    ExpertReview,
    PatentRecord,
    Product,
    ProductVersion,
)
from app.models.review_models import ReviewStatus
from app.schemas.schemas import APIResponse
from app.utils import is_admin, verify_token

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_TERMINAL_REVIEWS = (ReviewStatus.REVIEWED, ReviewStatus.ARCHIVED)


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


@router.get("", response_model=APIResponse)
def get_dashboard(
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = _uid(token_payload)
    admin = is_admin(db, user_id)

    products_q = db.query(Product).filter(Product.is_active == True)  # noqa: E712
    if not admin:
        products_q = products_q.filter(Product.created_by == user_id)
    product_ids = [p.id for p in products_q.all()]

    versions_q = db.query(ProductVersion)
    if product_ids:
        versions_q = versions_q.filter(ProductVersion.product_id.in_(product_ids))
    else:
        versions_q = versions_q.filter(ProductVersion.id == -1)
    version_ids = [v.id for v in versions_q.all()]

    reviews_q = db.query(ExpertReview)
    if not admin and product_ids:
        reviews_q = reviews_q.filter(ExpertReview.product_id.in_(product_ids))
    elif not admin:
        reviews_q = reviews_q.filter(ExpertReview.id == -1)
    pending_reviews = reviews_q.filter(~ExpertReview.status.in_(_TERMINAL_REVIEWS)).count()

    analyses_by_type = (
        db.query(Analysis.analysis_type, func.count(Analysis.id))
        .filter(Analysis.product_version_id.in_(version_ids) if version_ids else Analysis.id == -1)
        .group_by(Analysis.analysis_type)
        .all()
    )

    claims_needing = (
        db.query(func.count(Claim.id))
        .filter(
            Claim.product_version_id.in_(version_ids) if version_ids else Claim.id == -1,
            Claim.evidence_status == EvidenceStatus.NEEDS_EVIDENCE,
        )
        .scalar()
    )

    patent_records = (
        db.query(func.count(PatentRecord.id))
        .filter(
            PatentRecord.product_version_id.in_(version_ids) if version_ids else PatentRecord.id == -1
        )
        .scalar()
    )

    recent_disclosures = (
        db.query(Disclosure)
        .filter(Disclosure.product_id.in_(product_ids) if product_ids else Disclosure.id == -1)
        .order_by(Disclosure.created_at.desc(), Disclosure.id.desc())
        .limit(5)
        .all()
    )

    activity_q = db.query(AuditLog)
    if not admin:
        activity_q = activity_q.filter(AuditLog.user_id == user_id)
    recent_activity = (
        activity_q.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(10).all()
    )

    return APIResponse(
        success=True,
        data={
            "product_count": len(product_ids),
            "version_count": len(version_ids),
            "pending_reviews": pending_reviews,
            "analyses_total": sum(n for _, n in analyses_by_type),
            "analyses_by_type": [
                {"analysis_type": str(t), "count": n} for t, n in analyses_by_type
            ],
            "claims_needing_evidence": claims_needing,
            "patent_records": patent_records,
            "recent_disclosures": [
                {
                    "id": d.id,
                    "product_id": d.product_id,
                    "product_version_id": d.product_version_id,
                    "disclosure_type": (
                        d.disclosure_type.value
                        if hasattr(d.disclosure_type, "value")
                        else str(d.disclosure_type)
                    ),
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in recent_disclosures
            ],
            "recent_activity": [
                {
                    "id": a.id,
                    "action": a.action,
                    "resource": a.resource,
                    "resource_id": a.resource_id,
                    "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                }
                for a in recent_activity
            ],
        },
    )
