"""
Product router for IP-SAKTI Sahayak.
Handles product CRUD operations and versioning.

Every endpoint requires a valid access token and only exposes products the
caller owns (ADMIN users may access all products).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analysis, ProductVersion
from app.schemas.schemas import APIResponse
from app.schemas.product_schemas import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ProductVersionCreate,
    ProductVersionDetail,
    ProductVersionResponse,
    ProductVersionUpdate,
)
from app.services.product_service import ProductService
from app.utils import verify_token
from app.utils.authorization import get_accessible_product

router = APIRouter(prefix="/api/products", tags=["Products"])

# ============================================
# Product CRUD Endpoints
# ============================================


@router.post("", response_model=APIResponse, status_code=201)
def create_product(
    product_data: ProductCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Create a new product.

    Creates the product together with its initial version (version 1).
    """
    user_id = int(token_payload["sub"])
    product = ProductService.create_product(db, product_data, user_id, request)

    return APIResponse(
        success=True,
        data=ProductResponse.model_validate(product).model_dump(),
        message="Product created successfully",
    )


@router.get("", response_model=APIResponse)
def list_products(
    skip: int = 0,
    limit: int = 100,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    List products visible to the current user (own products; all products for ADMIN).
    """
    user_id = int(token_payload["sub"])
    products = ProductService.get_products(db, user_id=user_id, skip=skip, limit=limit)

    product_list = []
    for product in products:
        version_count = (
            db.query(ProductVersion)
            .filter(ProductVersion.product_id == product.id)
            .count()
        )
        product_list.append(
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "category": product.category,
                "current_version_id": product.current_version_id,
                "created_at": product.created_at,
                "version_count": version_count,
            }
        )

    return APIResponse(
        success=True,
        data=product_list,
        message=f"Found {len(product_list)} products",
    )


@router.get("/{product_id}", response_model=APIResponse)
def get_product(
    product_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get a specific product by ID."""
    user_id = int(token_payload["sub"])
    product = get_accessible_product(db, product_id, user_id)

    return APIResponse(
        success=True,
        data=ProductResponse.model_validate(product).model_dump(),
        message="Product retrieved successfully",
    )


@router.put("/{product_id}", response_model=APIResponse)
def update_product(
    product_id: int,
    product_data: ProductUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Update product metadata.

    To change ingredients/formulation/claims, create a new version instead so the
    previous version stays intact.
    """
    user_id = int(token_payload["sub"])
    product = ProductService.update_product(db, product_id, product_data, user_id, request)

    return APIResponse(
        success=True,
        data=ProductResponse.model_validate(product).model_dump(),
        message="Product updated successfully",
    )


@router.delete("/{product_id}", response_model=APIResponse)
def delete_product(
    product_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Soft delete a product (sets is_active = False)."""
    user_id = int(token_payload["sub"])
    ProductService.delete_product(db, product_id, user_id, request)

    return APIResponse(success=True, message="Product deleted successfully")


# ============================================
# Product Passport Endpoints
# ============================================


@router.get("/{product_id}/passport", response_model=APIResponse)
def get_product_passport(
    product_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Get the Product Passport for a product.

    The Product Passport is the persistent intelligence layer for a product:
    product metadata, the full current version (ingredients, formulation,
    claims, evidence, target markets), version count, and the latest completed
    analysis.
    """
    user_id = int(token_payload["sub"])
    product = get_accessible_product(db, product_id, user_id)

    version_count = (
        db.query(ProductVersion)
        .filter(ProductVersion.product_id == product.id)
        .count()
    )

    current_version = None
    latest_analysis = None

    if product.current_version_id:
        version = (
            db.query(ProductVersion)
            .filter(ProductVersion.id == product.current_version_id)
            .first()
        )
        if version:
            current_version = ProductVersionDetail.model_validate(version).model_dump()

            analysis = (
                db.query(Analysis)
                .filter(Analysis.product_version_id == version.id)
                .order_by(Analysis.created_at.desc())
                .first()
            )
            if analysis:
                latest_analysis = {
                    "id": analysis.id,
                    "type": analysis.analysis_type.value
                    if hasattr(analysis.analysis_type, "value")
                    else str(analysis.analysis_type),
                    "status": analysis.status.value
                    if hasattr(analysis.status, "value")
                    else str(analysis.status),
                    "summary": analysis.summary,
                    "created_at": analysis.created_at.isoformat()
                    if analysis.created_at
                    else None,
                }

    return APIResponse(
        success=True,
        data={
            "product": ProductResponse.model_validate(product).model_dump(),
            "current_version": current_version,
            "version_count": version_count,
            "latest_analysis": latest_analysis,
        },
        message="Product passport retrieved successfully",
    )


@router.put("/{product_id}/passport", response_model=APIResponse)
def update_product_passport(
    product_id: int,
    product_data: ProductUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Update the passport-level product metadata.

    Equivalent to ``PUT /api/products/{product_id}``; provided so clients that
    work from the passport screen do not need a second endpoint.
    """
    user_id = int(token_payload["sub"])
    product = ProductService.update_product(db, product_id, product_data, user_id, request)

    return APIResponse(
        success=True,
        data=ProductResponse.model_validate(product).model_dump(),
        message="Product passport updated successfully",
    )


# ============================================
# Product Version Endpoints
# ============================================


@router.get("/{product_id}/versions", response_model=APIResponse)
def list_product_versions(
    product_id: int,
    skip: int = 0,
    limit: int = 100,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List all versions of a product (newest first)."""
    user_id = int(token_payload["sub"])
    versions = ProductService.get_versions(db, product_id, user_id, skip, limit)

    version_list = [
        ProductVersionResponse.model_validate(version).model_dump() for version in versions
    ]

    return APIResponse(
        success=True,
        data=version_list,
        message=f"Found {len(version_list)} versions",
    )


@router.post("/{product_id}/versions", response_model=APIResponse, status_code=201)
def create_product_version(
    product_id: int,
    version_data: ProductVersionCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Create a new version of a product.

    The new version copies the current version's content by default, so it is a
    safe starting point for a change. Use ``start_empty`` to begin blank.
    """
    user_id = int(token_payload["sub"])
    version = ProductService.create_version(
        db=db,
        product_id=product_id,
        change_reason=version_data.change_reason,
        user_id=user_id,
        request=request,
        copy_from_version_id=version_data.copy_from_version_id,
        start_empty=version_data.start_empty,
    )

    return APIResponse(
        success=True,
        data=ProductVersionResponse.model_validate(version).model_dump(),
        message=f"Version {version.version_number} created successfully",
    )


@router.post(
    "/{product_id}/versions/{version_id}/clone",
    response_model=APIResponse,
    status_code=201,
)
def clone_product_version(
    product_id: int,
    version_id: int,
    version_data: ProductVersionUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Clone an existing version into a new version.

    Copies ingredients, formulation, claims, evidence and target markets. The
    source version is never modified.
    """
    user_id = int(token_payload["sub"])
    version = ProductService.create_version(
        db=db,
        product_id=product_id,
        change_reason=version_data.change_reason or f"Cloned from version {version_id}",
        user_id=user_id,
        request=request,
        copy_from_version_id=version_id,
    )

    return APIResponse(
        success=True,
        data=ProductVersionResponse.model_validate(version).model_dump(),
        message=f"Version {version.version_number} created by cloning version {version_id}",
    )


@router.get("/{product_id}/versions/{version_id}", response_model=APIResponse)
def get_product_version(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Get a specific version of a product.

    Returns the full version detail including ingredients, formulation, claims,
    evidence and target markets.
    """
    user_id = int(token_payload["sub"])
    get_accessible_product(db, product_id, user_id)
    version = ProductService.get_version(db, version_id, product_id)

    return APIResponse(
        success=True,
        data=ProductVersionDetail.model_validate(version).model_dump(),
        message="Version retrieved successfully",
    )


@router.put("/{product_id}/versions/{version_id}", response_model=APIResponse)
def update_product_version(
    product_id: int,
    version_id: int,
    version_data: ProductVersionUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Update version metadata.

    Only the change reason is editable here. Version content is immutable from
    this endpoint; ingredient/formulation/claim/evidence edits live under their
    own routes and refresh the version's snapshot hash.
    """
    user_id = int(token_payload["sub"])
    version = ProductService.update_version(
        db=db,
        product_id=product_id,
        version_id=version_id,
        change_reason=version_data.change_reason,
        user_id=user_id,
        request=request,
    )

    return APIResponse(
        success=True,
        data=ProductVersionResponse.model_validate(version).model_dump(),
        message="Version updated successfully",
    )
