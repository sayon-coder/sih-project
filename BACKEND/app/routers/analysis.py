"""
Analysis router (Phase 5).

Exposes the assistant's analysis workflows for a product version:

  POST /claims/analyze          claim-to-evidence review
  POST /analyze                 comprehensive preliminary analysis
  GET  /analyses                list recorded analyses (optional type filter)
  GET  /analyses/{analysis_id}  one recorded analysis

Every route is nested under an owned product version, and each result is stored
against the exact version it reviewed so history is never silently rewritten.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.schemas import APIResponse
from app.services.analysis_service import AnalysisService
from app.utils import verify_token

router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Analysis"],
)


def _payload(token_payload: dict) -> int:
    """Extract the authenticated user id from the verified token payload."""
    return int(token_payload["sub"])


@router.post("/claims/analyze", response_model=APIResponse)
def analyze_claims(
    product_id: int,
    version_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Run a claim-to-evidence review for this version.

    The review is advisory: it records a new analysis but never edits the
    underlying claims. An AI suggestion can never mark a claim supported or
    expert-verified.
    """
    analysis = AnalysisService.analyze_claims(
        db, product_id, version_id, _payload(token_payload), request=request
    )
    return APIResponse(
        success=True,
        data=AnalysisService.serialize(analysis),
        message="Claim analysis completed",
    )


@router.post("/analyze", response_model=APIResponse)
def analyze_product(
    product_id: int,
    version_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Run a comprehensive preliminary analysis for this version.

    Orchestrates a preliminary product classification and a claim/evidence
    review, then derives target-market considerations and expert-review
    recommendations. Stages owned by later phases are listed explicitly in
    ``deferred_components``.
    """
    analysis = AnalysisService.analyze_product(
        db, product_id, version_id, _payload(token_payload), request=request
    )
    return APIResponse(
        success=True,
        data=AnalysisService.serialize(analysis),
        message="Analysis completed",
    )


@router.get("/analyses", response_model=APIResponse)
def list_analyses(
    product_id: int,
    version_id: int,
    analysis_type: Optional[str] = None,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List analyses recorded for this version, newest first."""
    analyses = AnalysisService.list_analyses(
        db, product_id, version_id, _payload(token_payload), analysis_type=analysis_type
    )
    return APIResponse(
        success=True,
        data=[AnalysisService.serialize(a) for a in analyses],
        message=f"Found {len(analyses)} analyses",
    )


@router.get("/analyses/{analysis_id}", response_model=APIResponse)
def get_analysis(
    product_id: int,
    version_id: int,
    analysis_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Fetch one recorded analysis for this version."""
    analysis = AnalysisService.get_analysis(
        db, product_id, version_id, analysis_id, _payload(token_payload)
    )
    return APIResponse(success=True, data=AnalysisService.serialize(analysis))
