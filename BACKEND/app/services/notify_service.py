"""
Review-desk notifications (email).

When a user requests an expert review, the review desk receives a formal,
government-styled HTML email: reference number, requester identity, product
and version under review, what the requester wants examined, and the exact
submission time (IST). Sending is strictly best-effort: without SMTP
configuration nothing is sent (logged openly), and a send failure never
breaks review creation - it is recorded in the audit trail instead.

Standard library only (``smtplib`` + ``email``); no new dependencies.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: India Standard Time has no daylight saving - a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

#: Brand colours shared with the web UI.
_DEEP_GREEN = "#1E3A2F"
_GOLD = "#B98A2F"
_PAPER = "#FAF5EC"


def ist_now() -> datetime:
    """Current time in IST (naive-safe, always attached)."""
    return datetime.now(timezone.utc).astimezone(IST)


def format_ist(moment: Optional[datetime]) -> str:
    """'04 Oct 2026, 02:30 PM IST' - 'not recorded' when absent."""
    if moment is None:
        return "not recorded"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def build_review_email(payload: Dict[str, Any]) -> Dict[str, str]:
    """Render subject + plain-text + HTML bodies for a review request.

    ``payload`` keys: ref, title, notes, status, product_name,
    version_number, requester_name, requester_email, submitted_at
    (datetime), review_url (optional), audit_id (optional).
    """
    ref = payload.get("ref", "RV-UNKNOWN")
    title = (payload.get("title") or "Expert review requested").strip()
    notes = (payload.get("notes") or "No specific instructions provided.").strip()
    subject = f"[IP-SAKTI Sahayak] Expert review requested - {ref}"
    submitted = format_ist(payload.get("submitted_at"))
    review_url = payload.get("review_url") or ""
    audit_id = payload.get("audit_id")

    def row(label: str, value: str) -> str:
        return (
            f'<tr><td style="padding:8px 12px;color:#5B6670;font-size:13px;'
            f"width:38%;vertical-align:top;\">{label}</td>"
            f'<td style="padding:8px 12px;color:#1C2420;font-size:13px;">'
            f"{value}</td></tr>"
        )

    details = "".join(
        [
            row("Reference number", f"<strong>{ref}</strong>"),
            row("Request title", title),
            row(
                "Requested by",
                f"{payload.get('requester_name', 'Not recorded')} "
                f"&lt;{payload.get('requester_email', 'not recorded')}&gt;",
            ),
            row(
                "Product / version",
                f"{payload.get('product_name', 'Not recorded')} - "
                f"Version {payload.get('version_number', 'not recorded')}",
            ),
            row("Submitted at", submitted),
            row("Current status", str(payload.get("status", "DRAFT"))),
        ]
    )
    if audit_id is not None:
        details += row("Audit record", f"#{audit_id}")

    link_block = (
        f'<p style="margin:16px 0 0;">'
        f'<a href="{review_url}" style="background-color:{_DEEP_GREEN};'
        f"color:#ffffff;padding:10px 22px;text-decoration:none;"
        f'border-radius:6px;font-size:14px;">Open the review queue</a></p>'
        if review_url
        else ""
    )

    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background-color:#EFE9D8;font-family:Georgia,'Times New Roman',serif;">
<div style="max-width:640px;margin:0 auto;background-color:#ffffff;">
<div style="height:6px;background:linear-gradient(to right,#FF9933 0%,#FF9933 33%,#F5F5F5 33%,#F5F5F5 66%,#138808 66%,#138808 100%);"></div>
<div style="background-color:{_DEEP_GREEN};color:#ffffff;padding:22px 28px;">
<div style="font-size:11px;letter-spacing:3px;color:{_GOLD};">IP-SAKTI SAHAYAK &middot; AYURVEDA IP DECISION SUPPORT</div>
<div style="font-size:22px;margin-top:6px;">Expert Review Request &mdash; {ref}</div>
</div>
<div style="padding:24px 28px;color:#1C2420;">
<p style="font-size:14px;">Respected Reviewer,</p>
<p style="font-size:14px;">A user has requested expert review of an Ayurveda
product dossier on the IP-SAKTI Sahayak platform. The request details are
as follows:</p>
<table style="border-collapse:collapse;width:100%;border:1px solid #E7DFCE;">{details}</table>
<h3 style="color:{_DEEP_GREEN};font-size:15px;margin:20px 0 6px;">What the requester wants reviewed</h3>
<p style="font-size:14px;background-color:{_PAPER};border-left:3px solid {_GOLD};padding:10px 14px;">{notes}</p>
{link_block}
<p style="font-size:12px;color:#5B6670;margin-top:20px;">This is a
preliminary, source-backed decision-support request. It does not constitute
legal, patent, regulatory, medical or government advice or approval. Please
do not reply to this automated message; act through the platform review queue.</p>
</div>
<div style="background-color:{_PAPER};padding:14px 28px;border-top:2px solid {_GOLD};font-size:11px;color:#5B6670;">
IP-SAKTI Sahayak &middot; Multilingual RAG-based AI Assistant for Ayurveda IP
and Regulatory Guidance &middot; This is a system-generated message.
</div>
</div>
</body></html>"""

    text = (
        f"IP-SAKTI SAHAYAK - EXPERT REVIEW REQUEST ({ref})\n"
        f"{'=' * 60}\n\n"
        f"Respected Reviewer,\n\n"
        f"A user has requested expert review of an Ayurveda product dossier.\n\n"
        f"Reference number : {ref}\n"
        f"Request title    : {title}\n"
        f"Requested by     : {payload.get('requester_name', 'Not recorded')} "
        f"<{payload.get('requester_email', 'not recorded')}>\n"
        f"Product/version  : {payload.get('product_name', 'Not recorded')} - "
        f"Version {payload.get('version_number', 'not recorded')}\n"
        f"Submitted at     : {submitted}\n"
        f"Current status   : {payload.get('status', 'DRAFT')}\n"
        + (f"Audit record     : #{audit_id}\n" if audit_id is not None else "")
        + f"\nWHAT THE REQUESTER WANTS REVIEWED\n---\n{notes}\n"
        + (f"\nOpen the review queue: {review_url}\n" if review_url else "")
        + "\nThis is a preliminary, source-backed decision-support request. "
        "It does not constitute legal, patent, regulatory, medical or "
        "government advice or approval. Do not reply to this automated message."
    )
    return {"subject": subject, "text": text, "html": html}


def send_review_email(
    payload: Dict[str, Any],
    *,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_username: str = "",
    smtp_password: str = "",
    use_tls: bool = True,
    sender: str = "",
    recipient: str = "",
) -> Dict[str, Any]:
    """Send the rendered email; never raises.

    Returns ``{"sent": bool, "reason": str}``. Empty host/credentials means
    "not configured" (startup warning, per-request log) - the review itself
    is unaffected either way.
    """
    if not smtp_host or not smtp_username or not recipient:
        reason = "SMTP not configured (SMTP_HOST/SMTP_USERNAME or recipient missing)"
        logger.warning("Review email skipped for %s: %s", payload.get("ref"), reason)
        return {"sent": False, "reason": reason}
    rendered = build_review_email(payload)
    message = MIMEMultipart("alternative")
    message["Subject"] = rendered["subject"]
    message["From"] = sender or smtp_username
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message.attach(MIMEText(rendered["text"], "plain", "utf-8"))
    message.attach(MIMEText(rendered["html"], "html", "utf-8"))
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if use_tls:
                server.starttls()
            if smtp_password:
                server.login(smtp_username, smtp_password)
            server.sendmail(message["From"], [recipient], message.as_string())
    except Exception as exc:
        logger.warning(
            "Review email to %s failed for %s: %s", recipient, payload.get("ref"), exc
        )
        return {"sent": False, "reason": f"{exc.__class__.__name__}: {exc}"}
    logger.info("Review email sent to %s for %s", recipient, payload.get("ref"))
    return {"sent": True, "reason": "sent"}
