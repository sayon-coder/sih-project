"""
Audit router (Phase 10).

  GET /api/audit          the caller's own audit trail (?limit=)
  GET /api/audit/{audit_id}  one entry (own entries; ADMIN may read any)

Sensitive values are never stored in audit details by the services, and the
user-agent/IP columns are operational metadata only.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog
from app.schemas.schemas import APIResponse
from app.utils import is_admin, verify_token

router = APIRouter(prefix="/api/audit", tags=["Audit"])


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


def _out(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "action": entry.action,
        "resource": entry.resource,
        "resource_id": entry.resource_id,
        "ip_address": entry.ip_address,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }


@router.get("", response_model=APIResponse)
def list_audit(
    limit: int = Query(default=50, ge=1, le=200),
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == _uid(token_payload))
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return APIResponse(
        success=True,
        data=[_out(e) for e in entries],
        message=f"Found {len(entries)} audit entr(y/ies)",
    )


@router.get("/{audit_id}", response_model=APIResponse)
def get_audit(
    audit_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    entry = db.query(AuditLog).filter(AuditLog.id == audit_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    user_id = _uid(token_payload)
    if entry.user_id != user_id and not is_admin(db, user_id):
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return APIResponse(success=True, data=_out(entry))
