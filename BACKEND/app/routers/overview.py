"""
Overall Product View router (spec item 16).

  GET /api/products/{product_id}/versions/{version_id}/overview

One aggregate, built by ``app.services.overview_service`` from stored rows
only, that the Overall Product View page and the chatbot both read
(spec item 17: the same data, never two conflicting interpretations).

The endpoint performs no analysis and writes nothing - it reports what the
selected Product Passport version and its recorded runs actually contain.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.schemas import APIResponse
from app.services.overview_service import build_overview_cached
from app.utils import verify_token
from app.utils.authorization import get_accessible_version

version_router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Overall Product View"],
)


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


@version_router.get("/overview", response_model=APIResponse)
def get_overview(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Overall Product View for the selected Product Passport version."""
    user_id = _uid(token_payload)
    version = get_accessible_version(db, product_id, version_id, user_id)
    overview = build_overview_cached(db, version.product, version, user_id=user_id)
    return APIResponse(
        success=True,
        message="Overall Product View built from the stored version record.",
        data=overview,
    )
