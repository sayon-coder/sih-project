"""
Expert review service (Phase 9).

Drives the review state machine for one product version:

  DRAFT -> AI_SCREENED -> REVIEW_REQUIRED -> EXPERT_REVIEW
      -> CORRECTION_REQUESTED -> RESUBMITTED -> REVIEWED -> ARCHIVED

Rules:
* the requester (product owner) moves DRAFT -> AI_SCREENED (deterministic
  checklist) -> REVIEW_REQUIRED, and CORRECTION_REQUESTED -> RESUBMITTED;
* only EXPERT/ADMIN users act as reviewers (comment-driven EXPERT_REVIEW,
  request-correction, complete, archive);
* completing a review may explicitly promote listed claims/evidence to
  EXPERT_VERIFIED - the only path that ever sets that provenance, and it is
  audited per record;
* AI output stays distinguishable: the AI screen is a recorded checklist,
  never a verdict.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import Claim, Evidence, EvidenceStatus, ProductVersion, VerificationStatus
from app.models.review_models import ExpertReview, ReviewComment, ReviewStatus
from app.models.models import RoleName, User
from app.services.audit_service import AuditService
from app.services.version_content import load_version_content
from app.utils.authorization import (
    get_accessible_product,
    get_accessible_version,
    get_user_role_names,
)

_EXPERT_ROLES = {RoleName.EXPERT.value, RoleName.ADMIN.value}


def _is_expert(db: Session, user_id: int) -> bool:
    return bool(get_user_role_names(db, user_id) & _EXPERT_ROLES)


def _status_value(status) -> str:
    return status.value if isinstance(status, ReviewStatus) else str(status)


def _notify_review_desk(
    db: Session,
    review: ExpertReview,
    user_id: int,
    audit_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Email the review desk about a new request. Best-effort, never raises.

    The email carries the reference number, the requester's identity, the
    product/version under review, what the requester wants examined, and the
    IST submission time. Any failure is audit-logged, never propagated.
    Returns the ``{"sent", "reason"}`` outcome so the API can report it
    honestly instead of claiming a send that never happened.
    """
    from app.config import get_settings
    from app.models import Product
    from app.services.notify_service import send_review_email

    settings = get_settings()
    try:
        requester = db.get(User, user_id)
        product = db.get(Product, review.product_id)
        version = db.get(ProductVersion, review.product_version_id)
        payload = {
            "ref": f"RV-{review.id:06d}",
            "title": review.title,
            "notes": review.notes,
            "status": _status_value(review.status),
            "product_name": product.name if product else f"#{review.product_id}",
            "version_number": (
                version.version_number if version else review.product_version_id
            ),
            "requester_name": (
                requester.username if requester else f"user #{user_id}"
            ),
            "requester_email": requester.email if requester else "not recorded",
            "submitted_at": review.created_at,
            "review_url": (
                f"{settings.public_base_url.rstrip('/')}/reviews"
                if settings.public_base_url
                else ""
            ),
            "audit_id": audit_id,
        }
        result = send_review_email(
            payload,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_username=settings.smtp_username,
            smtp_password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            sender=settings.review_notify_from or settings.smtp_username,
            recipient=settings.review_notify_email,
        )
        AuditService.log_action(
            db,
            user_id,
            (
                "review_notify_sent"
                if result["sent"]
                else "review_notify_skipped"
            ),
            "review",
            review.id,
            {"ref": payload["ref"], "reason": result["reason"]},
        )
        return result
    except Exception as exc:  # never break review creation for email
        try:
            AuditService.log_action(
                db,
                user_id,
                "review_notify_failed",
                "review",
                review.id,
                {"error": f"{exc.__class__.__name__}"},
            )
        except Exception:
            pass
    return {"sent": False, "reason": "notification failed internally"}


def serialize(review: ExpertReview) -> Dict[str, Any]:
    return {
        "id": review.id,
        "product_id": review.product_id,
        "product_version_id": review.product_version_id,
        "status": _status_value(review.status),
        "title": review.title,
        "notes": review.notes,
        "ai_screen_summary": review.ai_screen_summary,
        "requested_by": review.requested_by,
        "assigned_expert_id": review.assigned_expert_id,
        "comments": [
            {
                "id": c.id,
                "author_id": c.author_id,
                "body": c.body,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in (review.comments or [])
        ],
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "updated_at": review.updated_at.isoformat() if review.updated_at else None,
    }


def _ai_screen_checklist(db: Session, version: ProductVersion) -> str:
    """Deterministic pre-check over stored content (counts only, no verdicts)."""
    content = load_version_content(db, version)
    claims = content["claims"]
    evidence = content["evidence"]
    markets = content["markets"]
    needing = sum(1 for c in claims if 'NEEDS_EVIDENCE' in str(c.evidence_status).upper())
    lines = [
        f"Claims recorded: {len(claims)} ({needing} needing evidence).",
        f"Evidence documents recorded: {len(evidence)}.",
        f"Formulation recorded: {'yes' if content['formulation'] is not None else 'no'}.",
        f"Target markets recorded: {len(markets)}.",
        "This automated checklist is a completeness scan, not a review verdict. "
        "Human expert review is still required.",
    ]
    return "\n".join(lines)


class ReviewService:
    """Create reviews, move them through the workflow, and record comments."""

    # ---------- helpers ----------

    @staticmethod
    def _get(db: Session, review_id: int, user_id: int) -> ExpertReview:
        review = db.query(ExpertReview).filter(ExpertReview.id == review_id).first()
        if review is None:
            raise HTTPException(status_code=404, detail="Review not found")
        try:
            get_accessible_product(db, review.product_id, user_id)
        except HTTPException:
            # The product owner always has access; members of the reviewer pool
            # (EXPERT/ADMIN) may open any review so they can do their job.
            # Everyone else gets 404 to avoid leaking the review's existence.
            if not _is_expert(db, user_id):
                raise
        return review

    @staticmethod
    def _move(
        db: Session,
        review: ExpertReview,
        to: ReviewStatus,
        user_id: int,
        action: str,
        request: Optional[Request] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ExpertReview:
        review.status = to
        review.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(review)
        AuditService.log_action(
            db, user_id, action, "review", review.id,
            {"status": to.value, **(extra or {})}, request,
        )
        return review

    # ---------- lifecycle ----------

    @staticmethod
    def create(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        request: Optional[Request] = None,
    ) -> Tuple[ExpertReview, Dict[str, Any]]:
        get_accessible_version(db, product_id, version_id, user_id)
        review = ExpertReview(
            product_id=product_id,
            product_version_id=version_id,
            status=ReviewStatus.DRAFT,
            title=title,
            notes=notes,
            requested_by=user_id,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        audit_entry = AuditService.log_action(
            db, user_id, "create_review", "review", review.id,
            {"product_id": product_id, "product_version_id": version_id}, request,
        )
        notify_result = _notify_review_desk(db, review, user_id, audit_entry.id)
        return review, notify_result

    @staticmethod
    def notify(db: Session, review_id: int, user_id: int) -> Dict[str, Any]:
        """(Re)send the review-desk email for an existing review.

        Owner- or reviewer-pool-visible reviews only (same access rule as
        reading). Best-effort: returns the ``{"sent", "reason"}`` outcome.
        """
        review = ReviewService._get(db, review_id, user_id)
        return _notify_review_desk(db, review, user_id)

    @staticmethod
    def list(db: Session, user_id: int, status: Optional[str] = None) -> List[ExpertReview]:
        from app.models import Product

        query = db.query(ExpertReview).join(
            Product, Product.id == ExpertReview.product_id
        )
        if not _is_expert(db, user_id):
            query = query.filter(Product.created_by == user_id)
        if status:
            try:
                query = query.filter(ExpertReview.status == ReviewStatus(status))
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
        return query.order_by(ExpertReview.created_at.desc(), ExpertReview.id.desc()).all()

    @staticmethod
    def get(db: Session, review_id: int, user_id: int) -> ExpertReview:
        return ReviewService._get(db, review_id, user_id)

    @staticmethod
    def submit(db: Session, review_id: int, user_id: int, request=None) -> ExpertReview:
        """DRAFT -> AI_SCREENED: run the deterministic completeness checklist."""
        review = ReviewService._get(db, review_id, user_id)
        if _status_value(review.status) != ReviewStatus.DRAFT.value:
            raise HTTPException(status_code=409, detail="Only DRAFT reviews can be submitted")
        version = db.query(ProductVersion).filter(ProductVersion.id == review.product_version_id).first()
        review.ai_screen_summary = _ai_screen_checklist(db, version)
        db.commit()
        return ReviewService._move(db, review, ReviewStatus.AI_SCREENED, user_id, "submit_review", request)

    @staticmethod
    def request_review(db: Session, review_id: int, user_id: int, request=None) -> ExpertReview:
        """AI_SCREENED -> REVIEW_REQUIRED: the requester asks for a human expert."""
        review = ReviewService._get(db, review_id, user_id)
        if _status_value(review.status) != ReviewStatus.AI_SCREENED.value:
            raise HTTPException(status_code=409, detail="Review is not awaiting a review request")
        return ReviewService._move(db, review, ReviewStatus.REVIEW_REQUIRED, user_id, "request_expert_review", request)

    @staticmethod
    def comment(
        db: Session, review_id: int, user_id: int, body: str, request=None
    ) -> ExpertReview:
        """Add a comment. An expert's comment on REVIEW_REQUIRED/RESUBMITTED
        opens EXPERT_REVIEW; terminal states refuse new comments."""
        review = ReviewService._get(db, review_id, user_id)
        current = _status_value(review.status)
        if current in (ReviewStatus.REVIEWED.value, ReviewStatus.ARCHIVED.value):
            raise HTTPException(status_code=409, detail="Review is closed to new comments")
        if not body or not body.strip():
            raise HTTPException(status_code=422, detail="Comment body must not be empty")
        db.add(ReviewComment(review_id=review.id, author_id=user_id, body=body.strip()))
        db.commit()
        if _is_expert(db, user_id) and current in (
            ReviewStatus.REVIEW_REQUIRED.value, ReviewStatus.RESUBMITTED.value
        ):
            review.assigned_expert_id = review.assigned_expert_id or user_id
            db.commit()
            return ReviewService._move(db, review, ReviewStatus.EXPERT_REVIEW, user_id, "begin_expert_review", request)
        db.refresh(review)
        AuditService.log_action(db, user_id, "comment_review", "review", review.id, None, request)
        return review

    @staticmethod
    def request_correction(
        db: Session, review_id: int, user_id: int, note: Optional[str] = None, request=None
    ) -> ExpertReview:
        """EXPERT_REVIEW -> CORRECTION_REQUESTED (reviewer only)."""
        review = ReviewService._get(db, review_id, user_id)
        if not _is_expert(db, user_id):
            raise HTTPException(status_code=403, detail="Only experts can request corrections")
        if _status_value(review.status) != ReviewStatus.EXPERT_REVIEW.value:
            raise HTTPException(status_code=409, detail="Corrections can only be requested during expert review")
        if note:
            db.add(ReviewComment(review_id=review.id, author_id=user_id, body=note))
            db.commit()
        return ReviewService._move(db, review, ReviewStatus.CORRECTION_REQUESTED, user_id, "request_correction", request)

    @staticmethod
    def resubmit(db: Session, review_id: int, user_id: int, note: Optional[str] = None, request=None) -> ExpertReview:
        """CORRECTION_REQUESTED -> RESUBMITTED (requester addresses the correction)."""
        review = ReviewService._get(db, review_id, user_id)
        if _status_value(review.status) != ReviewStatus.CORRECTION_REQUESTED.value:
            raise HTTPException(status_code=409, detail="No correction has been requested")
        if note:
            db.add(ReviewComment(review_id=review.id, author_id=user_id, body=note))
            db.commit()
        return ReviewService._move(db, review, ReviewStatus.RESUBMITTED, user_id, "resubmit_review", request)

    @staticmethod
    def complete(
        db: Session,
        review_id: int,
        user_id: int,
        verify_claim_ids: Optional[List[int]] = None,
        verify_evidence_ids: Optional[List[int]] = None,
        request=None,
    ) -> ExpertReview:
        """EXPERT_REVIEW/RESUBMITTED -> REVIEWED (reviewer only), with optional
        explicit promotion of listed claims/evidence to EXPERT_VERIFIED."""
        review = ReviewService._get(db, review_id, user_id)
        if not _is_expert(db, user_id):
            raise HTTPException(status_code=403, detail="Only experts can complete reviews")
        if _status_value(review.status) not in (
            ReviewStatus.EXPERT_REVIEW.value, ReviewStatus.RESUBMITTED.value
        ):
            raise HTTPException(status_code=409, detail="Review is not under expert review")
        verified: Dict[str, List[int]] = {"claims": [], "evidence": []}
        for cid in verify_claim_ids or []:
            claim = (
                db.query(Claim)
                .filter(Claim.id == cid, Claim.product_version_id == review.product_version_id)
                .first()
            )
            if claim is None:
                raise HTTPException(status_code=404, detail=f"Claim {cid} not found in this version")
            claim.evidence_status = EvidenceStatus.EXPERT_VERIFIED
            claim.provenance = "EXPERT_VERIFIED"
            claim.review_status = "reviewed"
            verified["claims"].append(cid)
        for eid in verify_evidence_ids or []:
            ev = (
                db.query(Evidence)
                .filter(Evidence.id == eid, Evidence.product_version_id == review.product_version_id)
                .first()
            )
            if ev is None:
                raise HTTPException(status_code=404, detail=f"Evidence {eid} not found in this version")
            ev.verification_status = VerificationStatus.VERIFIED
            ev.provenance = "EXPERT_VERIFIED"
            verified["evidence"].append(eid)
        db.commit()
        return ReviewService._move(
            db, review, ReviewStatus.REVIEWED, user_id, "complete_review", request,
            {"verified": verified},
        )

    @staticmethod
    def archive(db: Session, review_id: int, user_id: int, request=None) -> ExpertReview:
        """REVIEWED -> ARCHIVED (reviewer only)."""
        review = ReviewService._get(db, review_id, user_id)
        if not _is_expert(db, user_id):
            raise HTTPException(status_code=403, detail="Only experts can archive reviews")
        if _status_value(review.status) != ReviewStatus.REVIEWED.value:
            raise HTTPException(status_code=409, detail="Only REVIEWED reviews can be archived")
        return ReviewService._move(db, review, ReviewStatus.ARCHIVED, user_id, "archive_review", request)
