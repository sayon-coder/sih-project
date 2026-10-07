"""
Overall Product View - one stored-data aggregate for a Product Passport version.

``build_overview`` is the single source of truth for:

* the Overall Product View page (``GET .../versions/{id}/overview``), and
* the chatbot's product context (spec item 17: both must read the same data,
  so the page and the assistant can never present conflicting interpretations).

Everything is read from stored rows - passport fields, recorded analysis runs,
recorded screenings, recorded disclosures. Nothing is inferred, estimated or
invented:

* missing values are reported as missing (``Not provided`` / ``Not recorded``);
* patent records that are not verified public records are never returned - the
  platform has no live patent source, and demo-corpus rows must never be
  presented as real results;
* no status may ever read as approval, launch-readiness, clearance or
  compliance (see ``OVERVIEW_NOTICE`` and the closed status vocabularies).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.analysis.classifier import evaluate_classification_gaps
from app.analysis.ip_schemas import (
    DEMO_RECORD_LABEL,
    VERIFICATION_VERIFIED,
    record_verification_fields,
)
from app.analysis.schemas import UNRESOLVED_PATHWAYS
from app.models.analysis_models import Analysis, AnalysisStatus, AnalysisType
from app.models.disclosure_models import (
    Disclosure,
    INVENTION_DISCLOSURE_DISCLAIMER,
    PUBLIC_DISCLOSURE_DISCLAIMER,
)
from app.models.patent_models import PatentRecord
from app.models.product_models import Product, ProductVersion
from app.rag.jurisdiction_scope import (
    claim_standing,
    has_verified_evidence,
    market_display_label,
    missing_information_for,
)
from app.reports.builders import GENERAL_DISCLAIMER, PATENT_DISCLAIMER
from app.services.disclosure_service import (
    DisclosureService,
    serialize as serialize_disclosure,
)
from app.services.ip_service import IPService
from app.services.version_content import load_version_content
from app.services.version_snapshot import build_version_content
from app.config import get_settings
from app.utils.cache import cache, CACHED_MARKER

logger = logging.getLogger(__name__)


# ======================================================================
# Response cache: the overview is a pure stored-data aggregate (~12-15
# sequential queries). The key carries the full data revision - content
# hash plus the max row id of every run table - so a cache hit is never
# wrong by content, only older than the TTL. Writers invalidate the
# version prefix (analysis persist, disclosure create, patent-record
# write); content edits change the hash and miss automatically.
# ======================================================================

OVERVIEW_NAMESPACE = "overview"


def _overview_revision(db: Session, version_id: int) -> str:
    """Three indexed MAX lookups - milliseconds even on Supabase free."""
    try:
        max_a = db.query(func.max(Analysis.id)).filter(
            Analysis.product_version_id == version_id
        ).scalar() or 0
    except Exception:
        max_a = 0
    try:
        max_d = db.query(func.max(Disclosure.id)).filter(
            Disclosure.product_version_id == version_id
        ).scalar() or 0
    except Exception:
        max_d = 0
    try:
        max_p = db.query(func.max(PatentRecord.id)).filter(
            PatentRecord.product_version_id == version_id
        ).scalar() or 0
    except Exception:
        max_p = 0
    return f"a{max_a}d{max_d}p{max_p}"


def build_overview_cached(
    db: Session,
    product: Product,
    version: ProductVersion,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Cached front for :func:`build_overview` (same return shape + marker).

    The ``served_from_cache`` flag is honest metadata for the UI/debugging:
    True means this exact revision was built earlier inside the TTL window.
    """
    settings = get_settings()
    if not settings.cache_enabled:
        return build_overview(db, product, version, user_id=user_id)
    revision = _overview_revision(db, version.id)
    key = (
        f"{OVERVIEW_NAMESPACE}:v{version.id}:"
        f"h{version.content_hash or 'none'}:{revision}:u{user_id}"
    )
    hit = cache.get(key)
    if hit is not None:
        # Shallow copy: callers must never mutate the stored object.
        out = dict(hit)
        out[CACHED_MARKER] = True
        return out
    fresh = build_overview(db, product, version, user_id=user_id)
    fresh[CACHED_MARKER] = False
    cache.set(key, fresh, ttl=settings.cache_overview_ttl_seconds)
    return fresh


def invalidate_overview_cache(version_id: int) -> int:
    """Drop every cached overview for one version. Returns rows dropped."""
    return cache.invalidate_prefix(f"{OVERVIEW_NAMESPACE}:v{version_id}:")


# ======================================================================
# Closed vocabularies (spec items 3, 7, 10, 11). Nothing else is produced.
# ======================================================================

#: Overall status values the overview may show.
STATUS_COMPLETE_FOR_REVIEW = "COMPLETE_FOR_REVIEW"
STATUS_PARTIALLY_COMPLETE = "PARTIALLY_COMPLETE"
STATUS_INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
STATUS_ANALYSIS_NOT_RUN = "ANALYSIS_NOT_RUN"
STATUS_ANALYSIS_OUTDATED = "ANALYSIS_OUTDATED"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_NOT_ASSESSED = "NOT_ASSESSED"

#: Claim display statuses (spec item 7).
CLAIM_STATUS_SUPPORTED = "SUPPORTED_BY_ATTACHED_EVIDENCE"
CLAIM_STATUS_USER_PROVIDED = "USER_PROVIDED_ONLY"
CLAIM_STATUS_EVIDENCE_MISSING = "EVIDENCE_MISSING"
CLAIM_STATUS_EVIDENCE_REVIEW = "EVIDENCE_REVIEW_REQUIRED"
CLAIM_STATUS_SOURCE_BACKED = "SOURCE_BACKED"
CLAIM_STATUS_NOT_ASSESSED = "NOT_ASSESSED"

#: Biodiversity/ABS display statuses (spec item 11).
BIO_NOT_ASSESSED = "NOT_ASSESSED"
BIO_INFORMATION_MISSING = "INFORMATION_MISSING"
BIO_POTENTIALLY_RELEVANT = "POTENTIALLY_RELEVANT"
BIO_REVIEW_REQUIRED = "REVIEW_REQUIRED"
BIO_SOURCE_DOC_RECORDED = "SOURCE_DOCUMENTATION_RECORDED"

#: IP review statuses (spec item 10).
IP_NOT_ASSESSED = "NOT_ASSESSED"
IP_SEARCH_NOT_RUN = "SEARCH_NOT_RUN"
IP_SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"
IP_NO_RELEVANT_RECORD = "NO_RELEVANT_RECORD_IDENTIFIED"
IP_POTENTIALLY_RELEVANT = "POTENTIALLY_RELEVANT"
IP_FURTHER_REVIEW = "FURTHER_REVIEW_RECOMMENDED"
IP_VERIFIED_PUBLIC_RECORD = "VERIFIED_PUBLIC_RECORD"

#: Review priorities (spec item 10: never HIGH/MED/LOW "risk" labels).
PRIORITY_HIGHER = "Higher review priority"
PRIORITY_MODERATE = "Moderate review priority"
PRIORITY_LOWER = "Lower review priority"

NOT_PROVIDED = "Not provided"
NOT_RECORDED = "Not recorded"
NOT_INDEPENDENTLY_VERIFIED = "Not independently verified"


# ======================================================================
# Spec copy - exact sentences the UI and the chatbot must be able to show.
# ======================================================================

OVERVIEW_NOTICE = (
    "This overview reflects the selected Product Passport version and its "
    "recorded analysis results. It is preliminary decision support, not legal, "
    "patent, regulatory, medical, biodiversity, or government advice. It does "
    "not determine launch permission, patentability, infringement, approval, "
    "or ABS obligations."
)

ANALYSIS_OUTDATED_NOTICE = (
    "The product version has changed since this analysis was recorded. "
    "Re-run analysis before relying on the results."
)

NO_MARKET_EVIDENCE = (
    "No verified market-specific evidence is available for this section."
)

NO_PATENT_RESULT = (
    "No verified patent-search result is available for this version."
)

FEATURE_COMPARISON_DISCLAIMER = (
    "This feature comparison is not a patentability, novelty, validity, "
    "infringement, or freedom-to-operate opinion."
)

CLAIM_USER_PROVIDED_WARNING = (
    "This claim is recorded as user-provided. No independent supporting "
    "evidence is attached or verified in the selected version."
)

NO_EVIDENCE_DOCS = "No evidence documents are attached to this product version."

NO_DISCLOSURE_EVENT = "No public disclosure event is recorded for this version."

DISCLOSURE_ADVISORY = (
    "Consider professional IP review before public presentation, publication, "
    "investor disclosure, or commercial launch."
)

SOURCE_DOC_MISSING = "Source documentation not attached."

CLASSIFICATION_GAP_REASON = "Insufficient product and intended-use information."

TK_NO_SOURCE_NOTICE = (
    "No traditional-use source was supplied for this version. Restricted "
    "sources were not accessed or reproduced."
)

#: Spec item 11 reason for a POTENTIALLY_RELEVANT biodiversity review.
BIODIVERSITY_POTENTIALLY_RELEVANT_REASON = (
    "A biological resource with a recorded Indian source location is present "
    "in the product record. The current information is insufficient to "
    "determine whether any specific legal obligation, exemption, or "
    "documentation requirement applies."
)

BIODIVERSITY_POTENTIALLY_RELEVANT_REASON_GENERIC = (
    "A biological resource with a recorded source location is present in the "
    "product record. The current information is insufficient to determine "
    "whether any specific legal obligation, exemption, or documentation "
    "requirement applies."
)

#: Evidence is stored per version; the data model has no per-claim link.
CLAIM_EVIDENCE_LINKAGE_NOTE = (
    "Evidence is recorded for the product version. The data model has no "
    "per-claim evidence link, so every document below is shown for review."
)

MARKET_EVIDENCE_NOTE = (
    "Evidence is recorded at version level. No market-specific evidence link "
    "exists, so market evidence counts stay at zero until one is recorded."
)

#: Fields that do not exist anywhere in the product data model. They are
#: reported as missing for the biodiversity review (spec item 11) because the
#: product record genuinely does not hold them - nothing is invented.
BIODIVERSITY_STRUCTURALLY_MISSING = [
    "Exact supplier",
    "Access arrangement",
    "User/entity category",
    "Permits or declarations",
]

ANALYSIS_OUTDATED_RUN_NOTICE = (
    "OUTDATED - this run does not match the current product version."
)


# ======================================================================
# Small helpers
# ======================================================================

def _val(value: Any) -> Any:
    """Runtime value of an enum, or the value itself."""
    if isinstance(value, Enum):
        return value.value
    return value


def _plain(obj: Any) -> Any:
    """Recursively convert ORM/enum/date values into JSON-safe data."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime) or isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {key: _plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(item) for item in obj]
    return obj


def _iso(value: Any) -> Optional[str]:
    """ISO timestamp for a datetime, or None."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _text(value: Any) -> Optional[str]:
    """A trimmed string, or None when the value is absent/blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _num(value: Any) -> Optional[Any]:
    """A Decimal rendered as int/float for JSON (4.000 -> 4)."""
    if value is None:
        return None
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _num_display(value: Any, unit: Optional[str] = None, degree: bool = False) -> Optional[str]:
    """Human display of a recorded number, unit kept exactly as stored."""
    if isinstance(value, str) and not value.strip():
        return None
    number = _num(value)
    if number is None:
        return None
    if degree:
        return f"{number}\u00b0{unit or 'C'}"
    if unit:
        return f"{number} {unit}"
    return str(number)


def _field(value: Any, provenance: str, missing: str = NOT_PROVIDED) -> Dict[str, Any]:
    """One displayed value with its provenance (spec item 16)."""
    if value is None:
        return {"value": missing, "provenance": "NOT_PROVIDED"}
    if isinstance(value, str) and not value.strip():
        return {"value": missing, "provenance": "NOT_PROVIDED"}
    return {"value": value, "provenance": provenance}


def _item(key: str, label: str, value: Any, provenance: str, missing: str = NOT_PROVIDED) -> Dict[str, Any]:
    """A labelled field row: key, label, value, provenance."""
    return {"key": key, "label": label, **_field(value, provenance, missing)}


def _results(analysis: Optional[Analysis]) -> Dict[str, Any]:
    """Parsed ``results`` JSON of an analysis row ({} when absent/invalid)."""
    if analysis is None or not analysis.results:
        return {}
    try:
        data = json.loads(analysis.results)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_ref(analysis: Optional[Analysis]) -> Optional[Dict[str, Any]]:
    """Compact reference to one recorded analysis run."""
    if analysis is None:
        return None
    results = _results(analysis)
    return {
        "run_id": analysis.id,
        "analysis_type": _val(analysis.analysis_type),
        "status": _val(analysis.status),
        "timestamp": _iso(analysis.completed_at or analysis.created_at),
        "content_hash": results.get("content_hash"),
        "summary": analysis.summary,
    }


def _latest_completed(
    db: Session, version_id: int, analysis_type: Optional[AnalysisType] = None
) -> Optional[Analysis]:
    """Newest COMPLETED run for a version (optionally of one type)."""
    query = db.query(Analysis).filter(
        Analysis.product_version_id == version_id,
        Analysis.status == AnalysisStatus.COMPLETED,
    )
    if analysis_type is not None:
        query = query.filter(Analysis.analysis_type == analysis_type)
    return query.order_by(Analysis.created_at.desc(), Analysis.id.desc()).first()


def _latest_any(db: Session, version_id: int) -> Optional[Analysis]:
    """Newest run of any status (used for the header analysis status)."""
    return (
        db.query(Analysis)
        .filter(Analysis.product_version_id == version_id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .first()
    )


def _latest_classification(db: Session, version_id: int):
    """Newest completed run that recorded a preliminary classification."""
    rows = (
        db.query(Analysis)
        .filter(
            Analysis.product_version_id == version_id,
            Analysis.analysis_type.in_(
                [AnalysisType.COMPREHENSIVE, AnalysisType.PRODUCT_CLASSIFICATION]
            ),
            Analysis.status == AnalysisStatus.COMPLETED,
        )
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .all()
    )
    for analysis in rows:
        classification = _results(analysis).get("product_classification")
        if isinstance(classification, dict) and classification.get("category"):
            return analysis, classification
    return None, None


def _source_count(results: Dict[str, Any]) -> Optional[int]:
    """Sources a run actually used: citations, screening sources, records."""
    if not isinstance(results, dict):
        return None
    claim_review = results.get("claim_review")
    if isinstance(claim_review, dict) and claim_review.get("assessments"):
        return sum(len(a.get("citations") or []) for a in claim_review["assessments"])
    if results.get("assessments") is not None:
        return sum(len(a.get("citations") or []) for a in (results.get("assessments") or []))
    if results.get("sources") is not None:
        return len(results.get("sources") or [])
    if results.get("records") is not None:
        return len(results.get("records") or [])
    return None


def _has_resolved_classification(db: Session, version_id: int) -> bool:
    """True when a completed analysis recorded a RESOLVED classification."""
    _, classification = _latest_classification(db, version_id)
    if not classification:
        return False
    return bool(
        classification.get("category")
        and classification.get("status") != "UNRESOLVED"
    )


# ======================================================================
# Section builders
# ======================================================================

def _product_block(product: Product, version: ProductVersion) -> Dict[str, Any]:
    """Selected product version identity (spec item 2)."""
    owner = None
    try:
        if product.created_by_user is not None:
            owner = product.created_by_user.username
    except Exception:  # pragma: no cover - relationship may be detached
        owner = None
    return {
        "id": product.id,
        "name": product.name,
        "version": version.version_number,
        "version_id": version.id,
        "content_hash": version.content_hash,
        "created_at": _iso(version.created_at),
        # ProductVersion carries no update timestamp; reported honestly.
        "updated_at": None,
        "updated_at_note": "This version has no separate update timestamp.",
        "product_updated_at": _iso(product.updated_at),
        "owner": owner,
    }


def _facts_block(
    product: Product,
    content: Dict[str, Any],
    market_count: int,
    disclosure_count: int,
    owner: Optional[str],
) -> Dict[str, Any]:
    """Product Facts (spec item 4) - saved data only, missing shown honestly."""
    ingredients = content.get("ingredients") or []
    claims = content.get("claims") or []
    evidence = content.get("evidence") or []

    sources: List[str] = []
    for ingredient in ingredients:
        source_type = _text(_val(ingredient.get("source_type")))
        location = _text(ingredient.get("source_location"))
        label = " - ".join(part for part in (source_type, location) if part)
        if label and label not in sources:
            sources.append(label)

    fields = [
        _item("common_product_name", "Common product name", product.name, "USER_PROVIDED"),
        _item("product_name", "Product / brand name", product.name, "USER_PROVIDED"),
        # No intended-use / brand / dosage-form / manufacturing columns exist
        # anywhere in the data model: reported as missing, never inferred.
        _item("intended_use", "Intended use", None, "NOT_PROVIDED"),
        _item(
            "product_category",
            "Product category",
            _val(product.category),
            "USER_PROVIDED",
        ),
        _item("dosage_form", "Dosage form", None, "NOT_PROVIDED"),
        _item("manufacturing_status", "Manufacturing status", None, "NOT_PROVIDED"),
        _item("owner", "Owner / organisation", owner, "USER_PROVIDED"),
        _item("product_description", "Product description", product.description, "USER_PROVIDED"),
        _item(
            "source_information",
            "Source information",
            "; ".join(sources) if sources else None,
            "USER_PROVIDED",
        ),
        _item("ingredient_count", "Ingredient count", len(ingredients), "SYSTEM_DERIVED"),
        _item("claim_count", "Claim count", len(claims), "SYSTEM_DERIVED"),
        _item("evidence_count", "Evidence count", len(evidence), "SYSTEM_DERIVED"),
        _item("target_market_count", "Target-market count", market_count, "SYSTEM_DERIVED"),
        _item(
            "disclosure_event_count",
            "Disclosure-event count",
            disclosure_count,
            "SYSTEM_DERIVED",
        ),
    ]
    return {"fields": fields}


def _formulation_block(
    formulation: Any, ingredients: List[Any]
) -> Dict[str, Any]:
    """Formulation and Process (spec item 5) - stored fields with provenance."""
    fields: List[Dict[str, Any]] = []
    if formulation is None:
        values: Dict[str, Any] = {}
        provenance = "NOT_PROVIDED"
    else:
        values = {
            "process_description": _text(formulation.process_description),
            "extraction_method": _text(formulation.extraction_method),
            "solvent": _text(formulation.solvent),
            "temperature": _num_display(
                formulation.temperature, formulation.temperature_unit, degree=True
            ),
            "pressure": _num_display(formulation.pressure, formulation.pressure_unit),
            "duration": _num_display(formulation.duration, formulation.duration_unit),
            "concentration": _num_display(formulation.concentration),
            # No standardisation column exists on Formulation.
            "standardisation": None,
            "other_parameters": _text(formulation.other_parameters),
        }
        provenance = "USER_PROVIDED"

    for key, label in (
        ("process_description", "Process description"),
        ("extraction_method", "Extraction method"),
        ("solvent", "Solvent"),
        ("temperature", "Temperature"),
        ("pressure", "Pressure"),
        ("duration", "Duration"),
        ("concentration", "Concentration"),
        ("standardisation", "Standardisation"),
        ("other_parameters", "Other parameters"),
    ):
        field_provenance = provenance if values.get(key) is not None else "NOT_PROVIDED"
        fields.append(_item(key, label, values.get(key), field_provenance))

    # Ingredient source status/location (spec item 5 example).
    source_status = None
    source_location = None
    for ingredient in ingredients:
        source_status = source_status or _text(_val(ingredient.get("source_type")))
        source_location = source_location or _text(ingredient.get("source_location"))
    source_summary = [
        _item("source_status", "Source status", source_status, "USER_PROVIDED"),
        _item("source_location", "Source location", source_location, "USER_PROVIDED"),
    ]
    return {
        "present": formulation is not None,
        "fields": fields,
        "source_summary": source_summary,
    }


def _ingredients_block(ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ingredients and source (spec item 6) - one row per stored ingredient."""
    out: List[Dict[str, Any]] = []
    for ingredient in ingredients:
        quantity = ingredient.get("quantity")
        unit = _text(ingredient.get("quantity_unit"))
        quantity_display = None
        if quantity is not None:
            quantity_display = f"{_num(quantity)} {unit}".strip() if unit else str(_num(quantity))
        documentation = _text(ingredient.get("source_documentation"))
        row_provenance = _text(ingredient.get("provenance")) or "USER_PROVIDED"
        out.append(
            {
                "id": ingredient.get("id"),
                "provenance": row_provenance,
                "fields": [
                    _item("common_name", "Common name", _text(ingredient.get("common_name")), row_provenance),
                    _item(
                        "botanical_name",
                        "Botanical name",
                        _text(ingredient.get("botanical_name")),
                        row_provenance,
                    ),
                    _item(
                        "sanskrit_name",
                        "Sanskrit name",
                        _text(ingredient.get("sanskrit_name")),
                        row_provenance,
                    ),
                    _item("plant_part", "Plant part", _text(ingredient.get("plant_part")), row_provenance),
                    _item("quantity", "Quantity", quantity_display, row_provenance),
                    _item(
                        "source_status",
                        "Source status",
                        _text(_val(ingredient.get("source_type"))),
                        row_provenance,
                    ),
                    _item(
                        "source_location",
                        "Source location",
                        _text(ingredient.get("source_location")),
                        row_provenance,
                    ),
                    _item("supplier", "Supplier", None, "NOT_PROVIDED"),
                    _item("ingredient_provenance", "Provenance", row_provenance, row_provenance),
                    _item(
                        "documentation_status",
                        "Documentation status",
                        documentation,
                        "USER_PROVIDED",
                        missing=SOURCE_DOC_MISSING,
                    ),
                ],
            }
        )
    return out


#: Claim evidence-status mapping onto the spec item 7 vocabulary.
_CLAIM_STATUS_MAP = {
    "EVIDENCE_ON_RECORD": CLAIM_STATUS_SUPPORTED,
    "SUPPORTED": CLAIM_STATUS_SUPPORTED,
    "SUPPORTED_BY_ATTACHED_EVIDENCE": CLAIM_STATUS_SUPPORTED,
    "USER_PROVIDED": CLAIM_STATUS_USER_PROVIDED,
    "USER_PROVIDED_ONLY": CLAIM_STATUS_USER_PROVIDED,
    "NEEDS_EVIDENCE": CLAIM_STATUS_EVIDENCE_MISSING,
    "EVIDENCE_MISSING": CLAIM_STATUS_EVIDENCE_MISSING,
    "PARTIALLY_SUPPORTED": CLAIM_STATUS_EVIDENCE_REVIEW,
    "EVIDENCE_REVIEW_REQUIRED": CLAIM_STATUS_EVIDENCE_REVIEW,
    "EXPERT_VERIFIED": CLAIM_STATUS_SOURCE_BACKED,
    "SOURCE_BACKED": CLAIM_STATUS_SOURCE_BACKED,
}


def _map_claim_status(value: Optional[str]) -> str:
    if not value:
        return CLAIM_STATUS_NOT_ASSESSED
    return _CLAIM_STATUS_MAP.get(str(value).upper(), CLAIM_STATUS_NOT_ASSESSED)


def _marketing_status(independent_verification: Optional[str]) -> str:
    """Spec item 7 marketing line for a claim's verification state."""
    state = str(independent_verification or "").upper()
    if state == "EXPERT_VERIFIED":
        return "PROFESSIONAL REVIEW RECOMMENDED"
    if state in ("EVIDENCE_ON_RECORD", "SOURCE_CHECKED"):
        return "REVIEW REQUIRED"
    return "DO NOT PRESENT AS VERIFIED"


def _review_status(column_status: Any, review_required: bool) -> str:
    """Spec item 7 review status for one claim."""
    if review_required:
        return "REVIEW_REQUIRED"
    column = str(column_status or "pending").lower()
    if column == "reviewed":
        return "REVIEWED"
    if column == "rejected":
        return "CHANGES_REQUESTED"
    return "REVIEW_REQUIRED"


def _claims_block(
    claims: List[Any],
    plain_content: Dict[str, Any],
    markets: List[Any],
    evidence: List[Any],
    assessments: Dict[int, Dict[str, Any]],
    assessment_runs: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Claims and evidence (spec item 7), linked to the recorded analysis."""
    verified = has_verified_evidence(plain_content)
    market_countries = [m.country for m in markets if m.country]
    linked_evidence = [
        {
            "id": item.id,
            "title": item.title,
            "verification_status": _val(item.verification_status),
        }
        for item in evidence
    ]
    out: List[Dict[str, Any]] = []
    for claim, plain in zip(claims, plain_content.get("claims") or []):
        standing = claim_standing(plain, verified)
        assessment = assessments.get(claim.id)
        if assessment:
            evidence_status = assessment.get("evidence_status") or standing.get("evidence_status")
            independent = (
                assessment.get("independent_verification")
                or standing.get("independent_verification")
            )
            review_required = bool(assessment.get("review_required", standing.get("review_required")))
            reason = assessment.get("reason") or standing.get("reason")
            claim_provenance = (
                assessment.get("claim_provenance")
                or _val(claim.provenance)
                or "USER_PROVIDED"
            )
            linked_analysis = assessment_runs.get(claim.id)
        else:
            evidence_status = standing.get("evidence_status")
            independent = standing.get("independent_verification")
            review_required = bool(standing.get("review_required"))
            reason = standing.get("reason")
            claim_provenance = _val(claim.provenance) or "USER_PROVIDED"
            linked_analysis = None

        mapped = _map_claim_status(evidence_status)
        if mapped == CLAIM_STATUS_USER_PROVIDED:
            warning = CLAIM_USER_PROVIDED_WARNING
        else:
            warning = None
        out.append(
            {
                "id": claim.id,
                "claim_text": claim.claim_text,
                "claim_type": _val(claim.claim_type),
                "provenance": claim_provenance,
                "evidence_status": mapped,
                "recorded_evidence_status": _val(claim.evidence_status),
                "independent_verification": independent or "NOT_FOUND",
                "review_required": review_required,
                "review_status": _review_status(claim.review_status, review_required),
                "marketing_status": _marketing_status(independent),
                "reason": reason,
                "markets_affected": market_countries,
                "linked_evidence": linked_evidence,
                "evidence_linkage": CLAIM_EVIDENCE_LINKAGE_NOTE
                if linked_evidence
                else NO_EVIDENCE_DOCS,
                "warning": warning,
                "last_updated": _iso(claim.updated_at),
                "linked_analysis": linked_analysis,
                "provenance_label": "ANALYSIS_DERIVED" if linked_analysis else "NOT_VERIFIED",
            }
        )
    return out


def _evidence_block(evidence: List[Any]) -> List[Dict[str, Any]]:
    """Evidence documents recorded on the version (spec item 7)."""
    return [
        {
            "id": item.id,
            "title": item.title,
            "evidence_type": _val(item.evidence_type),
            "verification_status": _val(item.verification_status),
            "provenance": item.provenance or "USER_PROVIDED",
            "source_url": item.source_url,
            "doi": item.doi,
            "publication_date": item.publication_date.isoformat()
            if isinstance(item.publication_date, date)
            else item.publication_date,
            "created_at": _iso(item.created_at),
        }
        for item in evidence
    ]


def _markets_block(
    markets: List[Any],
    comp: Dict[str, Any],
    missing_information: List[str],
) -> Dict[str, Any]:
    """Target markets (spec item 8) - separated from ingredient source."""
    rows: List[Dict[str, Any]] = []
    for market in markets:
        rows.append(
            {
                "country": market.country,
                "region": _text(market.region) or NOT_PROVIDED,
                "regulatory_status": _field(
                    _text(market.regulatory_status), "USER_PROVIDED", missing=NOT_RECORDED
                ),
                "market_evidence_count": 0,
                "market_evidence_note": MARKET_EVIDENCE_NOTE,
                "market_specific_review_status": NOT_RECORDED,
                "last_review_date": NOT_RECORDED,
            }
        )

    considerations = {
        str(item.get("country") or "").strip().lower(): item
        for item in (comp.get("market_considerations") or [])
        if isinstance(item, dict)
    }
    sections: List[Dict[str, Any]] = []
    seen: List[str] = []
    for market in markets:
        country = market.country
        if not country or country.lower() in seen:
            continue
        seen.append(country.lower())
        consideration = considerations.get(country.lower()) or {}
        has_analysis = bool(comp)
        sections.append(
            {
                # Spec item 8: subsection headings are "INDIA" and "GERMANY/EU".
                "label": market_display_label(country).upper(),
                "country": country,
                "declared_regulatory_status": _text(market.regulatory_status) or NOT_RECORDED,
                "status": "REVIEW_REQUIRED" if has_analysis else "ANALYSIS_NOT_RUN",
                "consideration": consideration.get("consideration"),
                "sources_used": [],
                "evidence_note": NO_MARKET_EVIDENCE,
                "missing_information": list(missing_information),
                "review_questions": list(consideration.get("review_questions") or []),
                "next_action": (
                    "Review the recorded market consideration with a qualified "
                    "professional before relying on it."
                    if has_analysis
                    else "Run analysis for a market-specific review."
                ),
            }
        )
    return {"count": len(rows), "markets": rows, "sections": sections}


def _classification_block(
    product: Product,
    classification: Optional[Dict[str, Any]],
    ingredients: List[Any],
    claims: List[Any],
    run: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Regulatory classification (spec item 9) - never a final decision."""
    cosmetic_signal = str(_val(product.category) or "") == "possible_cosmetic" or any(
        _val(claim.claim_type) == "cosmetic" for claim in claims
    )

    if classification:
        status = str(classification.get("status") or "UNRESOLVED")
        confidence = str(classification.get("confidence") or "LOW").upper()
        category = classification.get("category")
        if status == "UNRESOLVED":
            confidence = CONFIDENCE_LOW
            reason = CLASSIFICATION_GAP_REASON
        else:
            reason = _text(classification.get("rationale")) or CLASSIFICATION_GAP_REASON
        missing = list(classification.get("missing_information") or [])
        pathways = list(classification.get("possible_categories") or [])
        review_required = bool(classification.get("review_required", True))
        source = "ANALYSIS_DERIVED"
        candidate = category
    else:
        status = "UNRESOLVED"
        confidence = CONFIDENCE_LOW
        missing, resolved = evaluate_classification_gaps(ingredients, claims)
        # Spec item 9: while the recorded information is incomplete the reason is
        # the spec's sentence; only a fully-recorded product that has never been
        # analysed gets the "no analysis" wording.
        reason = (
            CLASSIFICATION_GAP_REASON
            if not resolved
            else "No classification analysis has been recorded for this version."
        )
        pathways = []
        review_required = True
        source = "NOT_ASSESSED"
        candidate = None
        run = None

    if not missing:
        missing, _resolved = evaluate_classification_gaps(ingredients, claims)
    if not pathways:
        pathways = list(UNRESOLVED_PATHWAYS)
    if cosmetic_signal and "possible_cosmetic" not in pathways:
        pathways.append("possible_cosmetic")

    display = "UNRESOLVED" if status == "UNRESOLVED" else candidate
    return {
        "status": status,
        "classification": display,
        "candidate_category": candidate,
        "confidence": confidence,
        "reason": reason,
        "review_required": review_required,
        "rationale": _text(classification.get("rationale")) if classification else None,
        "possible_pathways": pathways,
        "missing_information": missing,
        "source": source,
        "analysis_run": run,
        "possible_pathways_note": (
            "Candidate pathways for review only; no pathway is selected or "
            "approved here."
        ),
    }


def _patent_record_block(record: PatentRecord) -> Dict[str, Any]:
    """One stored record - only ever called for verified public records."""
    base = IPService.record_to_result(record)
    features = base.get("features") or []
    band = str(record.similarity_band or "none").lower()
    priority = {
        "high": PRIORITY_HIGHER,
        "medium": PRIORITY_MODERATE,
    }.get(band, PRIORITY_LOWER)
    label = str(record.relevance_label or "").lower()
    if "further review" in label:
        priority = PRIORITY_HIGHER
    return {
        **base,
        "priority_date": NOT_RECORDED,
        "retrieval_date": _iso(record.created_at),
        "priority": priority,
        "matched_features": [f for f in features if f.get("verdict") == "match"],
        "different_features": [f for f in features if f.get("verdict") == "different"],
        "unknown_features": [f for f in features if f.get("verdict") == "unknown"],
        "why_included": _text(record.source_passage)
        or (
            "Included by the screening because recorded features overlap with "
            f"this version ({record.relevance_label}, similarity band "
            f"{record.similarity_band})."
        ),
        "features_disclaimer": FEATURE_COMPARISON_DISCLAIMER,
    }


def _ip_block(db: Session, version: ProductVersion, patent_run: Optional[Analysis]) -> Dict[str, Any]:
    """IP and prior-art review (spec item 10) - verified records only."""
    rows = (
        db.query(PatentRecord)
        .filter(PatentRecord.product_version_id == version.id)
        .order_by(PatentRecord.similarity.desc(), PatentRecord.id.asc())
        .all()
    )
    verified_rows: List[PatentRecord] = []
    synthetic_count = 0
    for row in rows:
        verification = record_verification_fields(row.record_source, bool(row.is_demo))
        if verification["verification_status"] == VERIFICATION_VERIFIED:
            verified_rows.append(row)
        else:
            synthetic_count += 1

    results = _results(patent_run)
    if patent_run is None and not rows:
        status = IP_SEARCH_NOT_RUN
        reason = "No patent screening has been recorded for this version."
        notice = NO_PATENT_RESULT
    elif not verified_rows:
        status = IP_SEARCH_UNAVAILABLE
        reason = (
            NO_PATENT_RESULT
            + " Screening results on record come from a clearly labelled "
            "demonstration corpus, not a live patent database."
        )
        notice = NO_PATENT_RESULT
    else:
        labels = [str(row.relevance_label or "").lower() for row in verified_rows]
        if any("further review" in label for label in labels):
            status = IP_FURTHER_REVIEW
        elif any("potentially relevant" in label or "overlap" in label for label in labels):
            status = IP_POTENTIALLY_RELEVANT
        else:
            status = IP_NO_RELEVANT_RECORD
        reason = (
            f"{len(verified_rows)} verified public record(s) are on record "
            "for this version and require review."
        )
        notice = None

    records = [_patent_record_block(row) for row in verified_rows]
    run = _run_ref(patent_run)
    if isinstance(run, dict) and isinstance(results, dict):
        run["live_search_performed"] = bool(results.get("live_search_performed"))
        run["corpus_type"] = results.get("corpus_type") or "DEMO_CORPUS"

    return {
        "status": status,
        "reason": reason,
        "notice": notice,
        "run": run,
        "records": records,
        "record_count": len(records),
        "synthetic_records_omitted": synthetic_count,
        "demo_notice": DEMO_RECORD_LABEL if synthetic_count else None,
        "features_disclaimer": FEATURE_COMPARISON_DISCLAIMER if records else None,
        "provenance": "SOURCE_BACKED" if records else "NOT_VERIFIED",
    }


def _map_biodiversity_status(raw: str, collected: Dict[str, Any]) -> str:
    """Map a stored screening status onto the spec item 11 vocabulary."""
    if raw == "POTENTIALLY_RELEVANT":
        return BIO_POTENTIALLY_RELEVANT
    if raw == "ADDITIONAL_INFORMATION_NEEDED":
        return BIO_INFORMATION_MISSING
    if raw == "REVIEW_RECOMMENDED":
        return BIO_REVIEW_REQUIRED
    # NO_IMMEDIATE_CONSIDERATION_IDENTIFIED
    if collected.get("source_documentation"):
        return BIO_SOURCE_DOC_RECORDED
    return BIO_NOT_ASSESSED


def _biodiversity_block(bio_run: Optional[Analysis]) -> Dict[str, Any]:
    """Biodiversity/ABS review (spec item 11) from the recorded screening."""
    if bio_run is None:
        return {
            "status": BIO_NOT_ASSESSED,
            "screening_status": None,
            "status_label": "Not assessed",
            "reason": "Biodiversity/ABS screening has not been recorded for this version.",
            "potential_considerations": [],
            "missing_information": [],
            "review_questions": [],
            "missing_fields": list(BIODIVERSITY_STRUCTURALLY_MISSING),
            "collected": {},
            "sources": [],
            "run": None,
        }

    results = _results(bio_run)
    raw = str(results.get("status") or "ADDITIONAL_INFORMATION_NEEDED")
    collected = results.get("collected") or {}
    status = _map_biodiversity_status(raw, collected)
    considerations = list(results.get("potential_considerations") or [])

    origins = [
        str(origin)
        for origin in (collected.get("origins") or [])
        if isinstance(origin, str) and origin.strip()
    ]
    indian_origin = any("india" in origin.lower() for origin in origins)
    if status == BIO_POTENTIALLY_RELEVANT:
        reason = (
            BIODIVERSITY_POTENTIALLY_RELEVANT_REASON
            if indian_origin
            else BIODIVERSITY_POTENTIALLY_RELEVANT_REASON_GENERIC
        )
    else:
        reason = considerations[0] if considerations else (
            "The recorded screening did not identify a conclusion; review the "
            "considerations below with a qualified professional."
        )

    missing_fields = list(BIODIVERSITY_STRUCTURALLY_MISSING)
    if not collected.get("source_documentation"):
        missing_fields.append("Cultivation documents")
    if not collected.get("associated_knowledge"):
        missing_fields.append("Associated knowledge")

    return {
        "status": status,
        "screening_status": raw,
        "status_label": results.get("status_label"),
        "reason": reason,
        "potential_considerations": considerations,
        "missing_information": list(results.get("missing_information") or []),
        "review_questions": list(results.get("review_questions") or []),
        "missing_fields": missing_fields,
        "collected": collected,
        "sources": list(results.get("sources") or []),
        "run": _run_ref(bio_run),
    }


def _traditional_knowledge_block(tk_run: Optional[Analysis]) -> Dict[str, Any]:
    """Traditional-knowledge review (spec item 12) - never implies TKDL access."""
    if tk_run is None:
        return {
            "status": "NOT_ASSESSED",
            "status_label": "Not assessed",
            "traditional_use_recorded": "NOT_PROVIDED",
            "source_supplied": "NOT_PROVIDED",
            "public_source_status": NOT_PROVIDED,
            "restricted_source_status": NOT_PROVIDED,
            "reason": "Traditional-knowledge screening has not been recorded for this version.",
            "notice": None,
            "potential_considerations": [],
            "missing_information": [],
            "review_questions": [],
            "sources": [],
            "restricted_sources_excluded": [],
            "run": None,
        }

    results = _results(tk_run)
    raw = str(results.get("status") or "ADDITIONAL_INFORMATION_NEEDED")
    collected = results.get("collected") or {}
    sources = list(results.get("sources") or [])
    considerations = list(results.get("potential_considerations") or [])

    documented = collected.get("publicly_documented_traditional_use")
    if documented is True:
        public_status = "PUBLICLY_DOCUMENTED"
    elif documented is False:
        public_status = "NO_PUBLIC_SOURCE_RETRIEVED"
    else:
        public_status = "NOT_ESTABLISHED"

    # ``sources`` always contains the registry reference listings (including
    # TKDL, listed as restricted and never accessed). A traditional-use source
    # was only *supplied* for this version when the screening actually
    # retrieved one from the accessible corpus.
    corpus_found = int(collected.get("corpus_sources_found") or 0)
    registry_listed = max(len(sources) - corpus_found, 0)
    traditional_use = "YES" if collected.get("tk_involvement") else "NO"
    source_supplied = "YES" if corpus_found else "NO"
    restricted = list(collected.get("restricted_sources_excluded") or [])

    return {
        "status": raw,
        "status_label": results.get("status_label"),
        "traditional_use_recorded": traditional_use,
        "source_supplied": source_supplied,
        "corpus_sources_found": corpus_found,
        "registry_sources_listed": registry_listed,
        "public_source_status": public_status,
        "restricted_source_status": "NOT_ACCESSED" if restricted else NOT_RECORDED,
        "reason": considerations[0] if considerations else results.get("summary"),
        "notice": TK_NO_SOURCE_NOTICE if source_supplied == "NO" else None,
        "potential_considerations": considerations,
        "missing_information": list(results.get("missing_information") or []),
        "review_questions": list(results.get("review_questions") or []),
        "sources": sources,
        "sources_note": (
            "Reference sources listed by the screening (registry entries plus "
            "any corpus source retrieved for this version). A registry entry "
            "is a listing only - nothing outside the recorded corpus "
            "retrieval was accessed."
        ),
        "restricted_sources_excluded": restricted,
        "run": _run_ref(tk_run),
    }


def _disclosures_block(
    db: Session, product: Product, version: ProductVersion, user_id: Optional[int]
) -> Dict[str, Any]:
    """Public disclosure review (spec item 13)."""
    if user_id is not None:
        events = DisclosureService.list(db, product.id, version.id, user_id)
        review = DisclosureService.review(db, product.id, version.id, user_id)
    else:
        events = (
            db.query(Disclosure)
            .filter(Disclosure.product_version_id == version.id)
            .order_by(Disclosure.created_at.desc(), Disclosure.id.desc())
            .all()
        )
        review = {
            "review_status": "NO_EVENTS_RECORDED" if not events else "NOT_REVIEWED",
            "event_count": len(events),
            "considerations": [],
            "review_questions": [],
            "warnings": [],
            "disclaimer": INVENTION_DISCLOSURE_DISCLAIMER,
        }

    return {
        "event_count": len(events),
        "review_status": review.get("review_status"),
        "events": [serialize_disclosure(event) for event in events],
        "notice": NO_DISCLOSURE_EVENT if not events else None,
        "advisory": DISCLOSURE_ADVISORY,
        "considerations": list(review.get("considerations") or []),
        "review_questions": list(review.get("review_questions") or []),
        "warnings": list(review.get("warnings") or []),
        "disclaimer": review.get("disclaimer") or INVENTION_DISCLOSURE_DISCLAIMER,
    }


def _history_block(db: Session, version_id: int, current_hash: Optional[str]) -> List[Dict[str, Any]]:
    """Analysis history (spec item 14), newest first."""
    rows = (
        db.query(Analysis)
        .filter(Analysis.product_version_id == version_id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .all()
    )
    history: List[Dict[str, Any]] = []
    for row in rows:
        results = _results(row)
        content_hash = results.get("content_hash")
        if content_hash is None or current_hash is None:
            hash_matches: Optional[bool] = None
        else:
            hash_matches = content_hash == current_hash
        claim_review = results.get("claim_review")
        claims_analysed = None
        if isinstance(claim_review, dict):
            claims_analysed = claim_review.get("claim_count")
        elif results.get("claim_count") is not None:
            claims_analysed = results.get("claim_count")
        markets_analysed = (
            len(results.get("market_considerations") or [])
            if results.get("market_considerations") is not None
            else None
        )
        missing_count = (
            len(results.get("missing_information") or [])
            if results.get("missing_information") is not None
            else None
        )
        history.append(
            {
                "run_id": row.id,
                "analysis_type": _val(row.analysis_type),
                "status": _val(row.status),
                "timestamp": _iso(row.completed_at or row.created_at),
                "product_version_id": row.product_version_id,
                "content_hash": content_hash,
                "current_version_hash": current_hash,
                "hash_matches": hash_matches,
                "outdated": hash_matches is False,
                "outdated_notice": ANALYSIS_OUTDATED_RUN_NOTICE
                if hash_matches is False
                else None,
                "summary": row.summary,
                "source_count": _source_count(results),
                "claims_analysed": claims_analysed,
                "markets_analysed": markets_analysed,
                "missing_information_count": missing_count,
            }
        )
    return history


# ======================================================================
# Overall status + recommended actions (deterministic, stored data only)
# ======================================================================

def _overall_status(
    latest_done: Optional[Analysis],
    analysis_hash: Optional[str],
    current_hash: Optional[str],
    analysis_outdated: bool,
    missing_required: List[str],
    review_triggers: List[str],
    soft_gaps: List[str],
    last_analysis_at: Optional[str],
) -> Dict[str, Any]:
    """Overall status card (spec item 3) from the actual stored record."""
    if latest_done is None:
        status = STATUS_ANALYSIS_NOT_RUN
        confidence = CONFIDENCE_NOT_ASSESSED
        reason = "No completed analysis has been recorded for this version."
    elif analysis_outdated:
        status = STATUS_ANALYSIS_OUTDATED
        confidence = CONFIDENCE_LOW
        reason = ANALYSIS_OUTDATED_NOTICE
    elif missing_required:
        status = STATUS_INSUFFICIENT_INFORMATION
        confidence = CONFIDENCE_LOW
        reason = " ".join(missing_required)
    elif review_triggers:
        status = STATUS_REVIEW_REQUIRED
        confidence = CONFIDENCE_MEDIUM
        reason = " ".join(review_triggers)
    elif soft_gaps:
        status = STATUS_PARTIALLY_COMPLETE
        confidence = CONFIDENCE_MEDIUM
        reason = " ".join(soft_gaps)
    else:
        status = STATUS_COMPLETE_FOR_REVIEW
        confidence = CONFIDENCE_HIGH
        reason = (
            "Required information is recorded, every claim has attached "
            "verified evidence and no review items are outstanding."
        )
    return {
        "status": status,
        "confidence": confidence,
        "reason": reason,
        "analysis_outdated": analysis_outdated,
        "last_analysis": last_analysis_at,
        "analysis_version_hash": analysis_hash,
        "current_version_hash": current_hash,
        "outdated_notice": ANALYSIS_OUTDATED_NOTICE if analysis_outdated else None,
        "missing_required": list(missing_required),
        "review_triggers": list(review_triggers),
        "soft_gaps": list(soft_gaps),
    }


def _recommended_actions(
    product: Product,
    content: Dict[str, Any],
    classification: Dict[str, Any],
    ip: Dict[str, Any],
    biodiversity: Dict[str, Any],
    traditional: Dict[str, Any],
    disclosures: Dict[str, Any],
    overall: Dict[str, Any],
    claims: List[Dict[str, Any]],
    formulation: Any,
    verified_evidence: bool,
) -> List[Dict[str, Any]]:
    """Recommended actions (spec item 15) derived from actual gaps only."""
    actions: List[Dict[str, Any]] = []
    version_link = f"/products/{product.id}/versions/{content.get('version_id')}"
    product_link = f"/products/{product.id}/versions"

    def add(
        action_id: str,
        title: str,
        priority: str,
        reason: str,
        section: str,
        link: str,
    ) -> None:
        actions.append(
            {
                "id": action_id,
                "title": title,
                "priority": priority,
                "reason": reason,
                "section": section,
                "status": "OPEN",
                "link": link,
            }
        )

    status = overall.get("status")
    if status == STATUS_ANALYSIS_NOT_RUN:
        add(
            "run_analysis",
            "Run analysis",
            "HIGH",
            "No completed analysis has been recorded for this version.",
            "analysis_history",
            version_link,
        )
    elif status == STATUS_ANALYSIS_OUTDATED:
        add(
            "rerun_analysis",
            "Re-run analysis",
            "HIGH",
            ANALYSIS_OUTDATED_NOTICE,
            "analysis_history",
            version_link,
        )

    if product.category is None:
        add(
            "confirm_product_category",
            "Confirm product category",
            "HIGH",
            "The product category is not recorded, so the regulatory "
            "classification stays unresolved.",
            "regulatory_classification",
            product_link,
        )

    if classification.get("status") == "UNRESOLVED":
        missing = [str(item) for item in classification.get("missing_information") or []]
        if "intended use" in missing:
            add(
                "add_intended_use",
                "Add intended use",
                "HIGH",
                "Intended use is not recorded, so the regulatory classification "
                "stays unresolved.",
                "regulatory_classification",
                product_link,
            )
        if "dosage form" in missing:
            add(
                "add_dosage_form",
                "Add dosage form",
                "HIGH",
                "Dosage form is not recorded, so the regulatory classification "
                "stays unresolved.",
                "regulatory_classification",
                product_link,
            )

    ingredients = content.get("ingredients") or []
    markets = content.get("target_markets") or []
    claims_orm = content.get("claims") or []
    evidence_orm = content.get("evidence") or []

    if not ingredients:
        add(
            "add_ingredients",
            "Add ingredients",
            "HIGH",
            "No ingredients are recorded for this version.",
            "ingredients",
            version_link,
        )
    if not markets:
        add(
            "add_target_markets",
            "Add target markets",
            "HIGH",
            "No target markets are recorded for this version.",
            "target_markets",
            version_link,
        )

    if claims_orm and not verified_evidence:
        add(
            "attach_claim_evidence",
            "Attach claim-supporting evidence",
            "HIGH",
            f"{len(claims_orm)} claim(s) are recorded without independently "
            "verified supporting evidence.",
            "claims_and_evidence",
            version_link,
        )

    if formulation is None or any(
        getattr(formulation, key) in (None, "")
        for key in ("solvent", "pressure", "duration", "concentration")
    ):
        add(
            "complete_formulation",
            "Complete formulation fields",
            "MEDIUM",
            "One or more formulation and process fields are not provided "
            "(solvent, pressure, duration, concentration).",
            "formulation_and_process",
            version_link,
        )

    if not evidence_orm and claims_orm:
        add(
            "record_evidence",
            "Record evidence documents",
            "MEDIUM",
            NO_EVIDENCE_DOCS,
            "claims_and_evidence",
            version_link,
        )

    bio_status = biodiversity.get("status")
    if bio_status == BIO_NOT_ASSESSED:
        add(
            "run_biodiversity_screen",
            "Run biodiversity/ABS screening",
            "MEDIUM",
            "Biodiversity/ABS screening has not been recorded for this version.",
            "biodiversity_abs",
            version_link,
        )
    elif bio_status == BIO_INFORMATION_MISSING:
        add(
            "complete_biodiversity_information",
            "Add biodiversity/ABS source details",
            "MEDIUM",
            "Biodiversity/ABS information is incomplete for this version.",
            "biodiversity_abs",
            version_link,
        )
    elif bio_status in (BIO_POTENTIALLY_RELEVANT, BIO_REVIEW_REQUIRED):
        add(
            "biodiversity_review",
            "Obtain biodiversity/ABS review",
            "MEDIUM",
            biodiversity.get("reason") or "Biodiversity/ABS review is outstanding.",
            "biodiversity_abs",
            version_link,
        )

    tk_status = traditional.get("status")
    if tk_status is None or tk_status == "NOT_ASSESSED":
        add(
            "run_traditional_knowledge_screen",
            "Run traditional-knowledge screening",
            "MEDIUM",
            "Traditional-knowledge screening has not been recorded for this "
            "version.",
            "traditional_knowledge",
            version_link,
        )
    elif tk_status == "ADDITIONAL_INFORMATION_NEEDED":
        add(
            "add_traditional_use_information",
            "Add traditional-use information",
            "MEDIUM",
            "No traditional-use information was supplied for this version.",
            "traditional_knowledge",
            version_link,
        )
    elif tk_status in ("REVIEW_RECOMMENDED", "POTENTIALLY_RELEVANT"):
        add(
            "review_traditional_knowledge",
            "Review traditional-knowledge source",
            "MEDIUM",
            traditional.get("reason")
            or "Traditional-knowledge review is outstanding.",
            "traditional_knowledge",
            version_link,
        )

    ip_status = ip.get("status")
    if ip_status in (IP_SEARCH_NOT_RUN, IP_SEARCH_UNAVAILABLE):
        add(
            "verified_patent_search",
            "Run verified patent search",
            "MEDIUM",
            NO_PATENT_RESULT,
            "ip_review",
            version_link,
        )
    elif ip_status in (IP_POTENTIALLY_RELEVANT, IP_FURTHER_REVIEW):
        add(
            "review_ip_records",
            "Review identified IP records",
            "HIGH",
            ip.get("reason") or "Identified IP records require review.",
            "ip_review",
            version_link,
        )

    if disclosures.get("event_count"):
        add(
            "review_disclosures",
            "Obtain expert review for recorded disclosures",
            "MEDIUM",
            "Public disclosure events are recorded for this version. "
            + DISCLOSURE_ADVISORY,
            "disclosures",
            version_link,
        )

    if any(claim.get("review_required") for claim in claims) or classification.get(
        "status"
    ) == "UNRESOLVED":
        add(
            "obtain_expert_review",
            "Obtain expert review",
            "MEDIUM",
            "Claims or the regulatory classification require qualified "
            "professional review.",
            "recommended_actions",
            "/reviews",
        )

    if not _text(product.description):
        add(
            "add_product_description",
            "Add product description",
            "LOW",
            "No product description is recorded for this product.",
            "product_facts",
            product_link,
        )

    return actions


def _section_provenance(
    facts: Dict[str, Any],
    formulation_block: Dict[str, Any],
    ingredients: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    markets: Dict[str, Any],
    classification: Dict[str, Any],
    ip: Dict[str, Any],
    biodiversity: Dict[str, Any],
    traditional: Dict[str, Any],
    disclosures: Dict[str, Any],
) -> Dict[str, List[str]]:
    """Which provenance layers contributed to each section (spec item 16)."""

    def collect(rows: List[Dict[str, Any]]) -> List[str]:
        values = sorted({row.get("provenance") for row in rows if row.get("provenance")})
        return values

    market_provenance = ["USER_PROVIDED"] if markets.get("count") else ["NOT_PROVIDED"]
    bio_provenance = ["ANALYSIS_DERIVED"] if biodiversity.get("run") else ["NOT_PROVIDED"]
    tk_provenance = ["ANALYSIS_DERIVED"] if traditional.get("run") else ["NOT_PROVIDED"]
    disclosure_provenance = (
        ["USER_PROVIDED", "ANALYSIS_DERIVED"] if disclosures.get("event_count") else ["NOT_PROVIDED"]
    )
    return {
        "facts": collect(facts.get("fields") or []),
        "formulation": collect(formulation_block.get("fields") or []),
        "ingredients": sorted(
            {row.get("provenance") for row in ingredients if row.get("provenance")}
        )
        or ["NOT_PROVIDED"],
        "claims": sorted({row.get("provenance") for row in claims if row.get("provenance")})
        or ["NOT_PROVIDED"],
        "evidence": sorted({row.get("provenance") for row in evidence if row.get("provenance")})
        or ["NOT_PROVIDED"],
        "target_markets": market_provenance,
        "regulatory_classification": [classification.get("source") or "NOT_PROVIDED"],
        "ip_review": [ip.get("provenance") or "NOT_VERIFIED"],
        "biodiversity_abs_review": bio_provenance,
        "traditional_knowledge_review": tk_provenance,
        "disclosures": disclosure_provenance,
        "analysis_history": ["ANALYSIS_DERIVED"],
        "recommended_actions": ["SYSTEM_DERIVED"],
    }


# ======================================================================
# Public API
# ======================================================================

def build_overview(
    db: Session,
    product: Product,
    version: ProductVersion,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the Overall Product View for one selected product version.

    Every value comes from stored rows for *this* version - sections never
    mix data from another version, and nothing is generated as a placeholder.
    """
    content = load_version_content(db, version)
    plain_content = _plain(build_version_content(version))

    ingredients = content["ingredients"]
    formulation = content["formulation"]
    claims = content["claims"]
    evidence = content["evidence"]
    markets = content["markets"]

    history = _history_block(db, version.id, version.content_hash)
    latest_any = _latest_any(db, version.id)
    latest_done = _latest_completed(db, version.id)
    analysis_hash = next(
        (
            entry["content_hash"]
            for entry in history
            if entry["status"] == AnalysisStatus.COMPLETED.value
            and entry["content_hash"]
        ),
        None,
    )
    analysis_outdated = bool(
        analysis_hash and version.content_hash and analysis_hash != version.content_hash
    )
    last_analysis_at = next(
        (entry["timestamp"] for entry in history if entry["status"] == AnalysisStatus.COMPLETED.value),
        None,
    )

    comp_analysis = _latest_completed(db, version.id, AnalysisType.COMPREHENSIVE)
    comp = _results(comp_analysis)
    claim_analysis = _latest_completed(db, version.id, AnalysisType.CLAIM_ANALYSIS)
    patent_run = _latest_completed(db, version.id, AnalysisType.PATENT_SCREENING)
    bio_run = _latest_completed(db, version.id, AnalysisType.BIODIVERSITY_SCREENING)
    tk_run = _latest_completed(db, version.id, AnalysisType.TK_SCREENING)
    classification_run, classification_raw = _latest_classification(db, version.id)

    has_resolved = _has_resolved_classification(db, version.id)
    missing_information = missing_information_for(plain_content, has_resolved)
    verified_evidence = has_verified_evidence(plain_content)

    # Claim assessments from the newest run that recorded them.
    assessments: Dict[int, Dict[str, Any]] = {}
    assessment_runs: Dict[int, Dict[str, Any]] = {}
    for run in sorted(
        [row for row in (claim_analysis, comp_analysis) if row is not None],
        key=lambda row: (
            row.created_at.isoformat() if row.created_at else "",
            row.id or 0,
        ),
        reverse=True,
    ):
        if run is None:
            continue
        results = _results(run)
        claim_review = results.get("claim_review") or results
        entries = claim_review.get("assessments") or []
        run_ref = _run_ref(run)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            claim_id = entry.get("claim_id")
            if claim_id is None or claim_id in assessments:
                continue
            assessments[claim_id] = entry
            assessment_runs[claim_id] = run_ref

    disclosures = _disclosures_block(db, product, version, user_id)
    product_block = _product_block(product, version)

    facts = _facts_block(
        product,
        plain_content,
        len(markets),
        disclosures["event_count"],
        product_block.get("owner"),
    )
    formulation_block = _formulation_block(formulation, plain_content.get("ingredients") or [])
    ingredients_block = _ingredients_block(plain_content.get("ingredients") or [])
    evidence_block = _evidence_block(evidence)
    claims_block = _claims_block(
        claims, plain_content, markets, evidence, assessments, assessment_runs
    )
    markets_block = _markets_block(markets, comp, missing_information)
    classification_block = _classification_block(
        product, classification_raw, ingredients, claims, _run_ref(classification_run)
    )
    ip = _ip_block(db, version, patent_run)
    biodiversity = _biodiversity_block(bio_run)
    traditional = _traditional_knowledge_block(tk_run)

    # ---- overall status inputs (spec item 3) --------------------------
    missing_required: List[str] = []
    if product.category is None:
        missing_required.append("The product category is not recorded.")
    if not ingredients:
        missing_required.append("No ingredients are recorded.")
    if not markets:
        missing_required.append("No target markets are recorded.")
    if claims and not evidence:
        missing_required.append("Evidence is absent where claims require support.")

    review_triggers: List[str] = []
    if claims and not verified_evidence:
        review_triggers.append("Claims require substantiation.")
    if ip["status"] in (IP_POTENTIALLY_RELEVANT, IP_FURTHER_REVIEW):
        review_triggers.append("IP screening identified records requiring review.")
    if biodiversity["status"] in (BIO_INFORMATION_MISSING, BIO_REVIEW_REQUIRED):
        review_triggers.append("Biodiversity/ABS information is incomplete.")
    if traditional["status"] == "ADDITIONAL_INFORMATION_NEEDED":
        review_triggers.append("Traditional-knowledge information is incomplete.")
    elif traditional["status"] in ("REVIEW_RECOMMENDED", "POTENTIALLY_RELEVANT"):
        review_triggers.append("Traditional-knowledge review is outstanding.")
    if classification_block["status"] == "UNRESOLVED":
        review_triggers.append("Regulatory classification is unresolved.")
    if disclosures.get("review_status") == "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED":
        review_triggers.append("Public disclosure may affect IP strategy.")

    soft_gaps: List[str] = []
    if formulation is None or any(
        getattr(formulation, key) in (None, "")
        for key in ("solvent", "pressure", "duration", "concentration")
    ):
        soft_gaps.append("Formulation and process fields are incomplete.")
    if any(
        not _text(item.get("source_documentation"))
        for item in (plain_content.get("ingredients") or [])
    ):
        soft_gaps.append("Source documentation is not attached for every ingredient.")
    if not evidence:
        soft_gaps.append(NO_EVIDENCE_DOCS)

    overall = _overall_status(
        latest_done,
        analysis_hash,
        version.content_hash,
        analysis_outdated,
        missing_required,
        review_triggers,
        soft_gaps,
        last_analysis_at,
    )

    analysis_block = {
        "status": _val(latest_any.status) if latest_any else "NOT_RUN",
        "run_id": latest_any.id if latest_any else None,
        "analysis_type": _val(latest_any.analysis_type) if latest_any else None,
        "timestamp": _iso(
            (latest_any.completed_at or latest_any.created_at) if latest_any else None
        ),
        "content_hash": analysis_hash,
        "current_version_hash": version.content_hash,
        "outdated": analysis_outdated,
        "completed_runs": sum(1 for entry in history if entry["status"] == "completed"),
    }

    recommended_actions = _recommended_actions(
        product,
        {**plain_content, "version_id": version.id},
        classification_block,
        ip,
        biodiversity,
        traditional,
        disclosures,
        overall,
        claims_block,
        formulation,
        verified_evidence,
    )

    provenance = _section_provenance(
        facts,
        formulation_block,
        ingredients_block,
        claims_block,
        evidence_block,
        markets_block,
        classification_block,
        ip,
        biodiversity,
        traditional,
        disclosures,
    )

    disclaimers = [OVERVIEW_NOTICE, GENERAL_DISCLAIMER]
    if ip.get("run") or ip.get("records"):
        disclaimers.append(PATENT_DISCLAIMER)
    if disclosures.get("event_count"):
        disclaimers.append(PUBLIC_DISCLOSURE_DISCLAIMER)

    return {
        "product": product_block,
        "analysis": analysis_block,
        "overall_status": overall,
        "facts": facts,
        "formulation": formulation_block,
        "ingredients": ingredients_block,
        "claims": claims_block,
        "evidence": evidence_block,
        "target_markets": markets_block,
        "regulatory_classification": classification_block,
        "ip_review": ip,
        "biodiversity_abs_review": biodiversity,
        "traditional_knowledge_review": traditional,
        "disclosures": disclosures,
        "analysis_history": history,
        "recommended_actions": recommended_actions,
        "missing_information": missing_information,
        "provenance": provenance,
        "disclaimers": disclaimers,
    }


def overview_context_for_chat(
    db: Session, product: Product, version: ProductVersion
) -> Optional[dict]:
    """Compact Overall Product View facts for the chatbot prompt (item 17).

    The assistant and the page read the same aggregate, so the chatbot can
    never present a separate, conflicting interpretation of the product.
    Patent record details are deliberately omitted: the platform's stored
    screening records are not verified live results and must never be quoted
    as if they were.
    """
    try:
        overview = build_overview_cached(db, product, version, user_id=None)
    except Exception as exc:  # pragma: no cover - defensive: chat must not fail
        logger.warning("Could not build overview context for chat: %s", exc)
        return None
    overall = overview["overall_status"]
    classification = overview["regulatory_classification"]
    # The missing-information list is not repeated here: the assistant's
    # MARKET CONTEXT block already carries the same list, computed by the
    # same missing_information_for() function, and one prompt must never
    # show two different versions of it.
    return {
        "overall_status": overall["status"],
        "confidence": overall["confidence"],
        "status_reason": overall["reason"],
        "content_hash": overview["product"]["content_hash"],
        "analysis": overview["analysis"],
        "regulatory_classification": {
            "status": classification["status"],
            "classification": classification["classification"],
            "confidence": classification["confidence"],
            "review_required": classification["review_required"],
        },
        "ip_review": {
            "status": overview["ip_review"]["status"],
            "notice": overview["ip_review"]["notice"],
        },
        "biodiversity_abs_review": {
            "status": overview["biodiversity_abs_review"]["status"],
            "reason": overview["biodiversity_abs_review"]["reason"],
        },
        "traditional_knowledge_review": {
            "status": overview["traditional_knowledge_review"]["status"],
            "notice": overview["traditional_knowledge_review"]["notice"],
        },
        "disclosures": {
            "event_count": overview["disclosures"]["event_count"],
            "review_status": overview["disclosures"]["review_status"],
        },
        "recommended_actions": [
            action["title"] for action in overview["recommended_actions"]
        ],
        "notice": OVERVIEW_NOTICE,
    }
