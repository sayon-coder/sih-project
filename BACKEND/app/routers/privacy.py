"""
Privacy router - DPDP-aligned data-principal rights and consent-gated sources.

Data principal rights (Digital Personal Data Protection Act, 2023):

  GET    /api/privacy/notice               the privacy notice (version + text)
  GET    /api/privacy/consent              notice + the caller's consent records
  POST   /api/privacy/consent              grant consent to named purposes
  DELETE /api/privacy/consent/{consent_id} withdraw consent (row kept, stamped)
  GET    /api/privacy/export               access & portability - owner only
  DELETE /api/privacy/account              right to erasure (typed confirmation)
  GET    /api/privacy/retention            the configured retention policy
  POST   /api/privacy/purge                apply retention (ADMIN)

Explicit, logged permission for paid / third-party connectors:

  POST   /api/privacy/sources/consent      grant permission  (confirm: true)
  GET    /api/privacy/sources/consent      the caller's permissions
  DELETE /api/privacy/sources/consent/{id} revoke (idempotent, owner-scoped)
  POST   /api/privacy/sources/access       consent-checked handoff (403 otherwise)
  GET    /api/privacy/sources/access-log   the caller's permission/access trail

Every route is authenticated. Nothing here lets an ADMIN read another data
principal's export or consents: the routes are owner-scoped by construction
(there is no user-id parameter anywhere in this router).
"""
from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import User
from app.models.privacy_models import DataConsent, SourceConsent
from app.schemas.schemas import APIResponse
from app.services import privacy_service
from app.utils import get_current_user_model, require_admin

router = APIRouter(prefix="/api/privacy", tags=["Privacy"])


# -------------------------------------------------------
# Request schemas
# -------------------------------------------------------

class DataConsentGrant(BaseModel):
    """Grant consent to a set of processing purposes."""

    purposes: List[str] = Field(default_factory=list)
    grant: bool = Field(
        False,
        description="Must be an explicit true - consent is never assumed.",
    )


class SourceConsentCreate(BaseModel):
    """Explicit permission for one external source/connector."""

    source_id: str = Field(min_length=1, max_length=100)
    access_type: str = Field(
        default="PAID_SUBSCRIPTION",
        description="PAID_SUBSCRIPTION | THIRD_PARTY_API | FREE",
    )
    scope: List[str] = Field(
        default_factory=list,
        description="Exactly which data the user permits to be used.",
    )
    expires_in_days: Optional[int] = Field(
        None, ge=1, le=3650,
        description="Defaults to SOURCE_CONSENT_DEFAULT_DAYS.",
    )
    confirm: bool = Field(
        False,
        description="Must be an explicit true - permission is never assumed.",
    )


class SourceAccessRequest(BaseModel):
    """Ask for a hand-off to a source (consent is checked first)."""

    source_id: str = Field(min_length=1, max_length=100)


class EraseAccountRequest(BaseModel):
    """Erasure requires the data principal to retype their own email."""

    confirm: str = Field(
        min_length=1,
        description="Must equal the caller's registered email address.",
    )


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    """Machine-readable API error (detail is always a dict with a code)."""
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


# -------------------------------------------------------
# Notice + data consent
# -------------------------------------------------------

@router.get("/notice", response_model=APIResponse)
def get_notice(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """The privacy notice: what is collected, why, how long, who with, and your rights."""
    return APIResponse(
        success=True,
        data=privacy_service.get_privacy_notice(),
        message="Privacy notice",
    )


@router.get("/consent", response_model=APIResponse)
def my_consents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """The privacy notice plus the caller's own consent records."""
    return APIResponse(
        success=True,
        data={
            "notice": privacy_service.get_privacy_notice(),
            "consents": privacy_service.list_data_consents(db, current_user.id),
        },
        message="Notice and consent records",
    )


@router.post("/consent", response_model=APIResponse)
def grant_consent(
    body: DataConsentGrant,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Record an explicit grant against the current privacy-notice version."""
    if body.grant is not True:
        raise _err(
            400,
            "GRANT_REQUIRED",
            "Consent must be explicit: set grant: true after reading the notice.",
        )
    consent, audit_id = privacy_service.record_data_consent(
        db, current_user, body.purposes, request
    )
    return APIResponse(
        success=True,
        data={"consent": consent, "audit_id": audit_id},
        message="Consent recorded",
    )


@router.delete("/consent/{consent_id}", response_model=APIResponse)
def withdraw_consent(
    consent_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Withdraw consent (right to withdraw). The record is kept, stamped withdrawn."""
    consent = privacy_service.withdraw_data_consent(
        db, current_user, consent_id, request
    )
    return APIResponse(
        success=True,
        data={"consent": consent},
        message="Consent withdrawn",
    )


# -------------------------------------------------------
# Access & portability (export)
# -------------------------------------------------------

@router.get("/export")
def export_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    Data principal's access & portability export.

    Owner-scoped by construction: there is no user-id parameter, so an ADMIN
    requesting this route only ever receives their own data.
    """
    payload = privacy_service.build_export(db, current_user)

    from app.services.audit_service import AuditService

    AuditService.log_action(
        db=db,
        user_id=current_user.id,
        action="export_data",
        resource="user",
        resource_id=current_user.id,
        details={"counts": payload["counts"], "truncated": payload["truncated"]},
        request=request,
    )

    filename = f"ip-sakti-export-user-{current_user.id}-{date.today().isoformat()}.json"
    return JSONResponse(
        content=json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------------------------------------
# Erasure
# -------------------------------------------------------

@router.delete("/account", response_model=APIResponse)
def erase_account(
    body: EraseAccountRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    Right to erasure: anonymise the account, delete the personal data, keep
    the audit trail (with user_id NULL).

    Requires the caller to retype their own email address, so a stray or
    forged request can never destroy an account by accident.
    """
    if body.confirm != current_user.email:
        raise _err(
            400,
            "CONFIRM_MISMATCH",
            "Type your registered email address exactly to confirm erasure.",
        )

    summary = privacy_service.erase_account(db, current_user, request)
    return APIResponse(
        success=True,
        data=summary,
        message="Account erased and anonymised",
    )


# -------------------------------------------------------
# Retention
# -------------------------------------------------------

@router.get("/retention", response_model=APIResponse)
def get_retention(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """The configured retention policy as data (0 days = never purge)."""
    return APIResponse(
        success=True,
        data=privacy_service.retention_policy(),
        message="Retention policy",
    )


@router.post("/purge", response_model=APIResponse)
def purge(
    request: Request,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Apply the configured retention windows (ADMIN only). 0 days = never purge."""
    actor_id = int(admin["sub"])
    result = privacy_service.run_retention_purge(db, request, actor_id)
    return APIResponse(success=True, data=result, message=result["message"])


# -------------------------------------------------------
# Source permission (explicit, logged) - declared before /sources/consent/{id}
# so literal paths are matched first
# -------------------------------------------------------

@router.get("/sources/consent", response_model=APIResponse)
def my_source_consents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """The caller's own permission records for external sources/connectors."""
    consents = privacy_service.list_source_consents(db, current_user.id)
    return APIResponse(
        success=True,
        data=consents,
        message=f"Found {len(consents)} permission record(s)",
    )


@router.post("/sources/consent", response_model=APIResponse)
def grant_source_consent(
    body: SourceConsentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    Grant explicit, logged permission for one source/connector.

    ``confirm: true`` is mandatory: permission is never inferred from an
    incomplete payload. Writes SourceConsent(GRANTED) + SourceAccessLog
    (PERMISSION_GRANTED) + an audit entry.
    """
    if body.confirm is not True:
        raise _err(
            400,
            "CONFIRM_REQUIRED",
            "Permission must be explicit: set confirm: true to grant access.",
        )
    consent, audit_id = privacy_service.grant_source_consent(
        db=db,
        user=current_user,
        source_id=body.source_id,
        access_type=body.access_type,
        scope=body.scope,
        expires_in_days=body.expires_in_days,
        request=request,
    )
    return APIResponse(
        success=True,
        data={"consent": consent, "audit_id": audit_id},
        message="Permission granted and logged",
    )


@router.delete("/sources/consent/{consent_id}", response_model=APIResponse)
def revoke_source_consent(
    consent_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Revoke a permission you granted. Idempotent; another user's row is 404."""
    consent = privacy_service.revoke_source_consent(
        db, current_user, consent_id, request
    )
    return APIResponse(
        success=True,
        data={"consent": consent},
        message="Permission revoked",
    )


@router.get("/sources/access-log", response_model=APIResponse)
def source_access_log(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """The caller's own permission/access evidence trail (never other users')."""
    entries = privacy_service.list_source_access_log(
        db, current_user.id, limit=max(1, min(limit, 500))
    )
    return APIResponse(
        success=True,
        data=entries,
        message=f"Found {len(entries)} access-log entr(y/ies)",
    )


@router.post("/sources/access", response_model=APIResponse)
def access_source(
    body: SourceAccessRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    Consent-checked handoff to a source.

    Without an effective GRANTED permission: 403 with a machine-readable body
    plus ACCESS_BLOCKED_NO_PERMISSION / PERMISSION_DENIED log rows. With
    permission: ACCESS_ATTEMPTED + ACCESS_PERFORMED and a ``mode:
    "HANDOFF"`` descriptor - this platform never fetches paid data itself.
    """
    descriptor = privacy_service.connector_handoff(
        db, current_user, body.source_id, request
    )
    return APIResponse(
        success=True,
        data=descriptor,
        message="Permission verified - handoff issued (open the source yourself)",
    )


# -------------------------------------------------------
# Convenience: expose the row types for the integrator's Alembic migration
# -------------------------------------------------------
__all__ = ["router", "DataConsent", "SourceConsent"]
