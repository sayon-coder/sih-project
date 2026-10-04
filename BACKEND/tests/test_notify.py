"""
Review-desk email notifications.

The template must carry the reference, the requester's identity, the
product/version, what is to be reviewed and the submission time; sending
is best-effort (unconfigured SMTP skips openly, failures never raise);
review creation succeeds even when sending explodes.
"""
from datetime import datetime, timezone


def test_template_carries_everything():
    from app.services.notify_service import build_review_email, format_ist

    submitted = datetime(2026, 10, 4, 14, 30, tzinfo=timezone.utc)
    rendered = build_review_email({
        "ref": "RV-000123",
        "title": "Please review it if possible",
        "notes": "Check whether my cold-press claim is substantiated.",
        "status": "REVIEW_REQUIRED",
        "product_name": "AshwaBio-X",
        "version_number": 2,
        "requester_name": "sayon",
        "requester_email": "sayon@example.com",
        "submitted_at": submitted,
        "review_url": "http://localhost:5173/reviews",
        "audit_id": 7,
    })
    assert "RV-000123" in rendered["subject"]
    for needle in (
        "sayon",
        "sayon@example.com",
        "AshwaBio-X",
        "Version 2",
        "Check whether my cold-press claim is substantiated.",
        "Please review it if possible",
        "REVIEW_REQUIRED",
        "#7",
    ):
        assert needle in rendered["html"], needle
        assert needle in rendered["text"], needle
    # 14:30 UTC == 20:00 IST (fixed +5:30, no DST in India).
    assert format_ist(submitted) == "04 Oct 2026, 08:00 PM IST"
    assert "does not constitute" in rendered["html"]


def test_unconfigured_smtp_skips_openly():
    from app.services.notify_service import send_review_email

    result = send_review_email({"ref": "RV-1"}, smtp_host="", recipient="x@y.z")
    assert result == {"sent": False, "reason": (
        "SMTP not configured (SMTP_HOST/SMTP_USERNAME or recipient missing)"
    )}


def test_send_failure_never_raises(monkeypatch):
    import smtplib

    from app.services.notify_service import send_review_email

    def _boom(*args, **kwargs):
        raise smtplib.SMTPException("no route")

    monkeypatch.setattr(smtplib, "SMTP", _boom)
    result = send_review_email(
        {"ref": "RV-2"},
        smtp_host="smtp.example.com",
        smtp_username="u",
        smtp_password="p",
        recipient="desk@example.com",
    )
    assert result["sent"] is False
    assert "SMTPException" in result["reason"]


def test_send_success_path(monkeypatch):
    import smtplib

    from app.services.notify_service import send_review_email

    sent = {}

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, sender, recipients, message):
            sent["mail"] = (sender, recipients, message)

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    result = send_review_email(
        {"ref": "RV-3", "title": "t"},
        smtp_host="smtp.example.com",
        smtp_username="sender@example.com",
        smtp_password="secret",
        recipient="desk@example.com",
    )
    assert result == {"sent": True, "reason": "sent"}
    assert sent["tls"] is True
    assert sent["mail"][1] == ["desk@example.com"]
    assert "RV-3" in sent["mail"][2]


def test_create_reports_email_outcome_honestly(client, auth_headers):
    r = client.post("/api/products", json={"name": "NotifyHonest"}, headers=auth_headers)
    pid = r.json()["data"]["id"]
    vid = r.json()["data"]["current_version_id"]
    created = client.post(
        "/api/reviews",
        json={"product_id": pid, "product_version_id": vid, "title": "t"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    mail = created.json()["data"]["email_notification"]
    # No SMTP in test settings: must say so, never claim a send.
    assert mail["sent"] is False
    assert "SMTP" in mail["reason"]


def test_notify_endpoint_reports_outcome(client, auth_headers):
    r = client.post("/api/products", json={"name": "NotifyResend"}, headers=auth_headers)
    pid = r.json()["data"]["id"]
    vid = r.json()["data"]["current_version_id"]
    created = client.post(
        "/api/reviews",
        json={"product_id": pid, "product_version_id": vid, "title": "t"},
        headers=auth_headers,
    )
    rid = created.json()["data"]["id"]
    resent = client.post(f"/api/reviews/{rid}/notify", headers=auth_headers)
    assert resent.status_code == 200, resent.text
    mail = resent.json()["data"]["email_notification"]
    # No SMTP in test settings: must say so, never claim a send.
    assert mail["sent"] is False
    assert "SMTP" in mail["reason"]
    assert client.post("/api/reviews/999999/notify", headers=auth_headers).status_code == 404


def test_review_creation_survives_notify_explosion(client, auth_headers, monkeypatch):
    import app.services.notify_service as notify_service

    def _explode(*args, **kwargs):
        raise RuntimeError("mailer is on fire")

    # review_service imports the sender lazily at call time, so patch the source.
    monkeypatch.setattr(notify_service, "send_review_email", _explode)
    r = client.post("/api/products", json={"name": "NotifyProof"}, headers=auth_headers)
    pid = r.json()["data"]["id"]
    vid = r.json()["data"]["current_version_id"]
    created = client.post(
        "/api/reviews",
        json={"product_id": pid, "product_version_id": vid, "title": "t"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
