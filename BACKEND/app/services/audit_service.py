"""
Audit logging service for tracking user actions.
"""
import json
import re
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from fastapi import Request
from app.models import AuditLog

#: Keys whose values must never be persisted in an audit ``details`` payload.
#: Keys are normalised first (``user_name`` == ``username``), then matched
#: case-insensitively as substrings, so ``email``, ``user_email``,
#: ``password_hash`` and ``refresh_token`` are all covered. Bare ``user_id``
#: deliberately stays readable - it is an opaque id, not an identifier.
SENSITIVE_KEY_PATTERN = re.compile(
    r"email|username|password|passwd|token|secret|phone|mobile",
    re.IGNORECASE,
)

#: Replacement written in place of any sensitive value.
REDACTED = "***"


def _normalise_key(key: Any) -> str:
    """Fold separators so ``user_name`` and ``api-token`` match their words."""
    return re.sub(r"[\s_\-]+", "", str(key))


def sanitize_details(details: Any) -> Any:
    """
    Recursively redact PII/secret values from an audit details payload.

    Dict keys whose normalised name matches :data:`SENSITIVE_KEY_PATTERN` have
    their value replaced with ``"***"``; nested dicts and lists of dicts are
    walked so a value cannot be smuggled in one level down. Everything else
    (ids, field names, counts, hashes, reasons) is left intact - an audit
    entry stays useful while the personal data stays out of the log.

    This is what makes ``routers/audit.py``'s promise true regardless of what
    a caller passes to :meth:`AuditService.log_action`.
    """
    if isinstance(details, dict):
        clean: Dict[str, Any] = {}
        for key, value in details.items():
            if SENSITIVE_KEY_PATTERN.search(_normalise_key(key)):
                clean[key] = REDACTED
            else:
                clean[key] = sanitize_details(value)
        return clean
    if isinstance(details, (list, tuple)):
        return [sanitize_details(item) for item in details]
    return details


class AuditService:
    """Service for creating and managing audit logs."""

    @staticmethod
    def log_action(
        db: Session,
        user_id: Optional[int],
        action: str,
        resource: str,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None
    ) -> AuditLog:
        """
        Create an audit log entry.

        Args:
            db: Database session
            user_id: ID of user performing action (None if not authenticated)
            action: Action performed (e.g., 'login', 'create_product')
            resource: Resource type (e.g., 'user', 'product')
            resource_id: ID of affected resource
            details: Additional details as dict (PII/secrets are redacted
                automatically via ``sanitize_details``)
            request: FastAPI request object for IP/user agent extraction

        Returns:
            Created AuditLog instance
        """
        ip_address = None
        user_agent = None

        if request:
            # Get client IP
            ip_address = request.client.host if request.client else None

            # Get user agent
            user_agent = request.headers.get("user-agent", None)

        # Never persist emails, usernames, passwords, tokens, secrets or
        # phone numbers in the audit trail, whatever the caller passed in.
        if details is not None:
            details = sanitize_details(details)

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        return audit_log

    @staticmethod
    def get_user_logs(
        db: Session,
        user_id: int,
        limit: int = 100
    ) -> list[AuditLog]:
        """
        Get audit logs for a specific user.

        Args:
            db: Database session
            user_id: User ID
            limit: Maximum number of logs to return

        Returns:
            List of AuditLog instances
        """
        return db.query(AuditLog).filter(
            AuditLog.user_id == user_id
        ).order_by(
            AuditLog.timestamp.desc()
        ).limit(limit).all()

    @staticmethod
    def get_resource_logs(
        db: Session,
        resource: str,
        resource_id: int,
        limit: int = 100
    ) -> list[AuditLog]:
        """
        Get audit logs for a specific resource.

        Args:
            db: Database session
            resource: Resource type
            resource_id: Resource ID
            limit: Maximum number of logs to return

        Returns:
            List of AuditLog instances
        """
        return db.query(AuditLog).filter(
            AuditLog.resource == resource,
            AuditLog.resource_id == resource_id
        ).order_by(
            AuditLog.timestamp.desc()
        ).limit(limit).all()
