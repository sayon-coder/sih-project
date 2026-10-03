"""
Expert review models (Phase 9).

An expert review tracks human verification of one product version through the
state machine the master prompt requires:

  DRAFT -> AI_SCREENED -> REVIEW_REQUIRED -> EXPERT_REVIEW
      -> CORRECTION_REQUESTED -> RESUBMITTED -> REVIEWED -> ARCHIVED

Rows are append-only history: every transition is recorded by writing the new
status (plus who/when), never by rewriting the past. Comments are separate
rows so reviewer discussion is preserved.

AI-generated analysis stays distinguishable: only a completed expert review
may promote claims/evidence to EXPERT_VERIFIED, and that promotion is an
explicit, audited action on completion - never silent.
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ReviewStatus(str, enum.Enum):
    """Expert review workflow states."""

    DRAFT = "DRAFT"
    AI_SCREENED = "AI_SCREENED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXPERT_REVIEW = "EXPERT_REVIEW"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    REVIEWED = "REVIEWED"
    ARCHIVED = "ARCHIVED"


class ExpertReview(Base):
    """One expert review of a product version."""

    __tablename__ = "expert_reviews"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(SQLEnum(ReviewStatus), default=ReviewStatus.DRAFT, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    ai_screen_summary = Column(Text, nullable=True)

    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_expert_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", foreign_keys=[product_id])
    product_version = relationship("ProductVersion", foreign_keys=[product_version_id])
    requester = relationship("User", foreign_keys=[requested_by])
    assigned_expert = relationship("User", foreign_keys=[assigned_expert_id])
    comments = relationship(
        "ReviewComment", back_populates="review", cascade="all, delete-orphan",
        order_by="ReviewComment.created_at",
    )

    def __repr__(self) -> str:
        return f"<ExpertReview(id={self.id}, status={self.status})>"


class ReviewComment(Base):
    """One comment on an expert review (reviewer discussion, preserved)."""

    __tablename__ = "review_comments"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(
        Integer,
        ForeignKey("expert_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    review = relationship("ExpertReview", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])

    def __repr__(self) -> str:
        return f"<ReviewComment(id={self.id}, review_id={self.review_id})>"
