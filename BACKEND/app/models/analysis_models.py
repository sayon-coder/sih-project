"""
Analysis model for storing product analysis results.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from app.database import Base


# ============================================
# Analysis Type Enum
# ============================================

class AnalysisType(str, enum.Enum):
    """Types of analysis."""
    PRODUCT_CLASSIFICATION = "product_classification"
    IP_ROUTE_MAP = "ip_route_map"
    PATENT_SCREENING = "patent_screening"
    BIODIVERSITY_SCREENING = "biodiversity_screening"
    TK_SCREENING = "tk_screening"
    PUBLIC_DISCLOSURE_REVIEW = "public_disclosure_review"
    COMPREHENSIVE = "comprehensive"
    CLAIM_ANALYSIS = "claim_analysis"


class AnalysisStatus(str, enum.Enum):
    """Analysis status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================
# Analysis Model
# ============================================

class Analysis(Base):
    """
    Analysis model for storing product analysis results.
    Each analysis is linked to a specific product version.
    """
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    product_version_id = Column(Integer, ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Analysis metadata
    analysis_type = Column(SQLEnum(AnalysisType), nullable=False, index=True)
    status = Column(SQLEnum(AnalysisStatus), default=AnalysisStatus.PENDING, nullable=False, index=True)

    # Results (JSON-serializable)
    results = Column(Text, nullable=True)  # JSON string of analysis results

    # Summary
    summary = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)  # JSON array of recommendations

    # Warnings and flags
    warnings = Column(Text, nullable=True)  # JSON array of warnings
    flags = Column(Text, nullable=True)  # JSON array of flags

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    product_version = relationship("ProductVersion", back_populates="analyses")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<Analysis(id={self.id}, type={self.analysis_type}, status={self.status})>"
