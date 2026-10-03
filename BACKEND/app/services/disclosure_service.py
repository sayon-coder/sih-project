"""
Disclosure service (Phase 8a).

Records immutable public-disclosure events pinned to one product version and
produces the advisory disclosure review. Every response carries the mandatory
disclaimers; the service never states a legal conclusion.

Safety rules carried over from earlier phases:
* advisory only - recording or reviewing never edits version content;
* version-pinned - an event belongs to exactly one version;
* ownership - all reads/writes go through ``get_accessible_product`` /
  ``get_accessible_version`` (ADMIN bypass), missing/forbidden is 404.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.disclosure_models import (
    INVENTION_DISCLOSURE_DISCLAIMER,
    PUBLIC_DISCLOSURE_DISCLAIMER,
    Disclosure,
    DisclosureType,
)
from app.services.audit_service import AuditService
from app.utils.authorization import (
    get_accessible_product,
    get_accessible_version,
    is_admin,
)


def _canonical_payload(
    product_id: int,
    product_version_id: int,
    disclosure_type: DisclosureType,
    description: str,
    venue_or_channel: Optional[str],
    disclosure_date: Optional[str],
    declarant_name: Optional[str],
    institution: Optional[str],
    created_by: int,
) -> Dict[str, Any]:
    """Canonical payload that the SHA-256 record hash covers."""
    return {
        "product_id": product_id,
        "product_version_id": product_version_id,
        "disclosure_type": disclosure_type.value,
        "description": description,
        "venue_or_channel": venue_or_channel,
        "disclosure_date": disclosure_date,
        "declarant_name": declarant_name,
        "institution": institution,
        "created_by": created_by,
    }


def compute_record_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON payload (sorted keys, compact)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize(d: Disclosure) -> Dict[str, Any]:
    """JSON-safe representation of one disclosure row."""
    dtype = d.disclosure_type
    return {
        "id": d.id,
        "product_id": d.product_id,
        "product_version_id": d.product_version_id,
        "disclosure_type": dtype.value if isinstance(dtype, DisclosureType) else str(dtype),
        "description": d.description,
        "venue_or_channel": d.venue_or_channel,
        "disclosure_date": d.disclosure_date,
        "declarant_name": d.declarant_name,
        "institution": d.institution,
        "record_hash": d.record_hash,
        "verification_id": d.verification_id,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "disclaimer": INVENTION_DISCLOSURE_DISCLAIMER,
    }


# Per-type review notes. Cautious wording only - considerations and questions,
# never conclusions about patentability, priority or infringement.
_TYPE_NOTES: Dict[str, Dict[str, List[str]]] = {
    "conference_presentation": {
        "considerations": [
            "A conference presentation may count as a public disclosure in some "
            "jurisdictions; the timing relative to any patent screening deserves review."
        ],
        "questions": [
            "Was the presented material limited to what is already recorded in this version?",
            "Should patent screening be re-run for this version before the presentation?",
        ],
    },
    "publication": {
        "considerations": [
            "A publication may make the disclosed content publicly available as of "
            "its publication date in some jurisdictions."
        ],
        "questions": [
            "Does the manuscript disclose anything beyond this version's recorded content?",
            "Should a registered patent agent review the draft before submission?",
        ],
    },
    "website": {
        "considerations": [
            "Website content is generally publicly accessible from the moment it is posted."
        ],
        "questions": [
            "Is the posted content limited to what is recorded in this version?",
        ],
    },
    "investor_disclosure": {
        "considerations": [
            "An investor disclosure shared without confidentiality terms may be "
            "treated as public in some jurisdictions."
        ],
        "questions": [
            "Was the disclosure made under a written confidentiality arrangement?",
        ],
    },
    "advertising": {
        "considerations": [
            "Advertising material describing the product or method may be publicly available."
        ],
        "questions": [
            "Does the advertising copy disclose technical detail beyond the recorded claims?",
        ],
    },
    "commercial_launch": {
        "considerations": [
            "A commercial launch generally makes the product publicly available."
        ],
        "questions": [
            "Is the launched product identical to what this version records?",
        ],
    },
    "other": {
        "considerations": [
            "Any sharing outside a confidential setting may be treated as public "
            "in some jurisdictions."
        ],
        "questions": [
            "Who received the information and under what terms?",
        ],
    },
}


class DisclosureService:
    """Create, read and review disclosure events."""

    @staticmethod
    def _unique_verification_id(db: Session) -> str:
        for _ in range(5):
            vid = secrets.token_hex(8)
            if not db.query(Disclosure).filter(Disclosure.verification_id == vid).first():
                return vid
        raise HTTPException(status_code=500, detail="Could not generate verification id")

    @staticmethod
    def create(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        disclosure_type: DisclosureType,
        description: str,
        venue_or_channel: Optional[str] = None,
        disclosure_date: Optional[str] = None,
        declarant_name: Optional[str] = None,
        institution: Optional[str] = None,
        request: Optional[Request] = None,
    ) -> Disclosure:
        get_accessible_version(db, product_id, version_id, user_id)
        if not description or not description.strip():
            raise HTTPException(status_code=422, detail="description must not be empty")
        payload = _canonical_payload(
            product_id,
            version_id,
            disclosure_type,
            description.strip(),
            venue_or_channel,
            disclosure_date,
            declarant_name,
            institution,
            user_id,
        )
        disclosure = Disclosure(
            product_id=product_id,
            product_version_id=version_id,
            disclosure_type=disclosure_type,
            description=description.strip(),
            venue_or_channel=venue_or_channel,
            disclosure_date=disclosure_date,
            declarant_name=declarant_name,
            institution=institution,
            record_hash=compute_record_hash(payload),
            verification_id=DisclosureService._unique_verification_id(db),
            created_by=user_id,
        )
        db.add(disclosure)
        db.commit()
        db.refresh(disclosure)
        AuditService.log_action(
            db,
            user_id,
            "create_disclosure",
            "disclosure",
            disclosure.id,
            {"product_id": product_id, "product_version_id": version_id},
            request,
        )
        return disclosure

    @staticmethod
    def list(db: Session, product_id: int, version_id: int, user_id: int) -> List[Disclosure]:
        get_accessible_version(db, product_id, version_id, user_id)
        return (
            db.query(Disclosure)
            .filter(
                Disclosure.product_id == product_id,
                Disclosure.product_version_id == version_id,
            )
            .order_by(Disclosure.created_at.desc(), Disclosure.id.desc())
            .all()
        )

    @staticmethod
    def get_global(db: Session, disclosure_id: int, user_id: int) -> Disclosure:
        """Fetch one disclosure by id; the caller must own its product (ADMIN bypass)."""
        disclosure = db.query(Disclosure).filter(Disclosure.id == disclosure_id).first()
        if disclosure is None:
            raise HTTPException(status_code=404, detail="Disclosure not found")
        get_accessible_product(db, disclosure.product_id, user_id)
        return disclosure

    @staticmethod
    def count_for_version(db: Session, version_id: int) -> int:
        return db.query(Disclosure).filter(Disclosure.product_version_id == version_id).count()

    @staticmethod
    def types_for_version(db: Session, version_id: int) -> List[str]:
        rows = (
            db.query(Disclosure.disclosure_type)
            .filter(Disclosure.product_version_id == version_id)
            .all()
        )
        out: List[str] = []
        for (dtype,) in rows:
            out.append(dtype.value if isinstance(dtype, DisclosureType) else str(dtype))
        return out

    @staticmethod
    def verify_payload(disclosure: Disclosure) -> Dict[str, Any]:
        """Public verification payload: stored hash, recomputed match flag, disclaimer."""
        dtype = disclosure.disclosure_type
        recomputed = compute_record_hash(
            _canonical_payload(
                disclosure.product_id,
                disclosure.product_version_id,
                dtype if isinstance(dtype, DisclosureType) else DisclosureType(str(dtype)),
                disclosure.description,
                disclosure.venue_or_channel,
                disclosure.disclosure_date,
                disclosure.declarant_name,
                disclosure.institution,
                disclosure.created_by,
            )
        )
        return {
            **serialize(disclosure),
            "hash_match": recomputed == disclosure.record_hash,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def review(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> Dict[str, Any]:
        """Advisory disclosure review for one version. Never a legal conclusion."""
        events = DisclosureService.list(db, product_id, version_id, user_id)
        if not events:
            return {
                "product_id": product_id,
                "product_version_id": version_id,
                "review_status": "NO_EVENTS_RECORDED",
                "event_count": 0,
                "event_types": [],
                "considerations": [
                    "No public-disclosure events are recorded for this version. "
                    "Record an event before any conference, publication, website "
                    "post, investor disclosure, advertising or launch."
                ],
                "review_questions": [
                    "Is any public disclosure planned for this version?",
                    "Should patent screening be completed before that disclosure?",
                ],
                "warnings": [PUBLIC_DISCLOSURE_DISCLAIMER],
                "disclaimer": INVENTION_DISCLOSURE_DISCLAIMER,
            }
        considerations: List[str] = []
        questions: List[str] = [
            "Should a registered patent agent review the disclosure timing for this version?",
            "Should patent screening be re-run for this version before any further disclosure?",
        ]
        seen_types: List[str] = []
        for event in events:
            t = event.disclosure_type
            key = t.value if isinstance(t, DisclosureType) else str(t)
            if key not in seen_types:
                seen_types.append(key)
            notes = _TYPE_NOTES.get(key, _TYPE_NOTES["other"])
            for c in notes["considerations"]:
                if c not in considerations:
                    considerations.append(c)
            for q in notes["questions"]:
                if q not in questions:
                    questions.append(q)
        return {
            "product_id": product_id,
            "product_version_id": version_id,
            "review_status": "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED",
            "event_count": len(events),
            "event_types": seen_types,
            "considerations": considerations,
            "review_questions": questions,
            "warnings": [PUBLIC_DISCLOSURE_DISCLAIMER],
            "disclaimer": INVENTION_DISCLOSURE_DISCLAIMER,
        }

    @staticmethod
    def is_owner_or_admin(db: Session, disclosure: Disclosure, user_id: int) -> None:
        """Raise 404 unless the caller owns the disclosure's product (ADMIN bypass)."""
        get_accessible_product(db, disclosure.product_id, user_id)
        if not is_admin(db, user_id) and disclosure.created_by != user_id:
            # Product is accessible but the row belongs to a collaborator path;
            # ownership of the product is sufficient for reads (same rule as
            # version content). Kept as a hook for stricter per-row rules later.
            pass
