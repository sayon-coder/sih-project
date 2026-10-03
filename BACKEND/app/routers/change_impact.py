"""
Change-impact router (Phase 7).

  POST /api/products/{product_id}/change-impact          compare two versions
  GET  /api/products/{product_id}/change-impact          list recorded runs
  GET  /api/products/{product_id}/change-impact/{id}     one recorded run

Every route requires ownership of the product (ADMIN bypasses), both versions
must belong to that product, and each run is advisory and pinned to the two
versions it compared.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.schemas import APIResponse
from app.services.change_impact_service import ChangeImpactService
from app.utils import verify_token

router = APIRouter(prefix="/api/products/{product_id}", tags=["Change Impact"])


class ChangeImpactRequest(BaseModel):
    """The two versions to compare."""

    old_version_id: int
    new_version_id: int


def _payload(token_payload: dict) -> int:
    """Extract the authenticated user id from the verified token payload."""
    return int(token_payload["sub"])


@router.post("/change-impact", response_model=APIResponse)
def create_change_impact(
    product_id: int,
    body: ChangeImpactRequest,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Compare two versions of this product and return the meaningful differences.

    The report is advisory: it lists differences between the two versions, ranks
    their significance and raises review questions. It never edits either version
    and never states a legal, patent or regulatory conclusion.
    """
    impact = ChangeImpactService.run(
        db,
        product_id,
        body.old_version_id,
        body.new_version_id,
        _payload(token_payload),
        request=request,
    )
    return APIResponse(
        success=True,
        data=ChangeImpactService.serialize(impact),
        message="Change-impact analysis completed",
    )


@router.get("/change-impact", response_model=APIResponse)
def list_change_impacts(
    product_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List recorded change-impact runs for this product, newest first."""
    impacts = ChangeImpactService.list(db, product_id, _payload(token_payload))
    return APIResponse(
        success=True,
        data=[ChangeImpactService.serialize(i) for i in impacts],
        message=f"Found {len(impacts)} change-impact run(s)",
    )


@router.get("/change-impact/{impact_id}", response_model=APIResponse)
def get_change_impact(
    product_id: int,
    impact_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Fetch one recorded change-impact run."""
    impact = ChangeImpactService.get(db, product_id, impact_id, _payload(token_payload))
    return APIResponse(success=True, data=ChangeImpactService.serialize(impact))
