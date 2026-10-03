"""
Change-impact model (Phase 7).

The formulation change-impact simulator compares two versions of a product and
stores one ``change_impacts`` row per run, pinned to *both* versions it compared.

Why a dedicated table rather than the ``analyses`` table: an impact run is
inherently about a **pair** of versions, not one. Keeping it separate means the
analysistype enum stays about single-version screens, and a run can never be
mistaken for an analysis of one version. Like every other run type, the row is
immutable once written - re-running the comparison writes a new row, so history
is never rewritten.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.analysis_models import AnalysisStatus


class ChangeImpact(Base):
    """One change-impact comparison of two versions of the same product."""

    __tablename__ = "change_impacts"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    new_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(
        SQLEnum(AnalysisStatus),
        default=AnalysisStatus.COMPLETED,
        nullable=False,
        index=True,
    )

    # Results (JSON-serializable)
    results = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    review_questions = Column(Text, nullable=True)  # JSON array
    warnings = Column(Text, nullable=True)          # JSON array

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships. Two foreign keys point at product_versions, so each side is
    # declared explicitly rather than left to inference.
    product = relationship("Product", back_populates="change_impacts")
    old_version = relationship("ProductVersion", foreign_keys=[old_version_id])
    new_version = relationship("ProductVersion", foreign_keys=[new_version_id])
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<ChangeImpact(id={self.id}, product_id={self.product_id}, "
            f"{self.old_version_id}->{self.new_version_id})>"
        )
