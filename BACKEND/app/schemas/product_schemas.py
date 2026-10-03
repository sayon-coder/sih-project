"""
Product and ProductVersion schemas for API requests and responses.
"""
from typing import Optional, List, Any, Dict
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from app.models.product_models import ProductCategory
from app.models.ingredient_models import SourceType, ClaimType, EvidenceStatus, EvidenceType, VerificationStatus


# ============================================
# Product Schemas
# ============================================

class ProductBase(BaseModel):
    """Base product schema."""
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
    description: Optional[str] = Field(None, description="Product description")
    category: Optional[ProductCategory] = Field(None, description="Product category")


class ProductCreate(ProductBase):
    """Schema for creating a product."""
    pass


class ProductUpdate(BaseModel):
    """Schema for updating a product."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[ProductCategory] = None
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """Schema for product in responses."""
    id: int
    current_version_id: Optional[int] = None
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """Schema for product list with version count."""
    id: int
    name: str
    category: Optional[ProductCategory] = None
    current_version_id: Optional[int] = None
    created_at: datetime
    version_count: int = 0

    class Config:
        from_attributes = True


# ============================================
# Product Version Schemas
# ============================================

class ProductVersionBase(BaseModel):
    """Base product version schema."""
    change_reason: Optional[str] = Field(None, description="Reason for creating this version")


class ProductVersionCreate(ProductVersionBase):
    """
    Schema for creating a product version.

    By default the new version inherits a copy of the product's current version
    content. Use ``copy_from_version_id`` to branch from another version, or
    ``start_empty=True`` for a blank version.
    """
    copy_from_version_id: Optional[int] = Field(
        None, description="Version whose content should be copied into the new version"
    )
    start_empty: bool = Field(
        False, description="Create the new version without copying existing content"
    )


class ProductVersionUpdate(BaseModel):
    """Schema for updating version metadata (change reason only)."""
    change_reason: Optional[str] = Field(None, description="Reason for creating this version")


class ProductVersionResponse(ProductVersionBase):
    """Schema for product version in responses."""
    id: int
    product_id: int
    version_number: int
    snapshot_data: Optional[str] = None
    content_hash: Optional[str] = None
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProductVersionDetail(ProductVersionResponse):
    """Detailed product version with all related data."""
    ingredients: List["IngredientResponse"] = Field(default_factory=list)
    formulation: Optional["FormulationResponse"] = None
    claims: List["ClaimResponse"] = Field(default_factory=list)
    evidence: List["EvidenceResponse"] = Field(default_factory=list)
    target_markets: List["TargetMarketResponse"] = Field(default_factory=list)


# ============================================
# Ingredient Schemas
# ============================================

class IngredientBase(BaseModel):
    """Base ingredient schema."""
    common_name: str = Field(..., min_length=1, max_length=255)
    botanical_name: Optional[str] = Field(None, max_length=255)
    sanskrit_name: Optional[str] = Field(None, max_length=255)
    plant_part: Optional[str] = Field(None, max_length=100)
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = Field(None, max_length=20)
    preparation_method: Optional[str] = None
    source_type: Optional[SourceType] = SourceType.UNKNOWN
    source_location: Optional[str] = Field(None, max_length=255)
    source_documentation: Optional[str] = None


class IngredientCreate(IngredientBase):
    """Schema for creating an ingredient."""
    pass


class IngredientUpdate(BaseModel):
    """Schema for updating an ingredient."""
    common_name: Optional[str] = Field(None, min_length=1, max_length=255)
    botanical_name: Optional[str] = None
    sanskrit_name: Optional[str] = None
    plant_part: Optional[str] = None
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    preparation_method: Optional[str] = None
    source_type: Optional[SourceType] = None
    source_location: Optional[str] = None
    source_documentation: Optional[str] = None


class IngredientResponse(IngredientBase):
    """Schema for ingredient in responses."""
    id: int
    product_version_id: int
    provenance: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# Formulation Schemas
# ============================================

class FormulationBase(BaseModel):
    """Base formulation schema.

    Spec item 3: an empty string means "not provided" - it is stored as
    ``null`` so the analysis reports the field as missing instead of as an
    empty recorded value. Nothing is ever inferred.
    """
    process_description: Optional[str] = None
    extraction_method: Optional[str] = Field(None, max_length=100)
    solvent: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = None
    temperature_unit: Optional[str] = "C"
    pressure: Optional[float] = None
    pressure_unit: Optional[str] = None
    duration: Optional[float] = None
    duration_unit: Optional[str] = None
    concentration: Optional[float] = None
    other_parameters: Optional[str] = None

    @field_validator(
        "process_description",
        "extraction_method",
        "solvent",
        "temperature",
        "temperature_unit",
        "pressure",
        "pressure_unit",
        "duration",
        "duration_unit",
        "concentration",
        "other_parameters",
        mode="before",
    )
    @classmethod
    def _empty_is_not_provided(cls, value: Any) -> Any:
        """Coerce ``""`` (and whitespace-only strings) to ``None`` on input."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value


class FormulationCreate(FormulationBase):
    """Schema for creating a formulation."""
    pass


class FormulationUpdate(FormulationBase):
    """Schema for updating a formulation."""
    pass


class FormulationResponse(FormulationBase):
    """Schema for formulation in responses."""
    id: int
    product_version_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================
# Claim Schemas
# ============================================

class ClaimBase(BaseModel):
    """Base claim schema."""
    claim_text: str = Field(..., min_length=1)
    claim_type: Optional[ClaimType] = None


class ClaimCreate(ClaimBase):
    """
    Schema for creating a claim.

    ``evidence_status`` is accepted but restricted to the user-settable values
    (``user_provided`` / ``needs_evidence``); the service rejects anything that
    asserts a claim is already supported. ``provenance`` is never client-supplied.
    """
    evidence_status: Optional[EvidenceStatus] = None
    evidence_notes: Optional[str] = None


class ClaimUpdate(BaseModel):
    """Schema for updating a claim."""
    claim_text: Optional[str] = Field(None, min_length=1)
    claim_type: Optional[ClaimType] = None
    evidence_notes: Optional[str] = None


class ClaimResponse(ClaimBase):
    """Schema for claim in responses."""
    id: int
    product_version_id: int
    evidence_status: EvidenceStatus
    evidence_notes: Optional[str] = None
    risk_level: Optional[str] = None
    review_status: str
    provenance: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================
# Evidence Schemas
# ============================================

class EvidenceBase(BaseModel):
    """Base evidence schema."""
    title: str = Field(..., min_length=1, max_length=500)
    evidence_type: Optional[EvidenceType] = None
    file_path: Optional[str] = None
    source_url: Optional[str] = None
    doi: Optional[str] = Field(None, max_length=100)
    publication_date: Optional[date] = None
    language: Optional[str] = Field(None, max_length=10)
    authors: Optional[str] = None


class EvidenceCreate(EvidenceBase):
    """Schema for creating evidence."""
    pass


class EvidenceUpdate(BaseModel):
    """Schema for updating evidence."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    evidence_type: Optional[EvidenceType] = None
    file_path: Optional[str] = None
    source_url: Optional[str] = None
    doi: Optional[str] = None
    publication_date: Optional[date] = None
    language: Optional[str] = None
    authors: Optional[str] = None
    verification_status: Optional[VerificationStatus] = None


class EvidenceResponse(EvidenceBase):
    """Schema for evidence in responses."""
    id: int
    product_version_id: int
    verification_status: VerificationStatus
    document_hash: Optional[str] = None
    provenance: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# Target Market Schemas
# ============================================

class TargetMarketBase(BaseModel):
    """Base target market schema."""
    country: str = Field(..., min_length=1, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    regulatory_status: Optional[str] = None
    notes: Optional[str] = None


class TargetMarketCreate(TargetMarketBase):
    """Schema for creating a target market."""
    pass


class TargetMarketUpdate(BaseModel):
    """Schema for updating a target market."""
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    region: Optional[str] = None
    regulatory_status: Optional[str] = None
    notes: Optional[str] = None


class TargetMarketResponse(TargetMarketBase):
    """Schema for target market in responses."""
    id: int
    product_version_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# Product Passport Schema
# ============================================

class ProductPassport(BaseModel):
    """
    Complete Product Passport - the intelligence layer for a product.
    Combines product info, version details, and all related data.
    """
    product: ProductResponse
    current_version: Optional[ProductVersionDetail] = None
    version_count: int = 0
    latest_analysis: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


# Update forward references
ProductVersionDetail.model_rebuild()
