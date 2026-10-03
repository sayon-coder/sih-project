"""
Product and ProductVersion models for IP-SAKTI Sahayak.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from app.database import Base


# ============================================
# Product Category Enum
# ============================================

class ProductCategory(str, enum.Enum):
    """
    Product classification categories aligned to the SIH problem statement.

    The six categories named in the IP-SAKTI Sahayak problem statement are:
      1. classical_traditional — formulation drawn from a First-Schedule text (Sec 3(p) bar; TKDL)
      2. proprietary_ayurvedic  — patent-or-proprietary medicine
      3. new_drug               — new/non-classical drug requiring safety & effectiveness proof
      4. phytopharmaceutical    — phytopharmaceutical (Drugs & Cosmetics Act, 2015 rules)
      5. ayurveda_aahara        — Ayurveda-Aahar / nutraceutical (FSSAI Ayurveda-Aahar regulations)
      6. possible_cosmetic      — cosmetic (Cosmetics Rules 2020)
    """
    CLASSICAL_TRADITIONAL = "classical_traditional"
    PROPRIETARY_AYURVEDIC = "proprietary_ayurvedic"
    NEW_DRUG = "new_drug"                        # renamed from possible_medicinal
    PHYTOPHARMACEUTICAL = "phytopharmaceutical"  # ← explicitly required by SIH
    AYURVEDA_AAHARA = "ayurveda_aahara"
    POSSIBLE_COSMETIC = "possible_cosmetic"
    # Legacy / backward-compatible aliases kept so existing DB rows are not broken
    POSSIBLE_MEDICINAL = "possible_medicinal"    # maps to new_drug concept
    RESEARCH_PRODUCT = "research_product"
    INDUSTRIAL_PRODUCT = "industrial_product"


# ============================================
# Product Model
# ============================================

class Product(Base):
    """
    Product model - the main entity for Ayurvedic products.
    Each product has multiple versions tracking its evolution.
    """
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(SQLEnum(ProductCategory), nullable=True, index=True)

    # Current active version
    current_version_id = Column(Integer, ForeignKey("product_versions.id"), nullable=True)

    # Ownership and audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    versions = relationship("ProductVersion", back_populates="product", foreign_keys="ProductVersion.product_id", cascade="all, delete-orphan")
    created_by_user = relationship("User", foreign_keys=[created_by])
    change_impacts = relationship(
        "ChangeImpact",
        back_populates="product",
        cascade="all, delete-orphan",
        foreign_keys="ChangeImpact.product_id",
    )

    def __repr__(self):
        return f"<Product(id={self.id}, name={self.name})>"


# ============================================
# Product Version Model
# ============================================

class ProductVersion(Base):
    """
    Product Version model - immutable snapshots of product state.
    Each version captures the complete state of a product at a point in time.
    """
    __tablename__ = "product_versions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)

    # Version metadata
    version_number = Column(Integer, nullable=False, default=1)
    change_reason = Column(Text, nullable=True)

    # Snapshot data (JSON-serializable dictionary)
    snapshot_data = Column(Text, nullable=True)  # JSON string of complete product state

    # Content hash for integrity
    content_hash = Column(String(64), nullable=True)  # SHA-256 hash

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    product = relationship("Product", back_populates="versions", foreign_keys=[product_id])
    created_by_user = relationship("User", foreign_keys=[created_by])
    ingredients = relationship("Ingredient", back_populates="product_version", cascade="all, delete-orphan")
    formulation = relationship("Formulation", back_populates="product_version", uselist=False, cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="product_version", cascade="all, delete-orphan")
    evidence = relationship("Evidence", back_populates="product_version", cascade="all, delete-orphan")
    target_markets = relationship("TargetMarket", back_populates="product_version", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="product_version", cascade="all, delete-orphan")
    patent_records = relationship("PatentRecord", back_populates="product_version", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProductVersion(id={self.id}, product_id={self.product_id}, version={self.version_number})>"
