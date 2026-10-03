"""
Version content router (Phase 3).

Exposes CRUD for the content that lives under a product version: ingredients,
formulation, claims, evidence and target markets.

Every route is nested under ``/api/products/{product_id}/versions/{version_id}``
so a request can only reach content through a product the caller owns. Each
successful write refreshes the version's snapshot and content hash.
"""
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.product_schemas import (
    ClaimCreate,
    ClaimResponse,
    ClaimUpdate,
    EvidenceCreate,
    EvidenceResponse,
    EvidenceUpdate,
    FormulationResponse,
    FormulationUpdate,
    IngredientCreate,
    IngredientResponse,
    IngredientUpdate,
    TargetMarketCreate,
    TargetMarketResponse,
    TargetMarketUpdate,
)
from app.schemas.schemas import APIResponse
from app.services.version_content_service import VersionContentService
from app.utils import verify_token

router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Version Content"],
)


def _payload(token_payload: dict) -> int:
    """Extract the authenticated user id from the verified token payload."""
    return int(token_payload["sub"])


# ============================================
# Ingredients
# ============================================


@router.get("/ingredients", response_model=APIResponse)
def list_ingredients(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List all ingredients in this version."""
    ingredients = VersionContentService.list_ingredients(
        db, product_id, version_id, _payload(token_payload)
    )
    return APIResponse(
        success=True,
        data=[IngredientResponse.model_validate(item).model_dump() for item in ingredients],
        message=f"Found {len(ingredients)} ingredients",
    )


@router.post("/ingredients", response_model=APIResponse, status_code=201)
def create_ingredient(
    product_id: int,
    version_id: int,
    ingredient_data: IngredientCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Add an ingredient to this version.

    The ingredient is recorded as ``USER_PROVIDED``; provenance is assigned by
    the server and cannot be set in the request body.
    """
    ingredient = VersionContentService.create_ingredient(
        db,
        product_id,
        version_id,
        ingredient_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=IngredientResponse.model_validate(ingredient).model_dump(),
        message="Ingredient added successfully",
    )


@router.put("/ingredients/{ingredient_id}", response_model=APIResponse)
def update_ingredient(
    product_id: int,
    version_id: int,
    ingredient_id: int,
    ingredient_data: IngredientUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Update an ingredient.

    A ``user_provided``/``public_source``/``ai_analysis`` record is editable;
    an ``EXPERT_VERIFIED`` ingredient returns 409.
    """
    ingredient = VersionContentService.update_ingredient(
        db,
        product_id,
        version_id,
        ingredient_id,
        ingredient_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=IngredientResponse.model_validate(ingredient).model_dump(),
        message="Ingredient updated successfully",
    )


@router.delete("/ingredients/{ingredient_id}", response_model=APIResponse)
def delete_ingredient(
    product_id: int,
    version_id: int,
    ingredient_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Remove an ingredient from this version."""
    VersionContentService.delete_ingredient(
        db, product_id, version_id, ingredient_id, _payload(token_payload), request
    )
    return APIResponse(success=True, message="Ingredient deleted successfully")


# ============================================
# Formulation
# ============================================


@router.get("/formulation", response_model=APIResponse)
def get_formulation(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get this version's formulation (``data`` is null when not yet entered)."""
    formulation = VersionContentService.get_formulation(
        db, product_id, version_id, _payload(token_payload)
    )
    data: Any = (
        FormulationResponse.model_validate(formulation).model_dump()
        if formulation is not None
        else None
    )
    return APIResponse(success=True, data=data, message="Formulation retrieved successfully")


@router.put("/formulation", response_model=APIResponse)
def upsert_formulation(
    product_id: int,
    version_id: int,
    formulation_data: FormulationUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create or update this version's formulation (one per version)."""
    formulation = VersionContentService.upsert_formulation(
        db,
        product_id,
        version_id,
        formulation_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=FormulationResponse.model_validate(formulation).model_dump(),
        message="Formulation saved successfully",
    )


# ============================================
# Claims
# ============================================


@router.get("/claims", response_model=APIResponse)
def list_claims(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List all claims for this version."""
    claims = VersionContentService.list_claims(
        db, product_id, version_id, _payload(token_payload)
    )
    return APIResponse(
        success=True,
        data=[ClaimResponse.model_validate(item).model_dump() for item in claims],
        message=f"Found {len(claims)} claims",
    )


@router.post("/claims", response_model=APIResponse, status_code=201)
def create_claim(
    product_id: int,
    version_id: int,
    claim_data: ClaimCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Record a product claim.

    Claim-to-evidence firewall: the claim is stored as ``USER_PROVIDED`` with
    ``evidence_status`` limited to ``user_provided`` / ``needs_evidence``. A user
    cannot declare their own claim ``supported`` or ``expert_verified``.
    """
    claim = VersionContentService.create_claim(
        db, product_id, version_id, claim_data, _payload(token_payload), request
    )
    return APIResponse(
        success=True,
        data=ClaimResponse.model_validate(claim).model_dump(),
        message="Claim created successfully",
    )


@router.put("/claims/{claim_id}", response_model=APIResponse)
def update_claim(
    product_id: int,
    version_id: int,
    claim_id: int,
    claim_data: ClaimUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Update a claim's text, type or notes."""
    claim = VersionContentService.update_claim(
        db,
        product_id,
        version_id,
        claim_id,
        claim_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=ClaimResponse.model_validate(claim).model_dump(),
        message="Claim updated successfully",
    )


@router.delete("/claims/{claim_id}", response_model=APIResponse)
def delete_claim(
    product_id: int,
    version_id: int,
    claim_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a claim from this version."""
    VersionContentService.delete_claim(
        db, product_id, version_id, claim_id, _payload(token_payload), request
    )
    return APIResponse(success=True, message="Claim deleted successfully")


# ============================================
# Evidence
# ============================================


@router.get("/evidence", response_model=APIResponse)
def list_evidence(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List evidence documents attached to this version."""
    evidence = VersionContentService.list_evidence(
        db, product_id, version_id, _payload(token_payload)
    )
    return APIResponse(
        success=True,
        data=[EvidenceResponse.model_validate(item).model_dump() for item in evidence],
        message=f"Found {len(evidence)} evidence documents",
    )


@router.post("/evidence", response_model=APIResponse, status_code=201)
def create_evidence(
    product_id: int,
    version_id: int,
    evidence_data: EvidenceCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Attach an evidence document.

    Recorded as ``USER_PROVIDED`` with ``verification_status = pending``: citing
    a source does not verify it.
    """
    evidence = VersionContentService.create_evidence(
        db, product_id, version_id, evidence_data, _payload(token_payload), request
    )
    return APIResponse(
        success=True,
        data=EvidenceResponse.model_validate(evidence).model_dump(),
        message="Evidence added successfully",
    )


@router.get("/evidence/{evidence_id}", response_model=APIResponse)
def get_evidence(
    product_id: int,
    version_id: int,
    evidence_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get a single evidence document."""
    evidence = VersionContentService.get_evidence(
        db, product_id, version_id, evidence_id, _payload(token_payload)
    )
    return APIResponse(
        success=True,
        data=EvidenceResponse.model_validate(evidence).model_dump(),
        message="Evidence retrieved successfully",
    )


@router.put("/evidence/{evidence_id}", response_model=APIResponse)
def update_evidence(
    product_id: int,
    version_id: int,
    evidence_id: int,
    evidence_data: EvidenceUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Update evidence metadata.

    A user may reset ``verification_status`` to ``pending`` but cannot promote
    evidence to ``verified``; that is the expert workflow's job.
    """
    evidence = VersionContentService.update_evidence(
        db,
        product_id,
        version_id,
        evidence_id,
        evidence_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=EvidenceResponse.model_validate(evidence).model_dump(),
        message="Evidence updated successfully",
    )


# ============================================
# Target markets
# ============================================


@router.get("/target-markets", response_model=APIResponse)
def list_target_markets(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the intended markets for this version."""
    markets = VersionContentService.list_target_markets(
        db, product_id, version_id, _payload(token_payload)
    )
    return APIResponse(
        success=True,
        data=[TargetMarketResponse.model_validate(item).model_dump() for item in markets],
        message=f"Found {len(markets)} target markets",
    )


@router.post("/target-markets", response_model=APIResponse, status_code=201)
def create_target_market(
    product_id: int,
    version_id: int,
    market_data: TargetMarketCreate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Add an intended market to this version."""
    market = VersionContentService.create_target_market(
        db, product_id, version_id, market_data, _payload(token_payload), request
    )
    return APIResponse(
        success=True,
        data=TargetMarketResponse.model_validate(market).model_dump(),
        message="Target market added successfully",
    )


@router.put("/target-markets/{market_id}", response_model=APIResponse)
def update_target_market(
    product_id: int,
    version_id: int,
    market_id: int,
    market_data: TargetMarketUpdate,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Update a target market entry."""
    market = VersionContentService.update_target_market(
        db,
        product_id,
        version_id,
        market_id,
        market_data,
        _payload(token_payload),
        request,
    )
    return APIResponse(
        success=True,
        data=TargetMarketResponse.model_validate(market).model_dump(),
        message="Target market updated successfully",
    )


@router.delete("/target-markets/{market_id}", response_model=APIResponse)
def delete_target_market(
    product_id: int,
    version_id: int,
    market_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Remove a target market from this version."""
    VersionContentService.delete_target_market(
        db, product_id, version_id, market_id, _payload(token_payload), request
    )
    return APIResponse(success=True, message="Target market deleted successfully")
