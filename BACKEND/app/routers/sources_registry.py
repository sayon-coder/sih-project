"""
Authoritative-sources registry router.

  GET /api/official-sources               filterable registry (auth)
  GET /api/official-sources/topics        distinct topics
  GET /api/official-sources/{source_id}   one entry (+ your permission state)

Why this prefix and not ``/api/sources``: ``app/routers/sources.py`` already
owns ``/api/sources``, ``/api/sources/search`` and ``/api/sources/{id}`` for
*corpus documents* (see tests/test_gap_endpoints.py). Registering a second
router at the same prefix would either shadow those routes or be shadowed by
``/api/sources/{source_id}`` (its ``str`` path param swallows every one-token
suffix such as ``/topics`` and returns 422). ``/api/official-sources`` is
collision-free in either registration order; the collision analysis is in
PRIVACY.md.

The response distinguishes FREE / FREE_REGISTRATION (direct access) from
PAID_SUBSCRIPTION / THIRD_PARTY_API / RESTRICTED_NOT_ACCESSED, which are
always returned with ``requires_permission: true`` and a ``restricted_note`` -
never as if they were directly accessible. Paid access is reached only
through POST /api/privacy/sources/consent + POST /api/privacy/sources/access.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.data.official_sources import (
    ACCESS_VALUES,
    VERIFICATION_NOTE,
    VERIFIED_ON,
    distinct_jurisdictions,
    distinct_topics,
    get_official_source,
    list_official_sources,
    sources_for_topic,
)
from app.database import get_db
from app.models.models import User
from app.schemas.schemas import APIResponse
from app.services.privacy_service import effective_source_consent, source_consent_out
from app.utils import get_current_user_model
from app.config import get_settings
from app.utils.cache import cache

router = APIRouter(prefix="/api/official-sources", tags=["Official Sources"])


@router.get("", response_model=APIResponse)
def list_sources(
    jurisdiction: Optional[str] = Query(
        None, description="Exact jurisdiction, e.g. 'India' or 'International'."
    ),
    ip_type: Optional[str] = Query(
        None, description="patent | trademark | geographical_indication | design | "
        "plant_variety | regulatory | access_and_benefit_sharing | traditional_knowledge"
    ),
    topic: Optional[str] = Query(None, description="Substring match on a topic."),
    access: Optional[str] = Query(
        None, description=f"One of: {', '.join(ACCESS_VALUES)}"
    ),
    q: Optional[str] = Query(
        None, min_length=1, max_length=200, description="Free-text keyword search."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    The authoritative-source registry.

    FREE and FREE_REGISTRATION entries are directly reachable. Anything else
    carries ``requires_permission: true``, ``direct_access: false`` and a
    ``restricted_note`` describing why - paid and restricted sources are
    never presented as if they were open to everyone.
    """
    if access is not None and access.strip().upper() not in ACCESS_VALUES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ACCESS_FILTER",
                "message": f"access must be one of {', '.join(ACCESS_VALUES)}.",
            },
        )

    settings = get_settings()
    cache_key = (
        f"registry:list:j{jurisdiction}:i{ip_type}:t{topic}:a{access}:q{q}"
    )
    entries = cache.get(cache_key) if settings.cache_enabled else None
    if entries is None:
        if q:
            entries = sources_for_topic(q)
            # Combine the free-text pass with any structured filters.
            if jurisdiction or ip_type or topic or access:
                allowed = {
                    entry["id"]
                    for entry in list_official_sources(
                        jurisdiction=jurisdiction,
                        ip_type=ip_type,
                        topic=topic,
                        access=access,
                    )
                }
                entries = [entry for entry in entries if entry["id"] in allowed]
        else:
            entries = list_official_sources(
                jurisdiction=jurisdiction,
                ip_type=ip_type,
                topic=topic,
                access=access,
            )
        if settings.cache_enabled:
            cache.set(cache_key, entries, ttl=settings.cache_registry_ttl_seconds)
    free = sum(1 for entry in entries if entry["direct_access"])
    gated = len(entries) - free
    return APIResponse(
        success=True,
        data={
            "sources": entries,
            "count": len(entries),
            "direct_access_count": free,
            "permission_required_count": gated,
            "verified_on": VERIFIED_ON,
            "verification_note": VERIFICATION_NOTE,
        },
        message=f"Found {len(entries)} source(s): {free} direct, {gated} permission-gated",
    )


@router.get("/topics", response_model=APIResponse)
def topics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Distinct topics and jurisdictions covered by the registry."""
    settings = get_settings()
    hit = cache.get("registry:topics") if settings.cache_enabled else None
    if hit is None:
        hit = {
            "topics": distinct_topics(),
            "jurisdictions": distinct_jurisdictions(),
            "access_values": list(ACCESS_VALUES),
        }
        if settings.cache_enabled:
            cache.set("registry:topics", hit, ttl=settings.cache_registry_ttl_seconds)
    return APIResponse(
        success=True,
        data=hit,
        message=f"{len(hit['topics'])} topic(s)",
    )


@router.get("/{source_id}", response_model=APIResponse)
def get_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    One registry entry.

    For permission-gated sources the response also reports the caller's own
    permission state (``your_permission``), so "logged permission" is visible
    from the registry itself.
    """
    entry = get_official_source(source_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SOURCE_NOT_FOUND",
                "message": f"No registered source with id '{source_id}'.",
            },
        )

    payload = dict(entry)
    payload["access_endpoint"] = "POST /api/privacy/sources/access"
    payload["consent_endpoint"] = "POST /api/privacy/sources/consent"

    consent = effective_source_consent(db, current_user.id, source_id)
    if entry["requires_permission"]:
        payload["your_permission"] = (
            source_consent_out(consent) if consent is not None else None
        )
        payload["permission_required"] = True
    else:
        payload["your_permission"] = None
        payload["permission_required"] = False

    return APIResponse(
        success=True,
        data=payload,
        message=entry["title"],
    )
