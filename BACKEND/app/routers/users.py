"""
Users router (master prompt section 7 — USERS).

  GET    /api/users/me          the caller's profile
  PUT    /api/users/me          update own profile (username / email only)
  GET    /api/users/me/history  the caller's audit history (?limit=)
  GET    /api/users/me/privacy  data-principal entry point (notice + rights map)

Roles, privileges, password and account state are deliberately not writable
here — profile changes are audit-logged as "update_profile".
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User
from app.schemas.schemas import APIResponse
from app.services.audit_service import AuditService
from app.services import privacy_service
from app.utils import get_current_user_model, get_user_role_names, verify_token

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    email: Optional[EmailStr] = None


def _profile_out(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "roles": sorted(get_user_role_names(db, user.id)),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/me", response_model=APIResponse)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Return the authenticated user's profile."""
    return APIResponse(success=True, data=_profile_out(db, current_user))


@router.put("/me", response_model=APIResponse)
def update_me(
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token),
    current_user: User = Depends(get_current_user_model),
):
    """Update the caller's own username and/or email address."""
    if body.username is None and body.email is None:
        raise HTTPException(
            status_code=400, detail="Provide a username or an email to update."
        )

    fields = []

    if body.email is not None and body.email != current_user.email:
        taken = (
            db.query(User)
            .filter(User.email == body.email, User.id != current_user.id)
            .first()
        )
        if taken is not None:
            raise HTTPException(status_code=409, detail="That email address is already in use.")
        current_user.email = body.email
        fields.append("email")

    if body.username is not None and body.username != current_user.username:
        current_user.username = body.username
        fields.append("username")

    if fields:
        db.commit()
        db.refresh(current_user)
        AuditService.log_action(
            db,
            user_id=current_user.id,
            action="update_profile",
            resource="user",
            resource_id=current_user.id,
            details={"fields": fields},
            request=request,
        )

    return APIResponse(
        success=True,
        data=_profile_out(db, current_user),
        message="Profile updated" if fields else "No changes to apply",
    )


@router.get("/me/history", response_model=APIResponse)
def my_history(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token),
):
    """Return the caller's own audit history (never other users' entries)."""
    user_id = int(token_payload["sub"])
    entries = AuditService.get_user_logs(db, user_id, limit=limit)
    return APIResponse(
        success=True,
        data=[
            {
                "id": e.id,
                "action": e.action,
                "resource": e.resource,
                "resource_id": e.resource_id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in entries
        ],
        message=f"Found {len(entries)} entr(y/ies)",
    )


@router.get("/me/privacy", response_model=APIResponse)
def my_privacy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """
    Data-principal entry point: the current privacy-notice version, the
    purposes it covers, your rights, and where each right is exercised.

    The full notice text lives at GET /api/privacy/notice; the records
    themselves at GET /api/privacy/consent. Correction of profile fields is
    the PUT /api/users/me call this router already exposes.
    """
    notice = privacy_service.get_privacy_notice()
    return APIResponse(
        success=True,
        data={
            "notice_version": notice["version"],
            "framework": notice["framework"],
            "purposes": sorted(notice["purposes"]),
            "rights": notice["rights"],
            "endpoints": {
                "notice": "GET /api/privacy/notice",
                "consent": "GET|POST /api/privacy/consent",
                "withdraw_consent": "DELETE /api/privacy/consent/{consent_id}",
                "export": "GET /api/privacy/export",
                "erasure": "DELETE /api/privacy/account",
                "retention": "GET /api/privacy/retention",
                "source_permission": "GET|POST|DELETE /api/privacy/sources/consent",
                "source_access": "POST /api/privacy/sources/access",
                "source_access_log": "GET /api/privacy/sources/access-log",
                "official_sources": "GET /api/official-sources",
                "audit_trail": "GET /api/audit",
            },
        },
        message="Privacy notice and data-principal rights map",
    )
