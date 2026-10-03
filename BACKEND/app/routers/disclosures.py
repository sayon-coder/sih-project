"""
Disclosure router (Phase 8a).

Version-scoped routes (ownership enforced through the product):

  GET  /api/products/{product_id}/versions/{version_id}/disclosures
  POST /api/products/{product_id}/versions/{version_id}/disclosures
  POST /api/products/{product_id}/versions/{version_id}/disclosure-review

Global routes:

  POST /api/disclosures                        create (product_id + version_id in body)
  GET  /api/disclosures/{disclosure_id}        one record (owner only)
  GET  /api/disclosures/{disclosure_id}/verify public verification payload (no auth)

Every mutating or advisory response is review-oriented and carries the
mandatory disclaimers. Nothing here states a legal conclusion.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.disclosure_models import DisclosureType
from app.schemas.schemas import APIResponse
from app.services.disclosure_service import DisclosureService, serialize
from app.utils import verify_token

version_router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Disclosures"],
)

global_router = APIRouter(prefix="/api/disclosures", tags=["Disclosures"])


class DisclosureCreate(BaseModel):
    disclosure_type: DisclosureType
    description: str = Field(min_length=1)
    venue_or_channel: Optional[str] = None
    disclosure_date: Optional[str] = None
    declarant_name: Optional[str] = None
    institution: Optional[str] = None


class GlobalDisclosureCreate(DisclosureCreate):
    product_id: int
    product_version_id: int


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


@version_router.get("/disclosures", response_model=APIResponse)
def list_disclosures(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    events = DisclosureService.list(db, product_id, version_id, _uid(token_payload))
    return APIResponse(
        success=True,
        data=[serialize(e) for e in events],
        message=f"Found {len(events)} disclosure event(s)",
    )


@version_router.post("/disclosures", response_model=APIResponse, status_code=201)
def create_disclosure(
    product_id: int,
    version_id: int,
    body: DisclosureCreate,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    event = DisclosureService.create(
        db,
        product_id,
        version_id,
        _uid(token_payload),
        body.disclosure_type,
        body.description,
        body.venue_or_channel,
        body.disclosure_date,
        body.declarant_name,
        body.institution,
    )
    return APIResponse(
        success=True,
        data=serialize(event),
        message="Disclosure event recorded",
    )


@version_router.post("/disclosure-review", response_model=APIResponse)
def disclosure_review(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    result = DisclosureService.review(db, product_id, version_id, _uid(token_payload))
    return APIResponse(success=True, data=result)


@global_router.post("", response_model=APIResponse, status_code=201)
def create_disclosure_global(
    body: GlobalDisclosureCreate,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    event = DisclosureService.create(
        db,
        body.product_id,
        body.product_version_id,
        _uid(token_payload),
        body.disclosure_type,
        body.description,
        body.venue_or_channel,
        body.disclosure_date,
        body.declarant_name,
        body.institution,
    )
    return APIResponse(
        success=True,
        data=serialize(event),
        message="Disclosure event recorded",
    )


@global_router.get("/{disclosure_id}", response_model=APIResponse)
def get_disclosure(
    disclosure_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    from app.services.disclosure_service import DisclosureService as S

    event = S.get_global(db, disclosure_id, _uid(token_payload))
    return APIResponse(success=True, data=serialize(event))


@global_router.get("/{disclosure_id}/verify", response_model=APIResponse)
def verify_disclosure(disclosure_id: int, db: Session = Depends(get_db)):
    """Public verification payload for QR checks - no authentication required."""
    from fastapi import HTTPException

    from app.models.disclosure_models import Disclosure as DisclosureModel

    event = db.query(DisclosureModel).filter(DisclosureModel.id == disclosure_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Disclosure not found")
    return APIResponse(
        success=True, data=DisclosureService.verify_payload(event)
    )
