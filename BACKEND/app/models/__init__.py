"""Models package."""
from app.models.models import User, Role, UserRole, AuditLog, RoleName
from app.models.product_models import Product, ProductVersion, ProductCategory
from app.models.ingredient_models import (
    Ingredient, Formulation, Claim, Evidence, TargetMarket,
    SourceType, ClaimType, EvidenceStatus, EvidenceType, VerificationStatus
)
from app.models.analysis_models import Analysis, AnalysisType, AnalysisStatus
from app.models.patent_models import PatentRecord, PatentFeature
from app.models.change_impact_models import ChangeImpact
from app.models.disclosure_models import Disclosure, DisclosureType
from app.models.report_models import Report, ReportType
from app.models.review_models import ExpertReview, ReviewComment, ReviewStatus
from app.models.rag_models import (
    SourceDocument, SourceChunk, ChatSession, ChatMessage,
    DocumentSourceType, DocumentStatus, MessageRole
)
# Knowledge graph (Stage 2) - additive export so ``Base.metadata`` sees the
# tables for create_all / alembic autogenerate. Importing only schema/entities
# keeps this free of builder/query side effects.
from app.graph.schema import GraphNode, GraphEdge, NodeType, Relation

__all__ = [
    # Auth models
    "User", "Role", "UserRole", "AuditLog", "RoleName",
    # Product models
    "Product", "ProductVersion", "ProductCategory",
    # Ingredient and related models
    "Ingredient", "Formulation", "Claim", "Evidence", "TargetMarket",
    "SourceType", "ClaimType", "EvidenceStatus", "EvidenceType", "VerificationStatus",
    # Analysis models
    "Analysis", "AnalysisType", "AnalysisStatus",
    # Patent screening models (Phase 6)
    "PatentRecord", "PatentFeature",
    # Change impact model (Phase 7)
    "ChangeImpact",
    # Disclosure model (Phase 8)
    "Disclosure",
    "DisclosureType",
    # Report model (Phase 8b)
    "Report",
    "ReportType",
    # Review models (Phase 9)
    "ExpertReview",
    "ReviewComment",
    "ReviewStatus",
    # RAG models
    "SourceDocument", "SourceChunk", "ChatSession", "ChatMessage",
    "DocumentSourceType", "DocumentStatus", "MessageRole",
    # Knowledge graph models (Stage 2)
    "GraphNode", "GraphEdge", "NodeType", "Relation",
]
