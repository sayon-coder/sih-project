"""
Disclosure models (Phase 8).

A disclosure records a public-disclosure event (conference, publication,
website, investor disclosure, advertising, commercial launch, other) against
one product version. Rows are immutable once written - correcting an event
means recording a new row, so history is never rewritten.

Each row carries:
- ``record_hash``: SHA-256 over the canonical disclosure payload, proving
  what was recorded;
- ``verification_id``: short unique id used by the QR verification endpoint.

The invention-disclosure disclaimer is a shared constant so every response
and (later) every PDF carries identical wording.
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean,
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

INVENTION_DISCLOSURE_DISCLAIMER = (
    "This record preserves the information entered by the declarant and the time "
    "at which it was recorded. It is not a patent application. It does not "
    "establish patent priority. It does not create any patent right. It does not "
    "guarantee acceptance as prior art or legal evidence by any authority. For "
    "patent priority, consult a registered patent agent regarding a formal "
    "provisional specification filing with IP India."
)

PUBLIC_DISCLOSURE_DISCLAIMER = (
    "Public-disclosure review is recommended before presenting or publishing the "
    "technical method. Consult a registered patent professional about appropriate "
    "filing strategy. A timestamped app record does not create patent priority or "
    "guarantee legal protection."
)


class DisclosureType(str, enum.Enum):
    """Tracked public-disclosure event types (master prompt section 7)."""

    CONFERENCE_PRESENTATION = "conference_presentation"
    PUBLICATION = "publication"
    WEBSITE = "website"
    INVESTOR_DISCLOSURE = "investor_disclosure"
    ADVERTISING = "advertising"
    COMMERCIAL_LAUNCH = "commercial_launch"
    OTHER = "other"


class Disclosure(Base):
    """One recorded public-disclosure event for a product version."""

    __tablename__ = "disclosures"

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

    disclosure_type = Column(SQLEnum(DisclosureType), nullable=False, index=True)
    description = Column(Text, nullable=False)
    venue_or_channel = Column(String(500), nullable=True)
    disclosure_date = Column(String(40), nullable=True)

    # Declarant (mirrors master prompt section 25)
    declarant_name = Column(String(255), nullable=True)
    institution = Column(String(500), nullable=True)

    # Integrity: SHA-256 over the canonical payload + short QR verification id
    record_hash = Column(String(64), nullable=False, index=True)
    verification_id = Column(String(32), nullable=False, unique=True, index=True)
    is_demo = Column(Boolean, nullable=False, server_default="false")

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    product = relationship("Product", foreign_keys=[product_id])
    product_version = relationship("ProductVersion", foreign_keys=[product_version_id])
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<Disclosure(id={self.id}, product_id={self.product_id}, "
            f"version_id={self.product_version_id}, type={self.disclosure_type})>"
        )
