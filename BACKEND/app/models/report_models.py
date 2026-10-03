"""
Report models (Phase 8b).

A report row pins one generated PDF to the product version it describes.
The PDF bytes live on disk under ``data/reports/``; the row stores the
SHA-256 ``content_hash`` so any download can be integrity-checked, plus a
unique ``verification_id`` used by the public verification endpoint (and the
QR code printed in each PDF).
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


class ReportType(str, enum.Enum):
    """The three report kinds the master prompt requires."""

    IP_BRIEF = "ip_brief"
    DISCLOSURE_RECORD = "disclosure_record"
    EXPERT_HANDOFF = "expert_handoff"


class Report(Base):
    """One generated PDF report for a product version."""

    __tablename__ = "reports"

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

    report_type = Column(SQLEnum(ReportType), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    file_size = Column(Integer, nullable=False, default=0)
    verification_id = Column(String(32), nullable=False, unique=True, index=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    product = relationship("Product", foreign_keys=[product_id])
    product_version = relationship("ProductVersion", foreign_keys=[product_version_id])
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<Report(id={self.id}, type={self.report_type}, "
            f"version_id={self.product_version_id})>"
        )
