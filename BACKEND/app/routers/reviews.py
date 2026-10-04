"""
Expert review router (Phase 9).

  POST /api/reviews                        create a DRAFT review for a version
  GET  /api/reviews                        list visible reviews (?status=)
  GET  /api/reviews/{review_id}            one review with comments
  POST /api/reviews/{review_id}/submit            DRAFT -> AI_SCREENED
  POST /api/reviews/{review_id}/request-review    AI_SCREENED -> REVIEW_REQUIRED
  POST /api/reviews/{review_id}/comment           comment (expert comment opens EXPERT_REVIEW)
  POST /api/reviews/{review_id}/request-correction EXPERT_REVIEW -> CORRECTION_REQUESTED
  POST /api/reviews/{review_id}/resubmit          CORRECTION_REQUESTED -> RESUBMITTED
  POST /api/reviews/{review_id}/complete          -> REVIEWED (reviewer only)
  POST /api/reviews/{review_id}/archive           REVIEWED -> ARCHIVED (reviewer only)

Reviewer-only actions return 403 for non-experts; illegal transitions are 409.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.schemas import APIResponse
from app.services.review_service import ReviewService, serialize
from app.utils import verify_token

router = APIRouter(prefix="/api/reviews", tags=["Expert Reviews"])


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


class ReviewCreate(BaseModel):
    product_id: int
    product_version_id: int
    title: Optional[str] = None
    notes: Optional[str] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class NoteBody(BaseModel):
    note: Optional[str] = None


class CompleteBody(BaseModel):
    verify_claim_ids: List[int] = Field(default_factory=list)
    verify_evidence_ids: List[int] = Field(default_factory=list)


@router.post("", response_model=APIResponse, status_code=201)
def create_review(
    body: ReviewCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review, notify_result = ReviewService.create(
        db, body.product_id, body.product_version_id, _uid(token_payload),
        body.title, body.notes, request=request,
    )
    return APIResponse(
        success=True,
        data={**serialize(review), "email_notification": notify_result},
        message="Review created",
    )


@router.get("", response_model=APIResponse)
def list_reviews(
    status: Optional[str] = Query(default=None),
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reviews = ReviewService.list(db, _uid(token_payload), status)
    return APIResponse(
        success=True,
        data=[serialize(r) for r in reviews],
        message=f"Found {len(reviews)} review(s)",
    )


@router.get("/{review_id}", response_model=APIResponse)
def get_review(
    review_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return APIResponse(success=True, data=serialize(ReviewService.get(db, review_id, _uid(token_payload))))


@router.post("/{review_id}/submit", response_model=APIResponse)
def submit_review(
    review_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.submit(db, review_id, _uid(token_payload), request=request)
    return APIResponse(success=True, data=serialize(review), message="Review submitted for AI screening")


@router.post("/{review_id}/request-review", response_model=APIResponse)
def request_review(
    review_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.request_review(db, review_id, _uid(token_payload), request=request)
    return APIResponse(success=True, data=serialize(review), message="Expert review requested")


@router.post("/{review_id}/comment", response_model=APIResponse)
def comment_review(
    review_id: int,
    body: CommentCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.comment(db, review_id, _uid(token_payload), body.body, request=request)
    return APIResponse(success=True, data=serialize(review), message="Comment recorded")


@router.post("/{review_id}/request-correction", response_model=APIResponse)
def request_correction(
    review_id: int,
    body: NoteBody,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.request_correction(db, review_id, _uid(token_payload), body.note, request=request)
    return APIResponse(success=True, data=serialize(review), message="Correction requested")


@router.post("/{review_id}/resubmit", response_model=APIResponse)
def resubmit_review(
    review_id: int,
    body: NoteBody,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.resubmit(db, review_id, _uid(token_payload), body.note, request=request)
    return APIResponse(success=True, data=serialize(review), message="Review resubmitted")


@router.post("/{review_id}/complete", response_model=APIResponse)
def complete_review(
    review_id: int,
    body: CompleteBody,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.complete(
        db, review_id, _uid(token_payload),
        body.verify_claim_ids, body.verify_evidence_ids, request=request,
    )
    return APIResponse(success=True, data=serialize(review), message="Review completed")


@router.post("/{review_id}/archive", response_model=APIResponse)
def archive_review(
    review_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    review = ReviewService.archive(db, review_id, _uid(token_payload), request=request)
    return APIResponse(success=True, data=serialize(review), message="Review archived")


@router.post("/{review_id}/notify", response_model=APIResponse)
def notify_review_desk(
    review_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """(Re)send the review-desk notification email for a review.

    Best-effort: the response reports ``email_notification: {sent, reason}``
    honestly - unconfigured SMTP or a send failure never fails this call.
    """
    result = ReviewService.notify(db, review_id, _uid(token_payload))
    review = ReviewService.get(db, review_id, _uid(token_payload))
    return APIResponse(
        success=True,
        data={**serialize(review), "email_notification": result},
        message=(
            "Notification email sent to the review desk"
            if result["sent"]
            else f"Notification email not sent ({result['reason']})"
        ),
    )
