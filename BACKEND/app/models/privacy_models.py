"""
DPDP-aligned privacy models for IP-SAKTI Sahayak.

Three tables cover the two mechanisms the problem statement asks for:

1. ``DataConsent``       - consent to the privacy notice and its processing
                           purposes (the DPDP "notice + consent" record).
2. ``SourceConsent``     - explicit, logged permission to use the user's own
                           paid subscription / third-party connector.
3. ``SourceAccessLog``   - the evidence trail for that permission: what was
                           granted, refused, revoked and accessed.

Design notes
------------
* Every personal-data table is FK'd to ``users.id`` with ``ondelete`` that
  keeps the audit trail intact: ``DataConsent``/``SourceConsent`` cascade with
  the account (they are personal data), while ``SourceAccessLog.user_id`` and
  ``source_consent_id`` are SET NULL so the log survives erasure without a
  personal identifier (mirroring ``AuditLog``).
* ``scope`` and ``purposes`` are JSON encoded in a Text column - the same
  convention the rest of the codebase uses (``details``, ``citations_json``),
  so the schema is portable between PostgreSQL and the SQLite test fixtures.
* Permission/action columns are plain ``String`` rather than SQL enums: the
  vocabulary is fixed in this module, and plain strings keep migrations
  cheap when the vocabulary grows.
"""
from __future__ import annotations

import enum
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


# -------------------------------------------------------
# Controlled vocabularies
# -------------------------------------------------------

class AccessType(str, enum.Enum):
    """What kind of connector the user is granting permission for."""

    PAID_SUBSCRIPTION = "PAID_SUBSCRIPTION"
    THIRD_PARTY_API = "THIRD_PARTY_API"
    FREE = "FREE"


class Permission(str, enum.Enum):
    """Lifecycle of a source permission (DPDP: grant / withdraw)."""

    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SourceAccessAction(str, enum.Enum):
    """Every event the source-access evidence trail records."""

    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    ACCESS_ATTEMPTED = "ACCESS_ATTEMPTED"
    ACCESS_BLOCKED_NO_PERMISSION = "ACCESS_BLOCKED_NO_PERMISSION"
    ACCESS_PERFORMED = "ACCESS_PERFORMED"


# -------------------------------------------------------
# DataConsent - privacy notice + purposes
# -------------------------------------------------------

class DataConsent(Base):
    """
    Consent to the privacy notice for a set of processing purposes.

    Rows are never deleted on withdrawal: ``withdrawn_at`` is set instead, so
    the record of what was consented to (and when it stopped) survives for
    auditability - which is what the DPDP regime expects of a data fiduciary.
    """

    __tablename__ = "data_consents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notice_version = Column(String(50), nullable=False)
    purposes = Column(Text, nullable=False)          # JSON list of purpose keys
    granted = Column(Boolean, nullable=False, default=False)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<DataConsent(id={self.id}, user_id={self.user_id}, "
            f"granted={self.granted})>"
        )


# -------------------------------------------------------
# SourceConsent - explicit permission for a connector
# -------------------------------------------------------

class SourceConsent(Base):
    """
    Explicit, logged permission to use one external source/connector.

    ``permission`` moves GRANTED -> REVOKED (user withdraws), EXPIRED
    (``expires_at`` passed) or DENIED (permission was refused).
    """

    __tablename__ = "source_consents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id = Column(String(100), nullable=False, index=True)
    source_title = Column(String(255), nullable=False)
    access_type = Column(String(50), nullable=False)
    scope = Column(Text, nullable=False)             # JSON list: what is permitted
    permission = Column(String(20), nullable=False, default="GRANTED")
    granted_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String(45), nullable=True)   # IPv6 compatible
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<SourceConsent(id={self.id}, user_id={self.user_id}, "
            f"source_id={self.source_id!r}, permission={self.permission})>"
        )


# -------------------------------------------------------
# SourceAccessLog - the "logged permission" evidence
# -------------------------------------------------------

class SourceAccessLog(Base):
    """
    Evidence trail for source permission and access events.

    ``user_id`` and ``source_consent_id`` are SET NULL (not CASCADE) so the
    trail survives account erasure without retaining a personal identifier -
    exactly how ``AuditLog`` behaves.
    """

    __tablename__ = "source_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_consent_id = Column(
        Integer,
        ForeignKey("source_consents.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id = Column(String(100), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<SourceAccessLog(id={self.id}, user_id={self.user_id}, "
            f"source_id={self.source_id!r}, action={self.action})>"
        )
