"""
Immutable version snapshots and content hashes.

Every ProductVersion stores two integrity fields:

* ``snapshot_data`` - a canonical JSON document capturing the version's content
  (ingredients, formulation, claims, evidence, target markets) plus metadata.
* ``content_hash`` - the SHA-256 hash of the canonical content only.

The hash is computed over *content only* (not the version number), so cloning a
version produces the same hash until the content actually changes. That property
is what later phases use to detect real changes between versions.
"""
import enum
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import ProductVersion

# Bump when the snapshot document shape changes.
SNAPSHOT_SCHEMA_VERSION = 1


def _json_default(value: Any) -> str:
    """Serialize types SQLAlchemy returns that JSON does not know about."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # str() keeps exact precision, e.g. "4.000" instead of 4.0
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    return str(value)


def canonical_json(data: Dict[str, Any]) -> str:
    """Deterministic JSON (sorted keys, no incidental whitespace)."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def build_version_content(version: ProductVersion) -> Dict[str, Any]:
    """
    Extract the version's content as plain, deterministically ordered data.

    Collections are ordered by primary key so the same rows always hash to the
    same digest.
    """
    ingredients = sorted(version.ingredients, key=lambda row: row.id or 0)
    claims = sorted(version.claims, key=lambda row: row.id or 0)
    evidence = sorted(version.evidence, key=lambda row: row.id or 0)
    markets = sorted(version.target_markets, key=lambda row: row.id or 0)
    formulation = version.formulation

    return {
        "ingredients": [
            {
                "common_name": item.common_name,
                "botanical_name": item.botanical_name,
                "sanskrit_name": item.sanskrit_name,
                "plant_part": item.plant_part,
                "quantity": item.quantity,
                "quantity_unit": item.quantity_unit,
                "preparation_method": item.preparation_method,
                "source_type": item.source_type,
                "source_location": item.source_location,
                "source_documentation": item.source_documentation,
                "provenance": item.provenance,
            }
            for item in ingredients
        ],
        "formulation": None
        if formulation is None
        else {
            "process_description": formulation.process_description,
            "extraction_method": formulation.extraction_method,
            "solvent": formulation.solvent,
            "temperature": formulation.temperature,
            "temperature_unit": formulation.temperature_unit,
            "pressure": formulation.pressure,
            "pressure_unit": formulation.pressure_unit,
            "duration": formulation.duration,
            "duration_unit": formulation.duration_unit,
            "concentration": formulation.concentration,
            "other_parameters": formulation.other_parameters,
        },
        "claims": [
            {
                "claim_text": item.claim_text,
                "claim_type": item.claim_type,
                "evidence_status": item.evidence_status,
                "evidence_notes": item.evidence_notes,
                "risk_level": item.risk_level,
                "review_status": item.review_status,
                "provenance": item.provenance,
            }
            for item in claims
        ],
        "evidence": [
            {
                "title": item.title,
                "evidence_type": item.evidence_type,
                "file_path": item.file_path,
                "source_url": item.source_url,
                "doi": item.doi,
                "publication_date": item.publication_date,
                "language": item.language,
                "authors": item.authors,
                "verification_status": item.verification_status,
                "document_hash": item.document_hash,
                "provenance": item.provenance,
            }
            for item in evidence
        ],
        "target_markets": [
            {
                "country": item.country,
                "region": item.region,
                "regulatory_status": item.regulatory_status,
                "notes": item.notes,
            }
            for item in markets
        ],
    }


def compute_content_hash(content: Dict[str, Any]) -> str:
    """SHA-256 of the canonical content document."""
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def build_version_snapshot(version: ProductVersion) -> Dict[str, Any]:
    """Full snapshot document: metadata envelope + content + content hash."""
    content = build_version_content(version)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "product_id": version.product_id,
        "version_number": version.version_number,
        "change_reason": version.change_reason,
        "created_by": version.created_by,
        "content_hash": compute_content_hash(content),
        "content": content,
    }


def refresh_version_snapshot(db: Session, version: ProductVersion) -> ProductVersion:
    """
    Recompute and persist ``snapshot_data`` / ``content_hash`` for a version.

    Call this after any change to a version's content so the stored hash keeps
    matching the stored content.
    """
    snapshot = build_version_snapshot(version)
    version.snapshot_data = canonical_json(snapshot)
    version.content_hash = snapshot["content_hash"]
    db.commit()
    db.refresh(version)
    return version
