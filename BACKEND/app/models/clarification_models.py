"""
Clarification models - the interactive classification loop.

The problem statement requires the assistant to *"ask the minimum
clarifying questions"* to classify a formulation. Classification gaps are
deterministic (see ``app.services.clarification_service``); the user's
answers are stored here, one row per (version, question), so the loop is
multi-turn: ask -> answer is recorded -> the gap list shrinks -> re-run
analysis.

Answers are advisory notes pinned to the version. Recording an answer
never edits version content (ingredients, formulation, claims, evidence,
markets) - the user records facts in the Product Passport editors; the
answer only documents what was supplied, for the audit trail.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ClarificationAnswer(Base):
    """One answered clarifying question on one product version."""

    __tablename__ = "clarification_answers"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Stable machine key, e.g. "dosage_form" (see QUESTION_CATALOG).
    question_key = Column(String(100), nullable=False, index=True)
    # The exact question text the user saw (kept: wording may evolve).
    question_text = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    answered_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ClarificationAnswer(id={self.id}, "
            f"version_id={self.product_version_id}, key={self.question_key!r})>"
        )
