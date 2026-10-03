"""
Ingredient, Formulation, Claim, Evidence, and TargetMarket models.
These are linked to ProductVersion for version tracking.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, date
import enum
from app.database import Base


# ============================================
# Ingredient Model
# ============================================

class SourceType(str, enum.Enum):
    """Source type for ingredients."""
    CULTIVATED = "cultivated"
    WILD = "wild"
    UNKNOWN = "unknown"


class Ingredient(Base):
    """
    Ingredient model for Ayurvedic product ingredients.
    Tracks botanical information, sourcing, and preparation.
    """
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Ingredient identification
    common_name = Column(String(255), nullable=False)
    botanical_name = Column(String(255), nullable=True, index=True)
    sanskrit_name = Column(String(255), nullable=True)
    plant_part = Column(String(100), nullable=True)  # root, leaf, bark, etc.

    # Quantity and preparation
    quantity = Column(Numeric(10, 3), nullable=True)  # Amount
    quantity_unit = Column(String(20), nullable=True)  # mg, g, ml, etc.
    preparation_method = Column(Text, nullable=True)  # powder, extract, etc.

    # Sourcing information
    source_type = Column(SQLEnum(SourceType), nullable=True, default=SourceType.UNKNOWN)
    source_location = Column(String(255), nullable=True)  # Geographic origin
    source_documentation = Column(Text, nullable=True)  # Reference to source docs

    # Provenance
    provenance = Column(String(50), default="USER_PROVIDED", nullable=False)  # USER_PROVIDED, AI_ANALYSIS, EXPERT_VERIFIED

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    product_version = relationship("ProductVersion", back_populates="ingredients")

    def __repr__(self):
        return f"<Ingredient(id={self.id}, common_name={self.common_name})>"


# ============================================
# Formulation Model
# ============================================

class Formulation(Base):
    """
    Formulation model for Ayurvedic product preparation process.
    Tracks extraction methods, processing parameters, and techniques.
    """
    __tablename__ = "formulations"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Process description
    process_description = Column(Text, nullable=True)

    # Extraction details
    extraction_method = Column(String(100), nullable=True)  # cold-press, solvent, etc.
    solvent = Column(String(100), nullable=True)  # water, ethanol, oil, etc.

    # Processing parameters
    temperature = Column(Numeric(10, 2), nullable=True)  # Temperature in Celsius
    temperature_unit = Column(String(10), default="C")
    pressure = Column(Numeric(10, 2), nullable=True)  # Pressure
    pressure_unit = Column(String(20), nullable=True)
    duration = Column(Numeric(10, 2), nullable=True)  # Processing duration
    duration_unit = Column(String(20), nullable=True)  # hours, days, etc.

    # Additional parameters
    concentration = Column(Numeric(10, 2), nullable=True)  # Concentration ratio
    other_parameters = Column(Text, nullable=True)  # JSON for additional params

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    product_version = relationship("ProductVersion", back_populates="formulation")

    def __repr__(self):
        return f"<Formulation(id={self.id}, extraction_method={self.extraction_method})>"


# ============================================
# Claim Model
# ============================================

class ClaimType(str, enum.Enum):
    """Types of product claims."""
    WELLNESS = "wellness"
    THERAPEUTIC = "therapeutic"
    NUTRITIONAL = "nutritional"
    COSMETIC = "cosmetic"
    STRUCTURE_FUNCTION = "structure_function"
    TRADITIONAL_USE = "traditional_use"


class EvidenceStatus(str, enum.Enum):
    """Evidence status for claims."""
    USER_PROVIDED = "user_provided"
    NEEDS_EVIDENCE = "needs_evidence"
    PARTIALLY_SUPPORTED = "partially_supported"
    SUPPORTED = "supported"
    EXPERT_VERIFIED = "expert_verified"


class Claim(Base):
    """
    Claim model for product claims and their evidence status.
    Tracks what the product claims to do and the evidence supporting it.
    """
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Claim content
    claim_text = Column(Text, nullable=False)
    claim_type = Column(SQLEnum(ClaimType), nullable=True, index=True)

    # Evidence tracking
    evidence_status = Column(SQLEnum(EvidenceStatus), default=EvidenceStatus.USER_PROVIDED, nullable=False, index=True)
    evidence_notes = Column(Text, nullable=True)

    # Risk assessment
    risk_level = Column(String(20), nullable=True)  # low, medium, high
    review_status = Column(String(50), default="pending", nullable=False)  # pending, reviewed, rejected

    # Provenance
    provenance = Column(String(50), default="USER_PROVIDED", nullable=False)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    product_version = relationship("ProductVersion", back_populates="claims")

    def __repr__(self):
        return f"<Claim(id={self.id}, claim_type={self.claim_type})>"


# ============================================
# Evidence Model
# ============================================

class EvidenceType(str, enum.Enum):
    """Types of evidence."""
    SCIENTIFIC_PAPER = "scientific_paper"
    CLINICAL_TRIAL = "clinical_trial"
    TRADITIONAL_TEXT = "traditional_text"
    PHARMACOPOEIA = "pharmacopoeia"
    REGULATORY_DOCUMENT = "regulatory_document"
    OTHER = "other"


class VerificationStatus(str, enum.Enum):
    """Verification status of evidence."""
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Evidence(Base):
    """
    Evidence model for supporting documents and references.
    Links to claims and tracks verification status.
    """
    __tablename__ = "evidence_documents"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Document identification
    title = Column(String(500), nullable=False)
    evidence_type = Column(SQLEnum(EvidenceType), nullable=True, index=True)

    # Document location
    file_path = Column(String(1000), nullable=True)  # Local file path
    source_url = Column(String(1000), nullable=True)  # External URL
    doi = Column(String(100), nullable=True)  # DOI for papers

    # Metadata
    publication_date = Column(Date, nullable=True)
    language = Column(String(10), nullable=True)
    authors = Column(Text, nullable=True)

    # Verification
    verification_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    document_hash = Column(String(64), nullable=True)  # SHA-256 hash for integrity

    # Provenance
    provenance = Column(String(50), default="USER_PROVIDED", nullable=False)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    product_version = relationship("ProductVersion", back_populates="evidence")

    def __repr__(self):
        return f"<Evidence(id={self.id}, title={self.title[:50]})>"


# ============================================
# Target Market Model
# ============================================

class TargetMarket(Base):
    """
    Target Market model for tracking intended markets.
    Different markets have different regulatory requirements.
    """
    __tablename__ = "target_markets"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Market identification
    country = Column(String(100), nullable=False, index=True)
    region = Column(String(100), nullable=True)

    # Regulatory status
    regulatory_status = Column(String(50), nullable=True)  # planned, submitted, approved, rejected

    # Notes
    notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    product_version = relationship("ProductVersion", back_populates="target_markets")

    def __repr__(self):
        return f"<TargetMarket(id={self.id}, country={self.country})>"
