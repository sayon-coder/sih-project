"""
DPDP-aligned privacy service for IP-SAKTI Sahayak.

This module holds everything the privacy router exposes, so the router stays
thin and the rules are testable on their own:

* the privacy notice (what is collected, why, how long, who it is shared
  with, and the data principal's rights under the Digital Personal Data
  Protection Act, 2023);
* consent capture / withdrawal (records are never deleted on withdrawal -
  ``withdrawn_at`` is set so the history stays auditable);
* explicit, logged permission for paid / third-party source connectors, and
  the access decision that consults it first;
* the data principal's access & portability export (owner-scoped only);
* erasure: anonymise the account, delete the personal data, keep the audit
  trail with ``user_id`` NULL;
* the configured retention policy and the (manual) purge job.

Honesty rules followed here
---------------------------
* The platform does not proxy, scrape or fetch paid sources: a permitted
  access returns ``mode: "HANDOFF"`` - the user opens the source themselves.
* Erasure never claims more than it did: the returned summary lists exactly
  what was erased and what was retained.
* Nothing here invents section numbers for the Act; it is cited by name.
"""
from __future__ import annotations

import enum
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.official_sources import get_official_source
from app.models.ingredient_models import Claim, Evidence
from app.models.disclosure_models import Disclosure
from app.models.models import AuditLog, User, UserRole
from app.models.privacy_models import DataConsent, SourceAccessLog, SourceConsent
from app.models.product_models import Product, ProductVersion
from app.models.rag_models import (
    ChatAttachment,
    ChatMessage,
    ChatSession,
    SourceChunk,
    SourceDocument,
)
from app.models.report_models import Report
from app.services.audit_service import AuditService


# =======================================================
# Privacy notice
# =======================================================

#: Stamped on every consent record. Source of truth is the setting so the
#: notice version and the consent rows can never drift apart.
PRIVACY_NOTICE_VERSION: str = get_settings().privacy_notice_version

#: Purposes a data principal may consent to. Keys are stored in
#: ``DataConsent.purposes``; the human wording lives here.
AVAILABLE_PURPOSES: Dict[str, str] = {
    "account": (
        "Create and manage your account, authenticate you, and keep your "
        "profile (username and email address)."
    ),
    "assistant": (
        "Answer your questions about Ayurveda IP and regulation, keep the "
        "conversation context of your chat sessions, and remember which "
        "product/version you were working on."
    ),
    "knowledge_base": (
        "Store and index the documents you upload so they can be retrieved "
        "in answers, and enforce your public/private visibility choice."
    ),
    "ip_analysis": (
        "Run product, claim, evidence, disclosure and report workflows over "
        "the data you enter, and produce the documents you request."
    ),
    "security_and_audit": (
        "Security monitoring, abuse prevention and the audit trail this "
        "platform is required to keep (IP address and user agent are stored "
        "as operational metadata on audit entries)."
    ),
    "support": (
        "Respond to support requests, grievances and feedback you send us."
    ),
}

#: Rights of the data principal under the Digital Personal Data Protection
#: Act, 2023, in plain language. Described, not numbered - the Act is cited
#: by name only.
DATA_PRINCIPAL_RIGHTS: List[Dict[str, str]] = [
    {
        "right": "Access",
        "summary": (
            "Ask for a summary of the personal data held about you and of how "
            "it has been processed, and for the names of other data "
            "fiduciaries it has been shared with."
        ),
        "implemented_at": "GET /api/privacy/export",
    },
    {
        "right": "Correction and erasure",
        "summary": (
            "Correct data that is inaccurate or incomplete, and ask for your "
            "personal data to be erased where it is no longer necessary for "
            "the purpose it was collected for (subject to the exceptions the "
            "Act allows)."
        ),
        "implemented_at": "PUT /api/users/me (correction), DELETE /api/privacy/account (erasure)",
    },
    {
        "right": "Grievance redressal",
        "summary": (
            "Raise a grievance about how your data is handled and have it "
            "addressed within a reasonable time."
        ),
        "implemented_at": "Support channel / audit trail at GET /api/audit",
    },
    {
        "right": "Nomination",
        "summary": (
            "Nominate another individual to exercise your rights on your behalf "
            "in the event of your death or in case you are unable to do so."
        ),
        "implemented_at": "Not implemented in this build (see PRIVACY.md)",
    },
    {
        "right": "Withdrawal of consent",
        "summary": (
            "Withdraw consent at any time for the purposes you consented to, "
            "with the same ease you gave it. Withdrawal is recorded, never "
            "silently discarded, and it does not undo processing that already "
            "lawfully happened."
        ),
        "implemented_at": "DELETE /api/privacy/consent/{id}",
    },
]

PRIVACY_NOTICE_TEXT = f"""\
PRIVACY NOTICE - IP-SAKTI Sahayak (version {PRIVACY_NOTICE_VERSION})

This notice is given to every data principal under the Digital Personal Data
Protection Act, 2023 (DPDP Act). It explains, in plain language, what we
collect, why we collect it, how long we keep it, who we share it with, and
the rights you can exercise. Consent is always free, specific, informed,
unconditional and unambiguous, and is limited to the purposes you tick. You
can withdraw it at any time.

1. WHAT WE COLLECT
   - Account data: your email address, a username you choose, and a
     password that we store only as a salted hash.
   - Your work product: products and their versions, claims and evidence
     you record, expert reviews, disclosures, and the reports you generate.
   - Conversations: chat sessions and messages you have with the assistant,
     plus documents you attach or upload to the knowledge base.
   - Operational metadata: IP address and user agent on audit entries,
     used for security and investigation.
   - Permissions you grant: for example, permission to hand off to a paid
     subscription you already own, including when it was granted, its scope
     and when it was revoked.

2. WHY WE COLLECT IT (the purposes you consent to)
   account, assistant, knowledge_base, ip_analysis, security_and_audit and
   support - each described in full at GET /api/privacy/consent. We do not
   sell personal data. We do not use your content to train third-party
   models. Automated answer generation is assistive: it does not by itself
   produce legal, medical or regulatory decisions about you.

3. HOW LONG WE KEEP IT
   - Chat messages and sessions: kept until you delete them, or until
     CHAT_RETENTION_DAYS passes if an administrator configures a window.
   - Uploaded documents: kept until you delete them, or until
     UPLOAD_RETENTION_DAYS passes if configured.
   - Audit entries: kept as long as the platform operates (this is
     evidence); AUDIT_RETENTION_DAYS defaults to 0 = never purge.
   - Consents and permission logs: kept for as long as needed to prove what
     was consented to and when; they are anonymised rather than destroyed
     when you erase your account.
   Defaults are "keep until you delete it" (0 days). The live policy is at
   GET /api/privacy/retention.

4. WHO WE SHARE IT WITH
   - Service providers that run the platform (hosting and the LLM provider
     you have configured), only to the extent needed to answer your request.
   - Other users of this platform, only where you choose to share something
     (for example a public knowledge-base document or an expert review).
   - Your own paid subscriptions and third-party connectors: never without
     your explicit, logged permission, and always as a hand-off you perform
     yourself - we do not fetch or store paid data on your behalf.
   - Regulators or authorities, only where the law requires it.
   We do not transfer your personal data outside India except to the extent
   the DPDP Act and the rules made under it permit.

5. YOUR RIGHTS AS A DATA PRINCIPAL
   Access; correction and erasure; grievance redressal; nomination of
   another individual to act for you; and withdrawal of consent at any time.
   Endpoints: GET /api/privacy/export (access & portability),
   PUT /api/users/me (correction), DELETE /api/privacy/account (erasure),
   DELETE /api/privacy/consent/{id} (withdraw consent).

6. CHILDREN
   This platform is not directed at children, and we do not knowingly
   process children's data or track/monitor their behaviour.

7. CONTACT
   Raise grievances through the support channel of the deployment you are
   using. Every privacy action you take is written to an audit entry you
   can read yourself at GET /api/audit.
"""


# =======================================================
# Small helpers
# =======================================================

def _now() -> datetime:
    """Current time, timezone-aware (UTC)."""
    return datetime.now(timezone.utc)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    """
    Normalise a stored datetime for comparison.

    SQLite (tests) returns naive datetimes; they were written as UTC, so
    attach UTC. PostgreSQL returns aware values which pass through unchanged.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    aware = _as_aware(value)
    return aware.isoformat() if aware else None


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _serialize(obj: Any, exclude: Sequence[str] = ()) -> Dict[str, Any]:
    """Column values of an ORM row as a JSON-safe dict."""
    out: Dict[str, Any] = {}
    skip = set(exclude)
    for column in obj.__table__.columns:
        if column.name in skip:
            continue
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            out[column.name] = _iso(value)
        elif isinstance(value, enum.Enum):
            # Python/SQLAlchemy enums -> their plain value
            out[column.name] = value.value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[column.name] = value
        else:
            out[column.name] = str(value)
    return out


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None or request.client is None:
        return None
    return request.client.host


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return request.headers.get("user-agent")


def _require_purposes(purposes: Any) -> List[str]:
    if not isinstance(purposes, list) or not purposes:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PURPOSES_REQUIRED",
                "message": "Provide a non-empty list of purposes to consent to.",
            },
        )
    unknown = [p for p in purposes if p not in AVAILABLE_PURPOSES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNKNOWN_PURPOSE",
                "message": f"Unknown purpose(s): {', '.join(sorted(map(str, unknown)))}",
                "known_purposes": sorted(AVAILABLE_PURPOSES),
            },
        )
    return sorted({str(p) for p in purposes})


# =======================================================
# Notice + data consent (DPDP notice & consent)
# =======================================================

def get_privacy_notice() -> Dict[str, Any]:
    """The notice itself: version, full text, purposes, rights, retention."""
    settings = get_settings()
    return {
        "version": settings.privacy_notice_version,
        "text": PRIVACY_NOTICE_TEXT,
        "purposes": AVAILABLE_PURPOSES,
        "rights": DATA_PRINCIPAL_RIGHTS,
        "retention": retention_policy(),
        "framework": "Digital Personal Data Protection Act, 2023 (India)",
    }


def _consent_out(consent: DataConsent) -> Dict[str, Any]:
    return {
        "id": consent.id,
        "notice_version": consent.notice_version,
        "purposes": _loads(consent.purposes, []),
        "granted": bool(consent.granted),
        "granted_at": _iso(consent.granted_at),
        "withdrawn_at": _iso(consent.withdrawn_at),
        "created_at": _iso(consent.created_at),
        "withdrawn": consent.withdrawn_at is not None,
    }


def list_data_consents(db: Session, user_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(DataConsent)
        .filter(DataConsent.user_id == user_id)
        .order_by(DataConsent.id.desc())
        .all()
    )
    return [_consent_out(row) for row in rows]


def record_data_consent(
    db: Session,
    user: User,
    purposes: Any,
    request: Optional[Request] = None,
) -> Tuple[Dict[str, Any], int]:
    """
    Record an explicit grant against the current notice version.

    Returns the consent payload and the id of the audit entry written for it.
    """
    purpose_keys = _require_purposes(purposes)
    settings = get_settings()
    now = _now()

    consent = DataConsent(
        user_id=user.id,
        notice_version=settings.privacy_notice_version,
        purposes=_dumps(purpose_keys),
        granted=True,
        granted_at=now,
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)

    audit = AuditService.log_action(
        db=db,
        user_id=user.id,
        action="grant_privacy_consent",
        resource="data_consent",
        resource_id=consent.id,
        details={
            "purposes": purpose_keys,
            "notice_version": settings.privacy_notice_version,
        },
        request=request,
    )
    return _consent_out(consent), audit.id


def withdraw_data_consent(
    db: Session,
    user: User,
    consent_id: int,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    """
    Withdraw consent (DPDP right to withdraw). The row is kept and stamped
    with ``withdrawn_at`` - withdrawal must never destroy the evidence of
    what was consented to.
    """
    consent = (
        db.query(DataConsent)
        .filter(DataConsent.id == consent_id, DataConsent.user_id == user.id)
        .first()
    )
    if consent is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONSENT_NOT_FOUND", "message": "Consent record not found."},
        )

    if consent.withdrawn_at is None:
        consent.withdrawn_at = _now()
        consent.granted = False
        db.commit()
        db.refresh(consent)
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="withdraw_privacy_consent",
            resource="data_consent",
            resource_id=consent.id,
            details={"purposes": _loads(consent.purposes, [])},
            request=request,
        )
    return _consent_out(consent)


# =======================================================
# Source consent (explicit, logged permission)
# =======================================================

def _source_consent_out(consent: SourceConsent) -> Dict[str, Any]:
    return {
        "id": consent.id,
        "source_id": consent.source_id,
        "source_title": consent.source_title,
        "access_type": consent.access_type,
        "scope": _loads(consent.scope, []),
        "permission": consent.permission,
        "granted_at": _iso(consent.granted_at),
        "revoked_at": _iso(consent.revoked_at),
        "expires_at": _iso(consent.expires_at),
        "created_at": _iso(consent.created_at),
        "expired": _is_expired(consent),
    }


def _is_expired(consent: SourceConsent) -> bool:
    expires_at = _as_aware(consent.expires_at)
    return expires_at is not None and expires_at <= _now()


def source_consent_out(consent: SourceConsent) -> Dict[str, Any]:
    """Public alias used by the source-registry router."""
    return _source_consent_out(consent)


def _resolve_source(source_id: str) -> Dict[str, Any]:
    """Look a connector up in the official-source registry."""
    entry = get_official_source(source_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SOURCE_NOT_FOUND",
                "message": f"No registered source with id '{source_id}'.",
            },
        )
    return entry


def log_source_access(
    db: Session,
    user_id: Optional[int],
    source_id: str,
    action: str,
    detail: Optional[str] = None,
    source_consent_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> SourceAccessLog:
    """Write one row to the source permission/access evidence trail."""
    row = SourceAccessLog(
        user_id=user_id,
        source_consent_id=source_consent_id,
        source_id=source_id,
        action=action,
        detail=detail,
        ip_address=_client_ip(request),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def grant_source_consent(
    db: Session,
    user: User,
    source_id: str,
    access_type: str,
    scope: Any,
    expires_in_days: Optional[int],
    request: Optional[Request] = None,
) -> Tuple[Dict[str, Any], int]:
    """
    Record explicit permission for one connector.

    Writes a ``SourceConsent(GRANTED)`` row, a ``SourceAccessLog
    (PERMISSION_GRANTED)`` row and a regular audit entry. The source must
    exist in the registry so permission can never be granted to an unknown
    connector.
    """
    entry = _resolve_source(source_id)

    allowed_types = {"PAID_SUBSCRIPTION", "THIRD_PARTY_API", "FREE"}
    if access_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ACCESS_TYPE",
                "message": f"access_type must be one of {sorted(allowed_types)}.",
            },
        )

    if not isinstance(scope, list) or not scope or not all(
        isinstance(item, str) and item.strip() for item in scope
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SCOPE_REQUIRED",
                "message": "scope must be a non-empty list of strings describing "
                "exactly which data you permit to be used.",
            },
        )

    settings = get_settings()
    days = expires_in_days if expires_in_days else settings.source_consent_default_days
    if days <= 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_EXPIRY",
                "message": "expires_in_days must be a positive number of days.",
            },
        )

    now = _now()
    consent = SourceConsent(
        user_id=user.id,
        source_id=source_id,
        source_title=entry["title"],
        access_type=access_type,
        scope=_dumps([item.strip() for item in scope]),
        permission="GRANTED",
        granted_at=now,
        expires_at=now + timedelta(days=days),
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)

    log_row = log_source_access(
        db=db,
        user_id=user.id,
        source_id=source_id,
        action="PERMISSION_GRANTED",
        detail=f"Permission granted for {entry['title']} ({len(scope)} scope item(s))",
        source_consent_id=consent.id,
        request=request,
    )

    audit = AuditService.log_action(
        db=db,
        user_id=user.id,
        action="grant_source_consent",
        resource="source_consent",
        resource_id=consent.id,
        details={
            "source_id": source_id,
            "access_type": access_type,
            "scope": list(scope),
            "expires_at": _iso(consent.expires_at),
            "access_log_id": log_row.id,
        },
        request=request,
    )
    return _source_consent_out(consent), audit.id


def list_source_consents(db: Session, user_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(SourceConsent)
        .filter(SourceConsent.user_id == user_id)
        .order_by(SourceConsent.id.desc())
        .all()
    )
    return [_source_consent_out(row) for row in rows]


def revoke_source_consent(
    db: Session,
    user: User,
    consent_id: int,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    """
    Revoke a permission the caller owns (DPDP withdrawal).

    Idempotent: revoking an already-revoked row is a no-op that still returns
    the row. Another user's row is a 404 so ids cannot be probed.
    """
    consent = (
        db.query(SourceConsent)
        .filter(SourceConsent.id == consent_id, SourceConsent.user_id == user.id)
        .first()
    )
    if consent is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONSENT_NOT_FOUND",
                "message": "Permission record not found.",
            },
        )

    if consent.permission != "REVOKED":
        consent.permission = "REVOKED"
        consent.revoked_at = _now()
        db.commit()
        db.refresh(consent)
        log_source_access(
            db=db,
            user_id=user.id,
            source_id=consent.source_id,
            action="PERMISSION_REVOKED",
            detail=f"Permission revoked by the data principal (consent id {consent.id})",
            source_consent_id=consent.id,
            request=request,
        )
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="revoke_source_consent",
            resource="source_consent",
            resource_id=consent.id,
            details={"source_id": consent.source_id},
            request=request,
        )
    return _source_consent_out(consent)


def effective_source_consent(
    db: Session, user_id: int, source_id: str
) -> Optional[SourceConsent]:
    """
    The caller's currently effective permission for a connector, or None.

    The most recent row decides. A granted row whose ``expires_at`` has
    passed is flipped to EXPIRED (and reported as no permission), so an
    expired permission cannot silently keep working.
    """
    latest = (
        db.query(SourceConsent)
        .filter(SourceConsent.user_id == user_id, SourceConsent.source_id == source_id)
        .order_by(SourceConsent.id.desc())
        .first()
    )
    if latest is None or latest.permission != "GRANTED":
        return None
    if _is_expired(latest):
        latest.permission = "EXPIRED"
        db.commit()
        db.refresh(latest)
        return None
    return latest


def list_source_access_log(
    db: Session, user_id: int, limit: int = 100
) -> List[Dict[str, Any]]:
    """The caller's own permission/access evidence trail."""
    rows = (
        db.query(SourceAccessLog)
        .filter(SourceAccessLog.user_id == user_id)
        .order_by(SourceAccessLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "source_consent_id": row.source_consent_id,
            "action": row.action,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def connector_handoff(db: Session, user: User, source_id: str,
                      request: Optional[Request] = None) -> Dict[str, Any]:
    """
    Consult consent first, then describe an honest HANDOFF to the source.

    Without an effective GRANTED permission this writes the blocking evidence
    (``ACCESS_BLOCKED_NO_PERMISSION`` + ``PERMISSION_DENIED``) and raises 403
    with a machine-readable body. With permission it writes
    ``ACCESS_ATTEMPTED`` then ``ACCESS_PERFORMED`` and returns the connector
    descriptor - ``mode: "HANDOFF"`` because this platform never fetches the
    source's data on the user's behalf.
    """
    entry = _resolve_source(source_id)
    consent = effective_source_consent(db, user.id, source_id)

    if consent is None:
        log_source_access(
            db=db,
            user_id=user.id,
            source_id=source_id,
            action="ACCESS_BLOCKED_NO_PERMISSION",
            detail="Access blocked: no effective GRANTED permission for this source.",
            request=request,
        )
        log_source_access(
            db=db,
            user_id=user.id,
            source_id=source_id,
            action="PERMISSION_DENIED",
            detail="Permission denied: consent missing, denied, revoked or expired.",
            request=request,
        )
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="source_access_blocked",
            resource="official_source",
            resource_id=None,
            details={"source_id": source_id, "reason": "no_permission"},
            request=request,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCESS_BLOCKED_NO_PERMISSION",
                "message": (
                    "No effective permission for this source. Grant it first with "
                    "POST /api/privacy/sources/consent (confirm: true)."
                ),
                "source_id": source_id,
                "grant_endpoint": "POST /api/privacy/sources/consent",
            },
        )

    log_source_access(
        db=db,
        user_id=user.id,
        source_id=source_id,
        action="ACCESS_ATTEMPTED",
        detail=f"Handoff requested for {entry['title']}",
        source_consent_id=consent.id,
        request=request,
    )

    performed = log_source_access(
        db=db,
        user_id=user.id,
        source_id=source_id,
        action="ACCESS_PERFORMED",
        detail="Handoff issued: the user opens the source themselves.",
        source_consent_id=consent.id,
        request=request,
    )

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="source_access_performed",
        resource="official_source",
        resource_id=None,
        details={
            "source_id": source_id,
            "mode": "HANDOFF",
            "access": entry["access"],
            "consent_id": consent.id,
        },
        request=request,
    )

    return {
        "source_id": entry["id"],
        "title": entry["title"],
        "authority": entry["authority"],
        "jurisdiction": entry["jurisdiction"],
        "access": entry["access"],
        "url": entry["url"],
        "requires_permission": entry["requires_permission"],
        "restricted_note": entry.get("restricted_note"),
        # Honest: no proxy, no scraping, no stored paid data.
        "mode": "HANDOFF",
        "data_fetched_by_platform": False,
        "instructions": (
            "Open the source URL yourself in your own subscription/session. "
            "This platform records your permission and the hand-off only; it "
            "does not fetch, proxy or store anything the source returns."
        ),
        "permission": _source_consent_out(consent),
        "access_log_id": performed.id,
    }


# =======================================================
# Export (DPDP access & portability)
# =======================================================

def _collect(query, cap: int) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Run a query capped at ``cap`` rows; return (records, total, truncated)."""
    total = query.count()
    rows = query.order_by().limit(cap).all()
    records = [_serialize(row) for row in rows]
    return records, total, total > cap


def build_export(db: Session, user: User) -> Dict[str, Any]:
    """
    Assemble everything the platform holds about ``user`` into one payload.

    Strictly owner-scoped: there is no user-id parameter, so an ADMIN cannot
    pull another data principal's export through this route - they only ever
    get their own.
    """
    settings = get_settings()
    cap = max(1, settings.export_max_items)

    # Owned products / versions
    products = db.query(Product).filter(Product.created_by == user.id)
    product_records, product_total, product_truncated = _collect(products, cap)

    versions = db.query(ProductVersion).filter(ProductVersion.created_by == user.id)
    version_records, version_total, version_truncated = _collect(versions, cap)
    version_ids = [row.id for row in versions.order_by(ProductVersion.id.asc()).all()]

    claims_q = db.query(Claim)
    evidence_q = db.query(Evidence)
    if version_ids:
        claims_q = claims_q.filter(Claim.product_version_id.in_(version_ids))
        evidence_q = evidence_q.filter(Evidence.product_version_id.in_(version_ids))
    else:
        claims_q = claims_q.filter(Claim.id == None)  # noqa: E711
        evidence_q = evidence_q.filter(Evidence.id == None)  # noqa: E711

    claim_records, claim_total, claim_truncated = _collect(claims_q, cap)
    evidence_records, evidence_total, evidence_truncated = _collect(evidence_q, cap)

    disclosures_q = db.query(Disclosure).filter(Disclosure.created_by == user.id)
    disclosure_records, disclosure_total, disclosure_truncated = _collect(
        disclosures_q, cap
    )

    reports_q = db.query(Report).filter(Report.created_by == user.id)
    report_records, report_total, report_truncated = _collect(reports_q, cap)

    # Conversations
    sessions_q = db.query(ChatSession).filter(ChatSession.user_id == user.id)
    session_records, session_total, session_truncated = _collect(sessions_q, cap)

    messages_q = (
        db.query(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .filter(ChatSession.user_id == user.id)
    )
    message_records, message_total, message_truncated = _collect(messages_q, cap)

    attachments_q = db.query(ChatAttachment).filter(ChatAttachment.user_id == user.id)
    attachment_records, attachment_total, attachment_truncated = _collect(
        attachments_q, cap
    )

    # Uploaded corpus documents (metadata only, no server file paths)
    uploads_q = db.query(SourceDocument).filter(SourceDocument.uploader_id == user.id)
    upload_rows = uploads_q.order_by(SourceDocument.id.asc()).limit(cap).all()
    upload_total = uploads_q.count()
    upload_records = [_serialize(row, exclude=("file_path",)) for row in upload_rows]

    # Evidence of processing: audit + consents + permission trail
    audit_q = db.query(AuditLog).filter(AuditLog.user_id == user.id)
    audit_rows = audit_q.order_by(AuditLog.id.asc()).limit(cap).all()
    audit_total = audit_q.count()
    audit_records = []
    for row in audit_rows:
        record = _serialize(row)
        record["details"] = _loads(row.details, None)
        audit_records.append(record)

    consents_q = db.query(DataConsent).filter(DataConsent.user_id == user.id)
    consent_records, consent_total, consent_truncated = _collect(consents_q, cap)

    source_consents_q = db.query(SourceConsent).filter(
        SourceConsent.user_id == user.id
    )
    source_consent_records, source_consent_total, source_consent_truncated = _collect(
        source_consents_q, cap
    )

    access_log_q = db.query(SourceAccessLog).filter(
        SourceAccessLog.user_id == user.id
    )
    access_log_records, access_log_total, access_log_truncated = _collect(
        access_log_q, cap
    )

    truncated = sorted(
        {
            name
            for name, flag in [
                ("products", product_truncated),
                ("product_versions", version_truncated),
                ("claims", claim_truncated),
                ("evidence", evidence_truncated),
                ("disclosures", disclosure_truncated),
                ("reports", report_truncated),
                ("chat_sessions", session_truncated),
                ("chat_messages", message_truncated),
                ("chat_attachments", attachment_truncated),
                ("uploaded_documents", upload_total > cap),
                ("audit_log", audit_total > cap),
                ("data_consents", consent_truncated),
                ("source_consents", source_consent_truncated),
                ("source_access_log", access_log_truncated),
            ]
            if flag
        }
    )

    return {
        "format": "ip-sakti-data-export/v1",
        "generated_at": _iso(_now()),
        "notice": {
            "version": settings.privacy_notice_version,
            "text": PRIVACY_NOTICE_TEXT,
        },
        "data_principal": {"user_id": user.id},
        "profile": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "created_at": _iso(user.created_at),
            "updated_at": _iso(user.updated_at),
            "roles": sorted(
                role.role.name.value
                if hasattr(role.role.name, "value")
                else str(role.role.name)
                for role in user.roles
            ),
        },
        "products": product_records,
        "product_versions": version_records,
        "claims": claim_records,
        "evidence": evidence_records,
        "disclosures": disclosure_records,
        "reports": report_records,
        "chat_sessions": session_records,
        "chat_messages": message_records,
        "chat_attachments": attachment_records,
        "uploaded_documents": upload_records,
        "audit_log": audit_records,
        "data_consents": consent_records,
        "source_consents": source_consent_records,
        "source_access_log": access_log_records,
        "counts": {
            "products": product_total,
            "product_versions": version_total,
            "claims": claim_total,
            "evidence": evidence_total,
            "disclosures": disclosure_total,
            "reports": report_total,
            "chat_sessions": session_total,
            "chat_messages": message_total,
            "chat_attachments": attachment_total,
            "uploaded_documents": upload_total,
            "audit_log": audit_total,
            "data_consents": consent_total,
            "source_consents": source_consent_total,
            "source_access_log": access_log_total,
        },
        "truncated": truncated,
        "export_max_items": cap,
        "notes": (
            "Owner-scoped export: it contains only your data. Audit details are "
            "already PII-redacted at write time, and uploaded document rows carry "
            "metadata only (no server file paths)."
        ),
    }


# =======================================================
# Erasure (DPDP right to erasure)
# =======================================================

def erase_account(
    db: Session, user: User, request: Optional[Request] = None
) -> Dict[str, Any]:
    """
    Erase the data principal's personal data.

    Anonymise, don't break: the user row survives with an anonymised email so
    foreign keys keep pointing somewhere, chat/upload/consent data is deleted,
    and audit rows are kept with ``user_id`` NULL so the trail survives
    without a personal identifier.

    Returns an honest summary of what was erased and what was retained.
    """
    uid = user.id
    erased: Dict[str, int] = {}
    retained: Dict[str, int] = {}

    # --- chat: attachments -> messages -> sessions ---------------------
    attachment_count = (
        db.query(ChatAttachment)
        .filter(ChatAttachment.user_id == uid)
        .delete(synchronize_session=False)
    )
    session_ids = [
        row[0]
        for row in db.query(ChatSession.id)
        .filter(ChatSession.user_id == uid)
        .all()
    ]
    message_count = 0
    if session_ids:
        message_count = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id.in_(session_ids))
            .delete(synchronize_session=False)
        )
        (
            db.query(ChatSession)
            .filter(ChatSession.id.in_(session_ids))
            .delete(synchronize_session=False)
        )
    erased["chat_messages"] = message_count
    erased["chat_sessions"] = len(session_ids)
    erased["chat_attachments"] = attachment_count

    # --- uploaded documents: rows + files on disk ----------------------
    upload_rows = (
        db.query(SourceDocument)
        .filter(SourceDocument.uploader_id == uid)
        .all()
    )
    upload_ids = [row.id for row in upload_rows]
    files_removed = 0
    if upload_ids:
        (
            db.query(SourceChunk)
            .filter(SourceChunk.document_id.in_(upload_ids))
            .delete(synchronize_session=False)
        )
        for row in upload_rows:
            if row.file_path and os.path.exists(row.file_path):
                try:
                    os.remove(row.file_path)
                    files_removed += 1
                except OSError:
                    pass
        (
            db.query(SourceDocument)
            .filter(SourceDocument.id.in_(upload_ids))
            .delete(synchronize_session=False)
        )
    erased["uploaded_documents"] = len(upload_ids)
    erased["uploaded_files_removed"] = files_removed

    # --- consents (the permission trail is anonymised, not destroyed) --
    erased["data_consents"] = (
        db.query(DataConsent)
        .filter(DataConsent.user_id == uid)
        .delete(synchronize_session=False)
    )
    erased["source_consents"] = (
        db.query(SourceConsent)
        .filter(SourceConsent.user_id == uid)
        .delete(synchronize_session=False)
    )

    # --- retained project records (they point at the anonymised account)
    retained["products"] = (
        db.query(Product).filter(Product.created_by == uid).count()
    )
    retained["reports"] = db.query(Report).filter(Report.created_by == uid).count()
    retained["disclosures"] = (
        db.query(Disclosure).filter(Disclosure.created_by == uid).count()
    )

    # Permission/access evidence keeps existing rows, loses the identifier.
    (
        db.query(SourceAccessLog)
        .filter(SourceAccessLog.user_id == uid)
        .update({SourceAccessLog.user_id: None}, synchronize_session=False)
    )
    erased["source_access_logs_anonymised"] = True

    # --- roles: the anonymised account keeps no privileges --------------
    (
        db.query(UserRole)
        .filter(UserRole.user_id == uid)
        .delete(synchronize_session=False)
    )
    erased["role_assignments"] = 1

    # --- anonymise the user row ----------------------------------------
    anonymised_email = f"deleted+{uid}@example.invalid"
    user.username = None
    user.email = anonymised_email
    user.password_hash = "erased"   # never a valid bcrypt hash again
    user.is_active = False

    # --- write the erasure evidence, then detach it from the identifier -
    AuditService.log_action(
        db=db,
        user_id=uid,
        action="data_erasure",
        resource="user",
        resource_id=uid,
        details={
            "action_label": "DataErasure",
            "erased": erased,
            "retained": retained,
            "user_ref": f"user:{uid}",
        },
        request=request,
    )
    retained["audit_logs"] = (
        db.query(AuditLog).filter(AuditLog.user_id == uid).count()
    )
    # Audit rows survive anonymised, exactly like the schema's SET NULL.
    (
        db.query(AuditLog)
        .filter(AuditLog.user_id == uid)
        .update({AuditLog.user_id: None}, synchronize_session=False)
    )
    retained["audit_logs_kept_with_user_id_null"] = retained["audit_logs"]

    db.commit()

    return {
        "erased": erased,
        "retained": retained,
        "anonymised_user": {
            "id": uid,
            "email": anonymised_email,
            "username": None,
            "is_active": False,
        },
        "notes": (
            "Your personal data was erased and the account anonymised. Audit "
            "entries and the source permission/access trail are retained with "
            "user_id NULL so the platform can still prove what happened, "
            "without identifying you."
        ),
    }


# =======================================================
# Retention + purge
# =======================================================

def _retention_entry(
    dataset: str, retention_days: int, note: str
) -> Dict[str, Any]:
    purgeable = retention_days > 0
    return {
        "dataset": dataset,
        "retention_days": retention_days,
        "action": "keep_forever" if not purgeable else f"purge_rows_older_than_{retention_days}_days",
        "purge_job_exists": purgeable,
        "purge_job": "manual_endpoint" if purgeable else "none",
        "automatic_purge_job": False,
        "purge_endpoint": "POST /api/privacy/purge (ADMIN)",
        "note": note,
    }


def retention_policy() -> Dict[str, Any]:
    """The configured retention policy, as data."""
    settings = get_settings()
    return {
        "notice_version": settings.privacy_notice_version,
        "datasets": [
            _retention_entry(
                "chat_messages_and_sessions",
                settings.chat_retention_days,
                "0 = keep until the user deletes the conversation.",
            ),
            _retention_entry(
                "uploaded_documents",
                settings.upload_retention_days,
                "0 = keep until the user deletes the document (file + rows).",
            ),
            _retention_entry(
                "audit_logs",
                settings.audit_retention_days,
                "0 = never purge (default): the audit trail is evidence.",
            ),
        ],
        "purge_job": {
            "exists": True,
            "kind": "manual",
            "scheduled": False,
            "endpoint": "POST /api/privacy/purge",
            "role": "ADMIN",
            "description": (
                "No background scheduler runs in this build: retention is applied "
                "on demand by an administrator through the purge endpoint. "
                "retention_days == 0 means that dataset is never purged."
            ),
        },
        "erasure": "DELETE /api/privacy/account (right to erasure, any time)",
        "framework": "Digital Personal Data Protection Act, 2023 (India)",
    }


def run_retention_purge(
    db: Session, request: Optional[Request] = None, actor_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Apply the configured retention windows. 0 days = never purge.

    Returns the per-dataset counts and writes an audit entry for the run.
    """
    settings = get_settings()
    now = _now()
    counts: Dict[str, Any] = {
        "chat_messages": 0,
        "chat_sessions": 0,
        "uploaded_documents": 0,
        "uploaded_files_removed": 0,
        "audit_logs": 0,
    }

    # --- chat ----------------------------------------------------------
    if settings.chat_retention_days > 0:
        cutoff = now - timedelta(days=settings.chat_retention_days)
        counts["chat_messages"] = (
            db.query(ChatMessage)
            .filter(ChatMessage.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        # Sessions with no messages left behind them are removable too.
        no_messages = (
            select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)
        ).exists()
        stale_sessions = (
            db.query(ChatSession)
            .filter(ChatSession.created_at < cutoff, ~no_messages)
        )
        stale_ids = [row[0] for row in stale_sessions.with_entities(ChatSession.id).all()]
        if stale_ids:
            (
                db.query(ChatSession)
                .filter(ChatSession.id.in_(stale_ids))
                .delete(synchronize_session=False)
            )
            counts["chat_sessions"] = len(stale_ids)

    # --- uploads -------------------------------------------------------
    if settings.upload_retention_days > 0:
        cutoff = now - timedelta(days=settings.upload_retention_days)
        stale = (
            db.query(SourceDocument)
            .filter(SourceDocument.created_at < cutoff)
            .all()
        )
        if stale:
            stale_ids = [row.id for row in stale]
            (
                db.query(SourceChunk)
                .filter(SourceChunk.document_id.in_(stale_ids))
                .delete(synchronize_session=False)
            )
            for row in stale:
                if row.file_path and os.path.exists(row.file_path):
                    try:
                        os.remove(row.file_path)
                        counts["uploaded_files_removed"] += 1
                    except OSError:
                        pass
            (
                db.query(SourceDocument)
                .filter(SourceDocument.id.in_(stale_ids))
                .delete(synchronize_session=False)
            )
            counts["uploaded_documents"] = len(stale)

    # --- audit ---------------------------------------------------------
    # 0 (the default) means the audit trail is never purged.
    if settings.audit_retention_days > 0:
        cutoff = now - timedelta(days=settings.audit_retention_days)
        counts["audit_logs"] = (
            db.query(AuditLog)
            .filter(AuditLog.timestamp < cutoff)
            .delete(synchronize_session=False)
        )

    db.commit()

    AuditService.log_action(
        db=db,
        user_id=actor_id,
        action="purge_retention",
        resource="retention_policy",
        resource_id=None,
        details={
            "counts": counts,
            "chat_retention_days": settings.chat_retention_days,
            "upload_retention_days": settings.upload_retention_days,
            "audit_retention_days": settings.audit_retention_days,
        },
        request=request,
    )

    return {
        "counts": counts,
        "policy": retention_policy(),
        "message": "Retention applied. Datasets with retention_days == 0 were not touched.",
    }
