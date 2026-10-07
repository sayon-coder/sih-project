"""
IP screening router (Phase 6).

Exposes the IP route map, patent screening and biodiversity / traditional-
knowledge screening:

  GET  /products/{product_id}/versions/{version_id}/ip-routes
  POST /products/{product_id}/versions/{version_id}/patents/search
  GET  /products/{product_id}/versions/{version_id}/patents
  POST /products/{product_id}/versions/{version_id}/patents/compare
  GET  /patents/{patent_id}
  POST /products/{product_id}/versions/{version_id}/biodiversity/screen
  POST /products/{product_id}/versions/{version_id}/traditional-knowledge/screen
  GET  /traditional-knowledge/sources

Every version-scoped route requires ownership of the enclosing product (ADMIN
bypasses), and all results are advisory and pinned to the version they reviewed.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data.traditional_knowledge_sources import (
    SOURCES_VERSION,
    get_traditional_knowledge_sources,
)
from app.database import get_db
from app.schemas.schemas import APIResponse
from app.services.analysis_service import AnalysisService
from app.services.ip_service import IPService
from app.utils import verify_token

router = APIRouter(prefix="/api", tags=["IP & Screening"])


class PatentCompareRequest(BaseModel):
    """Optional selection of which identified records to compare against."""

    patent_record_ids: Optional[List[int]] = None


def _payload(token_payload: dict) -> int:
    """Extract the authenticated user id from the verified token payload."""
    return int(token_payload["sub"])


# ============================================
# IP route map
# ============================================

@router.get(
    "/products/{product_id}/versions/{version_id}/ip-routes",
    response_model=APIResponse,
)
def get_ip_routes(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Return the preliminary IP route map for this version.

    The map is computed live from the recorded product data. Routes are
    indications worth reviewing, never statements that a route is legally
    applicable.
    """
    route_map = IPService.get_ip_route_map(db, product_id, version_id, _payload(token_payload))
    return APIResponse(
        success=True,
        data=route_map,
        message=f"IP route map produced ({len(route_map['routes'])} routes considered)",
    )


# ============================================
# Patent screening
# ============================================

@router.post(
    "/products/{product_id}/versions/{version_id}/patents/search",
    response_model=APIResponse,
)
def search_patents(
    product_id: int,
    version_id: int,
    request: Request,
    reuse: bool = True,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Screen this version for candidate patents and record the identified records.

    Runs against a frozen demonstration corpus; the response says so explicitly.
    It is not a live patent search and is never a patentability determination.
    ``reuse=true`` (default) returns the recorded screening for unchanged
    content instead of creating duplicate candidate records; ``reuse=false``
    forces a fresh screening.
    """
    analysis = IPService.search_patents(
        db, product_id, version_id, _payload(token_payload),
        request=request, reuse=reuse,
    )
    return APIResponse(
        success=True,
        data={
            **AnalysisService.serialize(analysis),
            "reused": bool(getattr(analysis, "_reused", False)),
        },
        message="Patent screening completed",
    )


@router.get(
    "/products/{product_id}/versions/{version_id}/patents",
    response_model=APIResponse,
)
def list_patents(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the candidate patent records already identified for this version."""
    records = IPService.list_patent_records(db, product_id, version_id, _payload(token_payload))
    return APIResponse(
        success=True,
        data=records,
        message=f"Found {len(records)} patent record(s)",
    )


@router.post(
    "/products/{product_id}/versions/{version_id}/patents/compare",
    response_model=APIResponse,
)
def compare_patents(
    product_id: int,
    version_id: int,
    request: Request,
    body: Optional[PatentCompareRequest] = None,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Compare this version's current technical features against identified records.

    Creates no new records; the comparison is recorded as an analysis run so it
    appears in the version's history.
    """
    ids = body.patent_record_ids if body else None
    analysis = IPService.compare_patents(
        db,
        product_id,
        version_id,
        _payload(token_payload),
        patent_record_ids=ids,
        request=request,
    )
    return APIResponse(
        success=True,
        data=AnalysisService.serialize(analysis),
        message="Patent feature comparison completed",
    )


@router.get("/patents/{patent_id}", response_model=APIResponse)
def get_patent(
    patent_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Fetch one identified patent record (scoped to an accessible version)."""
    record = IPService.get_patent_record(db, patent_id, _payload(token_payload))
    return APIResponse(success=True, data=record)


# ============================================
# Biodiversity / ABS and traditional knowledge
# ============================================

@router.post(
    "/products/{product_id}/versions/{version_id}/biodiversity/screen",
    response_model=APIResponse,
)
def screen_biodiversity(
    product_id: int,
    version_id: int,
    request: Request,
    include_sources: bool = False,
    reuse: bool = True,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Run a preliminary biodiversity / access-and-benefit-sharing screening.

    ``include_sources=true`` additionally searches the accessible corpus for
    supporting passages; it is opt-in because it requires the embedding model.
    ``reuse=true`` (default) returns the recorded content-only screening for
    unchanged content instead of running it again (corpus-dependent runs with
    ``include_sources=true`` are never reused).
    """
    analysis = IPService.screen_biodiversity(
        db,
        product_id,
        version_id,
        _payload(token_payload),
        include_sources=include_sources,
        request=request,
        reuse=reuse,
    )
    return APIResponse(
        success=True,
        data={
            **AnalysisService.serialize(analysis),
            "reused": bool(getattr(analysis, "_reused", False)),
        },
        message="Biodiversity/ABS screening completed",
    )


@router.post(
    "/products/{product_id}/versions/{version_id}/traditional-knowledge/screen",
    response_model=APIResponse,
)
def screen_traditional_knowledge(
    product_id: int,
    version_id: int,
    request: Request,
    include_sources: bool = False,
    reuse: bool = True,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Run a preliminary traditional-knowledge screening (public sources only).

    ``include_sources=true`` additionally searches the accessible corpus to check
    whether a traditional use is publicly documented. Restricted sources such as
    the TKDL are never searched. ``reuse=true`` (default) returns the recorded
    content-only screening for unchanged content; ``include_sources=true`` runs
    are never reused.
    """
    analysis = IPService.screen_traditional_knowledge(
        db,
        product_id,
        version_id,
        _payload(token_payload),
        include_sources=include_sources,
        request=request,
        reuse=reuse,
    )
    return APIResponse(
        success=True,
        data={
            **AnalysisService.serialize(analysis),
            "reused": bool(getattr(analysis, "_reused", False)),
        },
        message="Traditional-knowledge screening completed",
    )


@router.get("/traditional-knowledge/sources", response_model=APIResponse)
def list_traditional_knowledge_sources(
    token_payload: dict = Depends(verify_token),
):
    """
    List the traditional-knowledge sources the platform is permitted to use.

    Public, permitted and restricted/unavailable sources are distinguished
    explicitly. Restricted sources (notably the TKDL) are listed only so a
    reviewer knows to consult them through the authorised channel - the platform
    does not access or reproduce them.
    """
    sources = get_traditional_knowledge_sources()
    return APIResponse(
        success=True,
        data={
            "sources_version": SOURCES_VERSION,
            "sources": sources,
            "restricted_note": (
                "Restricted sources are not accessible to this platform. They are "
                "listed for orientation only and are never searched or reproduced."
            ),
        },
        message=f"{len(sources)} source categories",
    )
