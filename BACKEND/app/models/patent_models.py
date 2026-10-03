"""
Patent screening models (Phase 6).

When a user screens a product version for patents, the system stores the
**identified candidate records** pinned to the exact version that was screened,
together with the technical features it extracted and compared.

Two deliberate design choices, both required by the master prompt:

* **Records are version-pinned.** A ``patent_records`` row always references the
  ``product_version_id`` it was identified for, so a later version cannot
  silently inherit (or overwrite) an earlier screening.
* **Demo data is labelled as demo.** Every record carries ``record_source``
  (``DEMO_CORPUS`` / ``LIVE_SOURCE``) and ``is_demo``. The platform has no live
  patent database, so in practice these rows come from a frozen, clearly
  labelled demonstration corpus - never a real patent lookup called a live
  search.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PatentRecord(Base):
    """
    A candidate patent record identified for a product version.

    This is *not* a claim about the real world. It is the platform's record that,
    during a screening of one version, a candidate publicly documented record was
    found whose technical features overlap (or do not) with the version's own
    features. ``relevance_label`` uses the master prompt's careful labels
    ("Potentially Relevant", "Possible Technical Overlap", "Further Review
    Recommended") and never asserts patentability, validity or infringement.
    """

    __tablename__ = "patent_records"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identity of the underlying source record (a demo id, or a real patent
    # number when a live source is configured).
    record_id = Column(String(120), nullable=False, index=True)
    patent_number = Column(String(120), nullable=True)
    title = Column(String(500), nullable=False)
    assignee = Column(String(255), nullable=True)
    jurisdiction = Column(String(100), nullable=True)
    publication_date = Column(String(40), nullable=True)
    abstract = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    source_passage = Column(Text, nullable=True)

    # Provenance of the record itself: DEMO_CORPUS | LIVE_SOURCE
    record_source = Column(String(40), nullable=False, default="DEMO_CORPUS", index=True)
    is_demo = Column(Boolean, nullable=False, default=True)
    corpus_version = Column(String(50), nullable=True)

    # Screening outcome for this record against the screened version
    relevance_label = Column(String(60), nullable=False, default="Further Review Recommended")
    similarity = Column(Float, nullable=False, default=0.0)  # 0.0 - 1.0 feature overlap
    similarity_band = Column(String(20), nullable=False, default="none")  # none|low|medium|high
    uncertainty = Column(Text, nullable=True)

    # Provenance firewall: machine-generated, never expert-verified by default.
    provenance = Column(String(50), nullable=False, default="AI_ANALYSIS")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    product_version = relationship("ProductVersion", back_populates="patent_records")
    features = relationship(
        "PatentFeature",
        back_populates="patent_record",
        cascade="all, delete-orphan",
        order_by="PatentFeature.id",
    )

    def __repr__(self) -> str:
        return f"<PatentRecord(id={self.id}, record_id={self.record_id!r}, label={self.relevance_label})>"


class PatentFeature(Base):
    """
    One technical feature of a candidate patent record.

    ``verdict`` records how that feature compares with the screened version:
    ``match`` (the version has the same feature), ``different`` (the version has
    a different value for the same feature type) or ``unknown`` (the version does
    not record this feature at all). A field-by-field comparison, never a
    patentability conclusion.
    """

    __tablename__ = "patent_features"
    __table_args__ = (
        UniqueConstraint("patent_record_id", "feature_type", "feature_value", name="uq_patent_feature"),
    )

    id = Column(Integer, primary_key=True, index=True)
    patent_record_id = Column(
        Integer,
        ForeignKey("patent_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    feature_type = Column(String(60), nullable=False, index=True)
    feature_value = Column(String(500), nullable=False)
    verdict = Column(String(20), nullable=False, default="unknown")  # match | different | unknown
    user_value = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    patent_record = relationship("PatentRecord", back_populates="features")

    def __repr__(self) -> str:
        return f"<PatentFeature(id={self.id}, type={self.feature_type!r}, verdict={self.verdict})>"
