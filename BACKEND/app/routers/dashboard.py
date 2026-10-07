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
from app.config import get_settings
from app.utils.cache import cache, CACHED_MARKER

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_TERMINAL_REVIEWS = (ReviewStatus.REVIEWED, ReviewStatus.ARCHIVED)


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


def _build_dashboard(db: Session, user_id: int, admin: bool) -> dict:
    """The roll-up itself. COUNT(*) everywhere - never .all()+len().

    The previous version loaded every product/version id into Python to
    count them; on Supabase free that meant shipping whole tables over the
    network for two integers.
    """
    products_base = db.query(func.count(Product.id)).filter(Product.is_active == True)  # noqa: E712
    if not admin:
        products_base = products_base.filter(Product.created_by == user_id)
    product_count = products_base.scalar() or 0

    versions_base = db.query(func.count(ProductVersion.id))
    if admin:
        version_count = versions_base.scalar() or 0
    else:
        version_count = (
            versions_base.join(Product, ProductVersion.product_id == Product.id)
            .filter(Product.created_by == user_id, Product.is_active == True)  # noqa: E712
            .scalar() or 0
        )

    # Scoping subqueries: the DB filters, Python never sees the id lists.
    if admin:
        version_scope = db.query(ProductVersion.id)
        product_scope = db.query(Product.id).filter(Product.is_active == True)  # noqa: E712
    else:
        version_scope = (
            db.query(ProductVersion.id)
            .join(Product, ProductVersion.product_id == Product.id)
            .filter(Product.created_by == user_id, Product.is_active == True)  # noqa: E712
        )
        product_scope = (
            db.query(Product.id).filter(
                Product.created_by == user_id, Product.is_active == True  # noqa: E712
            )
        )

    reviews_base = db.query(func.count(ExpertReview.id)).filter(
        ~ExpertReview.status.in_(_TERMINAL_REVIEWS)
    )
    if not admin:
        reviews_base = reviews_base.filter(
            ExpertReview.product_id.in_(product_scope)
        )
    pending_reviews = reviews_base.scalar() or 0

    analyses_by_type = (
        db.query(Analysis.analysis_type, func.count(Analysis.id))
        .filter(Analysis.product_version_id.in_(version_scope))
        .group_by(Analysis.analysis_type)
        .all()
    )

    claims_needing = (
        db.query(func.count(Claim.id))
        .filter(
            Claim.product_version_id.in_(version_scope),
            Claim.evidence_status == EvidenceStatus.NEEDS_EVIDENCE,
        )
        .scalar()
    ) or 0

    patent_records = (
        db.query(func.count(PatentRecord.id))
        .filter(PatentRecord.product_version_id.in_(version_scope))
        .scalar()
    ) or 0

    recent_disclosures = (
        db.query(Disclosure)
        .filter(Disclosure.product_id.in_(product_scope))
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

    return {
        "product_count": product_count,
        "version_count": version_count,
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
    }


@router.get("", response_model=APIResponse)
def get_dashboard(
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = _uid(token_payload)
    admin = is_admin(db, user_id)
    settings = get_settings()
    if settings.cache_enabled:
        key = f"dashboard:u{user_id}:a{int(admin)}"
        hit = cache.get(key)
        if hit is not None:
            out = dict(hit)
            out[CACHED_MARKER] = True
            return APIResponse(success=True, data=out)
        data = _build_dashboard(db, user_id, admin)
        payload = dict(data)
        payload[CACHED_MARKER] = False
        cache.set(key, payload, ttl=settings.cache_dashboard_ttl_seconds)
        return APIResponse(success=True, data=payload)
    return APIResponse(success=True, data=_build_dashboard(db, user_id, admin))
