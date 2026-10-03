"""
PDF builders (Phase 8b).

Three deterministic ReportLab builders that assemble their content only from
stored rows (passport content, recorded analyses, disclosure events). No model
calls, no invented sources: anything absent is labelled as missing rather
than filled in.

Every PDF ends with the mandatory disclaimers and a QR code pointing at the
public verification endpoint for the generated report.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors

from app.analysis.prompts import ANALYSIS_DISCLAIMER
from app.models.disclosure_models import INVENTION_DISCLOSURE_DISCLAIMER

GENERAL_DISCLAIMER = (
    "This platform provides preliminary, source-backed information and decision "
    "support. It does not constitute legal, patent, regulatory, medical, or "
    "government advice or approval."
)

PATENT_DISCLAIMER = (
    "Patent-related outputs are preliminary information based on identified "
    "public records and are not determinations of patentability, validity, "
    "infringement, or priority."
)


def _styles():
    return getSampleStyleSheet()


def _heading(doc_parts: list, styles, text: str, level: int = 1):
    style = styles["Heading1"] if level == 1 else styles["Heading2"]
    doc_parts.append(Paragraph(text, style))
    doc_parts.append(Spacer(1, 0.3 * cm))


def _body(doc_parts: list, styles, text: str):
    doc_parts.append(Paragraph(text or "-", styles["Normal"]))
    doc_parts.append(Spacer(1, 0.2 * cm))


def _kv_table(doc_parts: list, styles, rows: List[List[str]]):
    table = Table([[Paragraph(str(a), styles["Normal"]), Paragraph(str(b), styles["Normal"])] for a, b in rows])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    doc_parts.append(table)
    doc_parts.append(Spacer(1, 0.4 * cm))


def _bullets(doc_parts: list, styles, items: List[str]):
    for item in items:
        doc_parts.append(Paragraph(f"- {item}", styles["Normal"]))
    doc_parts.append(Spacer(1, 0.2 * cm))


def _qr_image(url: str, size_cm: float = 4.0):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size_cm * cm, height=size_cm * cm)


def _footer(doc_parts: list, styles, verify_url: str, verification_id: str):
    _heading(doc_parts, styles, "Verification", level=2)
    _body(doc_parts, styles, f"Verification ID: {verification_id}")
    _body(doc_parts, styles, f"Verify at: {verify_url}")
    doc_parts.append(_qr_image(verify_url))
    doc_parts.append(Spacer(1, 0.3 * cm))
    _heading(doc_parts, styles, "Disclaimers", level=2)
    _body(doc_parts, styles, GENERAL_DISCLAIMER)
    _body(doc_parts, styles, PATENT_DISCLAIMER)
    _body(doc_parts, styles, ANALYSIS_DISCLAIMER)
    _body(doc_parts, styles, INVENTION_DISCLOSURE_DISCLAIMER)


def _render(title: str, build, verify_url: str, verification_id: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    styles = _styles()
    parts: list = []
    _heading(parts, styles, title)
    _body(parts, styles, f"Generated: {datetime.now(timezone.utc).isoformat()}")
    build(parts, styles)
    _footer(parts, styles, verify_url, verification_id)
    doc.build(parts)
    return buf.getvalue()


def _passport_header(parts, styles, ctx: Dict[str, Any]):
    _kv_table(
        parts,
        styles,
        [
            ["Product", f"{ctx['product_name']} (id {ctx['product_id']})"],
            ["Version", f"v{ctx['version_number']} (id {ctx['version_id']})"],
            ["Content hash", ctx.get("content_hash") or "not recorded"],
        ],
    )


def _content_sections(parts, styles, ctx: Dict[str, Any]):
    """The version's actual content: claims (with provenance), target markets,

    formulation fields and evidence - exactly what is recorded, with
    ``not provided`` / ``not recorded`` gaps shown (spec item 12)."""
    _heading(parts, styles, "Claims on record (with provenance)", level=2)
    _bullets(parts, styles, ctx.get("claim_lines") or ["No claims recorded."])
    _heading(parts, styles, "Target markets", level=2)
    _bullets(parts, styles, ctx.get("market_lines") or ["No target markets recorded."])
    _heading(parts, styles, "Formulation", level=2)
    _bullets(parts, styles, ctx.get("formulation_lines") or ["No formulation recorded."])
    _heading(parts, styles, "Evidence on record", level=2)
    _bullets(parts, styles, ctx.get("evidence_lines") or ["No evidence recorded."])


def _evidence_detail_sections(parts, styles, ctx: Dict[str, Any]):
    """Claim standing, citation status, corpus type and uncertainty (item 12)."""
    details = ctx.get("details") or {}
    _heading(parts, styles, "Claim standing & citation status", level=2)
    _bullets(
        parts,
        styles,
        details.get("standing_lines") or ["No claim assessments on record."],
    )
    _body(parts, styles, details.get("citation_line") or "No citations on record.")
    _heading(parts, styles, "Patent screening corpus", level=2)
    _bullets(
        parts,
        styles,
        details.get("corpus_lines") or ["No patent screening on record."],
    )


def build_ip_brief(ctx: Dict[str, Any], verify_url: str, verification_id: str) -> bytes:
    """IP Opportunity & Evidence Brief (never a patentability determination)."""

    def _build(parts, styles):
        _passport_header(parts, styles, ctx)
        _heading(parts, styles, "Preliminary classification", level=2)
        _body(parts, styles, ctx.get("classification") or "No recorded preliminary classification.")
        _heading(parts, styles, "IP routes", level=2)
        routes = ctx.get("routes") or []
        if routes:
            _kv_table(parts, styles, [[r["route"], r["label"]] for r in routes])
        else:
            _body(parts, styles, "No route map recorded.")
        _content_sections(parts, styles, ctx)
        _evidence_detail_sections(parts, styles, ctx)
        _heading(parts, styles, "Missing information", level=2)
        _bullets(parts, styles, ctx.get("missing") or ["None recorded."])
        _heading(parts, styles, "Expert-review questions", level=2)
        _bullets(parts, styles, ctx.get("questions") or ["None recorded."])

    return _render("IP Opportunity & Evidence Brief", _build, verify_url, verification_id)


def build_disclosure_record(
    ctx: Dict[str, Any], verify_url: str, verification_id: str
) -> bytes:
    """Invention Disclosure Record for one version's disclosure events."""

    def _build(parts, styles):
        _passport_header(parts, styles, ctx)
        _heading(parts, styles, "Recorded disclosure events", level=2)
        events = ctx.get("events") or []
        if events:
            _kv_table(
                parts,
                styles,
                [
                    [f"#{e['id']} {e['disclosure_type']}", f"{e['description']} (hash {e['record_hash'][:16]}...)"]
                    for e in events
                ],
            )
        else:
            _body(parts, styles, "No disclosure events recorded for this version.")
        _heading(parts, styles, "Review status", level=2)
        _body(parts, styles, ctx.get("review_status") or "Not reviewed.")
        _content_sections(parts, styles, ctx)

    return _render("Invention Disclosure Record", _build, verify_url, verification_id)


def build_expert_handoff(ctx: Dict[str, Any], verify_url: str, verification_id: str) -> bytes:
    """Expert Handoff Package: everything a reviewer needs, nothing concluded."""

    def _build(parts, styles):
        _passport_header(parts, styles, ctx)
        if ctx.get("classification"):
            _heading(parts, styles, "Preliminary classification", level=2)
            _body(parts, styles, ctx["classification"])
        _heading(parts, styles, "Analyses on record", level=2)
        _bullets(parts, styles, ctx.get("analysis_lines") or ["No analyses recorded."])
        _heading(parts, styles, "Screenings on record", level=2)
        _bullets(parts, styles, ctx.get("screening_lines") or ["No screenings recorded."])
        _heading(parts, styles, "Disclosures on record", level=2)
        _bullets(parts, styles, ctx.get("disclosure_lines") or ["No disclosures recorded."])
        _content_sections(parts, styles, ctx)
        _evidence_detail_sections(parts, styles, ctx)
        if ctx.get("missing"):
            _heading(parts, styles, "Missing information", level=2)
            _bullets(parts, styles, ctx["missing"])
        _heading(parts, styles, "Open review questions", level=2)
        _bullets(parts, styles, ctx.get("questions") or ["None recorded."])
        _heading(parts, styles, "Review status", level=2)
        _body(parts, styles, ctx.get("review_status") or "No expert review recorded.")

    return _render("Expert Handoff Package", _build, verify_url, verification_id)
