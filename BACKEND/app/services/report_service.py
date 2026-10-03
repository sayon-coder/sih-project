"""
Report service (Phase 8b).

Generates the three PDF reports from stored rows only (no model calls) and
pins each file to its product version with a SHA-256 content hash. The PDF
embeds a QR code pointing at the public verification endpoint.

Flow per report: insert the row (reserving the id) -> render the PDF with the
verify URL -> hash the bytes -> write the file -> store hash + size. A
generation failure never leaves a half-written row behind.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis.ip_routes import build_ip_route_map
from app.config import get_settings
from app.models import ProductVersion
from app.models.analysis_models import Analysis, AnalysisStatus, AnalysisType
from app.models.report_models import Report, ReportType
from app.reports.builders import (
    build_disclosure_record,
    build_expert_handoff,
    build_ip_brief,
)
from app.services.audit_service import AuditService
from app.services.disclosure_service import DisclosureService, serialize as serialize_disclosure
from app.services.version_content import load_version_content
from app.utils.authorization import get_accessible_product, get_accessible_version

settings = get_settings()


def _latest_analysis(
    db: Session, version_id: int, analysis_type: AnalysisType
) -> Optional[Analysis]:
    return (
        db.query(Analysis)
        .filter(
            Analysis.product_version_id == version_id,
            Analysis.analysis_type == analysis_type,
            Analysis.status == AnalysisStatus.COMPLETED,
        )
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .first()
    )


def _analysis_line(a: Analysis) -> str:
    at = a.analysis_type.value if hasattr(a.analysis_type, "value") else str(a.analysis_type)
    when = a.created_at.isoformat() if a.created_at else "unknown time"
    return f"{at} (id {a.id}, {a.status}, {when}): {a.summary or 'no summary'}"


def _val(value: Any) -> str:
    """Render an enum (or plain value) as its runtime value."""
    if value is None:
        return "not recorded"
    return value.value if hasattr(value, "value") else str(value)


def _formulation_lines(formulation: Any) -> List[str]:
    """The formulation fields actually recorded - never an inferred value.

    Fields the user has not provided are shown as ``not provided`` so the
    report reflects the real record (spec item 12).
    """
    if formulation is None:
        return ["No formulation or process recorded for this version."]

    def _num(value: Any, unit: Optional[str] = None) -> Optional[str]:
        if value is None:
            return None
        return f"{value} {unit}".strip()

    rows = [
        ("Process description", formulation.process_description),
        ("Extraction method", formulation.extraction_method),
        ("Solvent", formulation.solvent),
        ("Temperature", _num(formulation.temperature, formulation.temperature_unit)),
        ("Pressure", _num(formulation.pressure, formulation.pressure_unit)),
        ("Duration", _num(formulation.duration, formulation.duration_unit)),
        ("Concentration", _num(formulation.concentration)),
        ("Other parameters", formulation.other_parameters),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value not in (None, "")]
    for label, value in rows:
        if value in (None, ""):
            lines.append(f"{label}: not provided")
    return lines


def _base_ctx(db: Session, product_id: int, version: ProductVersion) -> Dict[str, Any]:
    content = load_version_content(db, version)
    claims = content["claims"]
    markets = content["markets"]
    evidence = content["evidence"]
    return {
        "product_id": product_id,
        "product_name": version.product.name if version.product else f"product {product_id}",
        "version_id": version.id,
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        "content": content,
        # Actual claims with their provenance label (spec item 12).
        "claim_lines": [
            f"#{c.id} [{_val(c.claim_type)}] {c.claim_text} "
            f"(provenance: {c.provenance}, evidence: {c.evidence_status})"
            for c in claims
        ],
        # Actual target markets - country primary, region secondary (spec item 2/12).
        "market_lines": [
            f"{m.country}" + (f" / {m.region}" if m.region else "")
            + (f" - regulatory status: {m.regulatory_status}" if m.regulatory_status else "")
            for m in markets
        ],
        "formulation_lines": _formulation_lines(content["formulation"]),
        # Evidence with its verification status and provenance (spec item 12).
        "evidence_lines": [
            f"#{e.id} [{_val(e.evidence_type)}] {e.title} "
            f"(verification: {_val(e.verification_status)}, provenance: {e.provenance})"
            for e in evidence
        ],
    }


def _comp_details(comp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the evidence labels a report must show (spec item 12) from the
    latest comprehensive analysis: provenance labels, corpus type, citation
    status and uncertainty. Missing pieces render as ``not recorded`` - nothing
    is invented.
    """
    if not comp:
        return {
            "corpus_lines": ["No comprehensive analysis on record."],
            "standing_lines": ["No claim assessments on record."],
            "citation_line": "No citations on record.",
        }

    claim_review = comp.get("claim_review") or {}
    assessments = claim_review.get("assessments") or []
    standing_lines = [
        f"Claim {a.get('claim_id')}: {a.get('claim_text')} - "
        f"provenance {a.get('claim_provenance')}, evidence {a.get('evidence_status')}, "
        f"independent verification {a.get('independent_verification')}, "
        f"review required: {'yes' if a.get('review_required') else 'no'}"
        for a in assessments
    ] or ["No claim assessments on record."]

    citations = [c for a in assessments for c in (a.get("citations") or [])]
    if citations:
        citation_line = (
            f"{len(citations)} citation(s) retrieved from {len(assessments)} assessed "
            f"claim(s); per-claim independent verification: "
            + "; ".join(
                f"claim {a.get('claim_id')}: {a.get('independent_verification')}"
                for a in assessments
            )
            + "."
        )
    else:
        citation_line = (
            "No supporting citations were retrieved; independent verification: "
            + "; ".join(
                f"claim {a.get('claim_id')}: {a.get('independent_verification')}"
                for a in assessments
            )
            + "."
            if assessments
            else "No citations on record."
        )

    patent = comp.get("patent_signals") or {}
    corpus_type = patent.get("corpus_type") or ("DEMO_CORPUS" if patent else "NOT_SCREENED")
    corpus_lines = [
        f"Corpus type: {corpus_type}",
        f"Live search performed: {'yes' if patent.get('live_search_performed') else 'no'}",
        f"Records verified: {'yes' if patent.get('records_verified') else 'no'}",
    ]
    for record in (patent.get("records") or [])[:5]:
        corpus_lines.append(
            f"{record.get('record_label') or 'record'} - {record.get('title')} "
            f"(similarity: {record.get('similarity_band') or 'n/a'}, "
            f"uncertainty: {record.get('uncertainty') or 'not stated'}, "
            f"status: {record.get('verification_status') or 'not recorded'})"
        )

    return {
        "corpus_lines": corpus_lines,
        "standing_lines": standing_lines,
        "citation_line": citation_line,
    }


def _comprehensive_ctx(db: Session, version_id: int) -> Dict[str, Any]:
    analysis = _latest_analysis(db, version_id, AnalysisType.COMPREHENSIVE)
    if analysis is None or not analysis.results:
        return {}
    try:
        return json.loads(analysis.results)
    except (json.JSONDecodeError, TypeError):
        return {}


def serialize(r: Report) -> Dict[str, Any]:
    base = settings.public_base_url.rstrip("/")
    rtype = r.report_type.value if isinstance(r.report_type, ReportType) else str(r.report_type)
    return {
        "id": r.id,
        "product_id": r.product_id,
        "product_version_id": r.product_version_id,
        "report_type": rtype,
        "content_hash": r.content_hash,
        "file_size": r.file_size,
        "verification_id": r.verification_id,
        "download_url": f"/api/reports/{r.id}",
        "verify_url": f"{base}/api/reports/{r.id}/verify",
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class ReportService:
    """Generate, fetch and verify PDF reports."""

    @staticmethod
    def generate(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        report_type: ReportType,
        request: Optional[Request] = None,
    ) -> Report:
        version = get_accessible_version(db, product_id, version_id, user_id)
        ctx = _base_ctx(db, product_id, version)
        content = ctx.pop("content")

        if report_type == ReportType.IP_BRIEF:
            routes = build_ip_route_map(
                version.product,
                version,
                content["ingredients"],
                content["formulation"],
                content["claims"],
                content["evidence"],
                content["markets"],
            )
            comp = _comprehensive_ctx(db, version.id)
            classification_result = comp.get("product_classification") or {}
            classification = classification_result.get("category")
            status = classification_result.get("status")
            if classification and status:
                ctx["classification"] = (
                    f"{classification} (preliminary, status: {status})"
                )
            elif classification:
                ctx["classification"] = f"{classification} (preliminary)"
            else:
                ctx["classification"] = None
            ctx["routes"] = [
                {"route": r.route_label, "label": r.label} for r in routes.routes
            ]
            ctx["missing"] = comp.get("missing_information") or []
            ctx["questions"] = comp.get("expert_review_recommendations") or []
            ctx["details"] = _comp_details(comp)
            builder = build_ip_brief
        elif report_type == ReportType.DISCLOSURE_RECORD:
            events = DisclosureService.list(db, product_id, version_id, user_id)
            review = DisclosureService.review(db, product_id, version_id, user_id)
            ctx["events"] = [
                {
                    "id": e.id,
                    "disclosure_type": (
                        e.disclosure_type.value
                        if hasattr(e.disclosure_type, "value")
                        else str(e.disclosure_type)
                    ),
                    "description": e.description,
                    "record_hash": e.record_hash,
                }
                for e in events
            ]
            ctx["review_status"] = review["review_status"]
            builder = build_disclosure_record
        else:
            comp_analysis = _latest_analysis(db, version.id, AnalysisType.COMPREHENSIVE)
            patent = _latest_analysis(db, version.id, AnalysisType.PATENT_SCREENING)
            biodiv = _latest_analysis(db, version.id, AnalysisType.BIODIVERSITY_SCREENING)
            tk = _latest_analysis(db, version.id, AnalysisType.TK_SCREENING)
            screenings = [s for s in (patent, biodiv, tk) if s is not None]
            events = DisclosureService.list(db, product_id, version_id, user_id)
            comp = _comprehensive_ctx(db, version.id)
            ctx["analysis_lines"] = (
                [_analysis_line(comp_analysis)] if comp_analysis else []
            )
            ctx["screening_lines"] = [_analysis_line(s) for s in screenings]
            ctx["disclosure_lines"] = [
                f"#{e.id} {e.disclosure_type}: {e.description}" for e in events
            ]
            ctx["questions"] = comp.get("expert_review_recommendations") or []
            ctx["missing"] = comp.get("missing_information") or []
            ctx["details"] = _comp_details(comp)
            classification_result = comp.get("product_classification") or {}
            if classification_result.get("category"):
                ctx["classification"] = (
                    f"{classification_result['category']} (preliminary, status: "
                    f"{classification_result.get('status') or 'unknown'})"
                )
            else:
                ctx["classification"] = None
            ctx["review_status"] = "No expert review recorded."
            builder = build_expert_handoff

        os.makedirs(settings.reports_dir, exist_ok=True)
        report = Report(
            product_id=product_id,
            product_version_id=version_id,
            report_type=report_type,
            file_path="pending",
            content_hash="pending",
            file_size=0,
            verification_id=secrets.token_hex(8),
            created_by=user_id,
        )
        db.add(report)
        db.flush()  # reserve the id for the verify URL

        base = settings.public_base_url.rstrip("/")
        verify_url = f"{base}/api/reports/{report.id}/verify"
        try:
            pdf_bytes = builder(ctx, verify_url, report.verification_id)
        except Exception:
            db.rollback()
            raise

        file_path = os.path.join(settings.reports_dir, f"{report.id}.pdf")
        with open(file_path, "wb") as fh:
            fh.write(pdf_bytes)
        report.file_path = file_path
        report.content_hash = hashlib.sha256(pdf_bytes).hexdigest()
        report.file_size = len(pdf_bytes)
        db.commit()
        db.refresh(report)
        AuditService.log_action(
            db,
            user_id,
            "generate_report",
            "report",
            report.id,
            {"product_id": product_id, "product_version_id": version_id,
             "report_type": report_type.value},
            request,
        )
        return report

    @staticmethod
    def get(db: Session, report_id: int, user_id: int) -> Report:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        get_accessible_product(db, report.product_id, user_id)
        return report

    @staticmethod
    def list_for_version(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[Report]:
        get_accessible_version(db, product_id, version_id, user_id)
        return (
            db.query(Report)
            .filter(
                Report.product_id == product_id,
                Report.product_version_id == version_id,
            )
            .order_by(Report.created_at.desc(), Report.id.desc())
            .all()
        )

    @staticmethod
    def read_bytes(report: Report) -> bytes:
        if not os.path.exists(report.file_path):
            raise HTTPException(status_code=410, detail="Report file no longer available")
        with open(report.file_path, "rb") as fh:
            return fh.read()

    @staticmethod
    def verify_payload(report: Report) -> Dict[str, Any]:
        try:
            pdf_bytes = ReportService.read_bytes(report)
            on_disk_hash = hashlib.sha256(pdf_bytes).hexdigest()
        except HTTPException:
            on_disk_hash = None
        data = serialize(report)
        data["hash_match"] = on_disk_hash == report.content_hash if on_disk_hash else False
        data["verified_at"] = datetime.now(timezone.utc).isoformat()
        return data
