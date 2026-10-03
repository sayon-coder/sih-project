"""
Tests for the DPDP-aligned privacy layer.

What these tests protect:
* consent is explicit (confirm/grant flags) and every grant, withdrawal,
  access attempt and block is written to an evidence log;
* access to a source without an effective permission is 403 with a
  machine-readable body AND a blocked log entry;
* the export is owner-scoped - no other data principal's data can leak into
  it, and an ADMIN gets only their own through this route;
* erasure anonymises rather than breaking foreign keys, and keeps the audit
  trail with user_id NULL;
* retention honours the settings, and retention_days == 0 never purges;
* audit details are PII-redacted on the way in.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.main import app
from app.routers.privacy import router as privacy_router
from app.routers.sources_registry import router as sources_registry_router
from app.models import AuditLog, Role, RoleName, User, UserRole
from app.models.privacy_models import DataConsent, SourceAccessLog, SourceConsent
from app.models.rag_models import ChatMessage, ChatSession, SourceDocument
from app.services.audit_service import AuditService, sanitize_details
from app.utils import hash_password

# The integrator registers these routers in app/main.py. Mount them here as
# well (idempotently) so the privacy tests pass before and after that wiring.
def _mount(path: str, router) -> None:
    if not any(getattr(route, "path", None) == path for route in app.routes):
        app.include_router(router)


_mount("/api/privacy/notice", privacy_router)
_mount("/api/official-sources", sources_registry_router)

PAID_SOURCE = "derwent-innovation"


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _make_admin(client, db_session) -> dict:
    """Create an ADMIN user and return their auth headers."""
    user = User(
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("adminpass123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    role = db_session.query(Role).filter(Role.name == RoleName.ADMIN).first()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "adminpass123"},
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _grant_source(client, headers, source_id=PAID_SOURCE, **overrides) -> dict:
    payload = {
        "source_id": source_id,
        "access_type": "PAID_SUBSCRIPTION",
        "scope": ["search my own subscription", "read result metadata"],
        "confirm": True,
    }
    payload.update(overrides)
    return client.post("/api/privacy/sources/consent", json=payload, headers=headers)


def _add_chat(db_session, user_id: int, content: str = "hello"):
    session = ChatSession(user_id=user_id, title="privacy-test")
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    message = ChatMessage(session_id=session.id, role="user", content=content)
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)
    return session, message


def _backdate(db_session, model, row_id: int, days: int) -> None:
    """Force a row's created_at into the past (retention tests)."""
    when = datetime.now(timezone.utc) - timedelta(days=days)
    db_session.query(model).filter(model.id == row_id).update(
        {"created_at": when}, synchronize_session=False
    )
    db_session.commit()


def _patch_settings(monkeypatch, **overrides):
    """Point privacy_service at a Settings copy with different retention."""
    from app.config import Settings
    import app.services.privacy_service as privacy_service

    patched = Settings().model_copy(update=overrides)
    monkeypatch.setattr(privacy_service, "get_settings", lambda: patched)
    return patched


def _access_logs(db_session, action: str) -> list:
    return (
        db_session.query(SourceAccessLog)
        .filter(SourceAccessLog.action == action)
        .all()
    )


def _delete_with_body(client, url: str, body: dict, headers: dict):
    """Starlette's TestClient has no ``delete(json=...)``; use the raw verb."""
    return client.request("DELETE", url, json=body, headers=headers)


# -------------------------------------------------------
# PII redaction in the audit trail
# -------------------------------------------------------

class TestAuditDetailsSanitised:
    def test_sanitize_redacts_sensitive_keys(self):
        clean = sanitize_details(
            {
                "email": "person@example.com",
                "username": "person",
                "password": "hunter2",
                "api_token": "abc",
                "client_secret": "xyz",
                "phone": "+9112345",
                "reason": "invalid_credentials",
                "product_id": 7,
            }
        )
        assert clean["email"] == "***"
        assert clean["username"] == "***"
        assert clean["password"] == "***"
        assert clean["api_token"] == "***"
        assert clean["client_secret"] == "***"
        assert clean["phone"] == "***"
        assert clean["reason"] == "invalid_credentials"
        assert clean["product_id"] == 7

    def test_sanitize_walks_nested_structures(self):
        clean = sanitize_details(
            {"users": [{"email": "a@b.c", "id": 1}], "nested": {"user_name": "x"}}
        )
        assert clean["users"][0]["email"] == "***"
        assert clean["users"][0]["id"] == 1
        assert clean["nested"]["user_name"] == "***"

    def test_log_action_never_persists_email(self, db_session):
        AuditService.log_action(
            db=db_session,
            user_id=None,
            action="register",
            resource="user",
            details={"email": "leak@example.com", "username": "leaker"},
        )
        entry = db_session.query(AuditLog).filter(AuditLog.action == "register").one()
        stored = json.loads(entry.details)
        assert stored["email"] == "***"
        assert stored["username"] == "***"
        assert "leak@example.com" not in entry.details


# -------------------------------------------------------
# Privacy notice + data consent
# -------------------------------------------------------

class TestDataConsent:
    def test_requires_authentication(self, client):
        assert client.get("/api/privacy/consent").status_code == 401
        assert client.post("/api/privacy/consent", json={}).status_code == 401

    def test_grant_requires_explicit_flag(self, client, auth_headers):
        response = client.post(
            "/api/privacy/consent",
            json={"purposes": ["account"], "grant": False},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "GRANT_REQUIRED"

    def test_grant_unknown_purpose_rejected(self, client, auth_headers):
        response = client.post(
            "/api/privacy/consent",
            json={"purposes": ["surveillance"], "grant": True},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "UNKNOWN_PURPOSE"

    def test_grant_is_recorded_and_audited(self, client, db_session, auth_headers):
        response = client.post(
            "/api/privacy/consent",
            json={"purposes": ["account", "assistant"], "grant": True},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        consent = data["consent"]
        assert consent["granted"] is True
        assert consent["withdrawn"] is False
        assert consent["purposes"] == ["account", "assistant"]
        assert consent["notice_version"]
        assert data["audit_id"]

        row = db_session.query(DataConsent).filter(DataConsent.id == consent["id"]).one()
        assert row.granted is True
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "grant_privacy_consent")
            .count()
            == 1
        )

        listed = client.get("/api/privacy/consent", headers=auth_headers).json()["data"]
        assert listed["notice"]["version"] == consent["notice_version"]
        assert any(c["id"] == consent["id"] for c in listed["consents"])

    def test_withdraw_keeps_the_record(self, client, db_session, auth_headers):
        created = client.post(
            "/api/privacy/consent",
            json={"purposes": ["account"], "grant": True},
            headers=auth_headers,
        ).json()["data"]["consent"]

        response = client.delete(
            f"/api/privacy/consent/{created['id']}", headers=auth_headers
        )
        assert response.status_code == 200
        withdrawn = response.json()["data"]["consent"]
        assert withdrawn["withdrawn"] is True
        assert withdrawn["withdrawn_at"]

        # Row survives (auditability) but is marked withdrawn.
        row = db_session.query(DataConsent).filter(DataConsent.id == created["id"]).one()
        assert row.withdrawn_at is not None
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "withdraw_privacy_consent")
            .count()
            == 1
        )

        # Idempotent: withdrawing again is still 200.
        again = client.delete(
            f"/api/privacy/consent/{created['id']}", headers=auth_headers
        )
        assert again.status_code == 200

    def test_withdraw_another_users_consent_is_404(
        self, client, auth_headers, second_user_headers
    ):
        created = client.post(
            "/api/privacy/consent",
            json={"purposes": ["account"], "grant": True},
            headers=auth_headers,
        ).json()["data"]["consent"]
        response = client.delete(
            f"/api/privacy/consent/{created['id']}", headers=second_user_headers
        )
        assert response.status_code == 404


# -------------------------------------------------------
# Source consent + consent-gated access
# -------------------------------------------------------

class TestSourceConsent:
    def test_grant_requires_confirm(self, client, db_session, auth_headers):
        response = client.post(
            "/api/privacy/sources/consent",
            json={
                "source_id": PAID_SOURCE,
                "access_type": "PAID_SUBSCRIPTION",
                "scope": ["search"],
            },
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "CONFIRM_REQUIRED"
        assert db_session.query(SourceConsent).count() == 0

    def test_grant_requires_scope(self, client, auth_headers):
        response = _grant_source(client, auth_headers, scope=[])
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "SCOPE_REQUIRED"

    def test_unknown_source_is_404(self, client, auth_headers):
        response = _grant_source(client, auth_headers, source_id="not-a-source")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"

    def test_grant_writes_consent_and_evidence_log(
        self, client, db_session, auth_headers
    ):
        response = _grant_source(client, auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        consent = data["consent"]
        assert consent["permission"] == "GRANTED"
        assert consent["granted_at"]
        assert consent["expires_at"]
        assert consent["scope"] == ["search my own subscription", "read result metadata"]
        assert data["audit_id"]

        row = db_session.query(SourceConsent).one()
        assert row.user_id is not None
        assert row.source_id == PAID_SOURCE
        assert row.ip_address is not None

        assert len(_access_logs(db_session, "PERMISSION_GRANTED")) == 1
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "grant_source_consent")
            .count()
            == 1
        )

        listed = client.get("/api/privacy/sources/consent", headers=auth_headers)
        assert listed.status_code == 200
        assert len(listed.json()["data"]) == 1

    def test_access_without_consent_is_blocked(
        self, client, db_session, auth_headers
    ):
        response = client.post(
            "/api/privacy/sources/access",
            json={"source_id": PAID_SOURCE},
            headers=auth_headers,
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "ACCESS_BLOCKED_NO_PERMISSION"
        assert detail["grant_endpoint"] == "POST /api/privacy/sources/consent"

        assert len(_access_logs(db_session, "ACCESS_BLOCKED_NO_PERMISSION")) == 1
        assert len(_access_logs(db_session, "PERMISSION_DENIED")) == 1
        # Nothing was ever fetched on the user's behalf.
        assert len(_access_logs(db_session, "ACCESS_PERFORMED")) == 0

    def test_access_with_consent_performs_a_handoff(
        self, client, db_session, auth_headers
    ):
        _grant_source(client, auth_headers)
        response = client.post(
            "/api/privacy/sources/access",
            json={"source_id": PAID_SOURCE},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        # Honest: a handoff, never a proxied fetch of paid data.
        assert data["mode"] == "HANDOFF"
        assert data["data_fetched_by_platform"] is False
        assert data["url"].startswith("http")
        assert data["access"] == "PAID_SUBSCRIPTION"
        assert data["requires_permission"] is True
        assert "does not fetch" in data["instructions"]

        assert len(_access_logs(db_session, "ACCESS_ATTEMPTED")) == 1
        assert len(_access_logs(db_session, "ACCESS_PERFORMED")) == 1

    def test_revoke_is_idempotent_and_owner_scoped(
        self, client, db_session, auth_headers, second_user_headers
    ):
        consent_id = _grant_source(client, auth_headers).json()["data"]["consent"]["id"]

        first = client.delete(
            f"/api/privacy/sources/consent/{consent_id}", headers=auth_headers
        )
        assert first.status_code == 200
        assert first.json()["data"]["consent"]["permission"] == "REVOKED"

        second = client.delete(
            f"/api/privacy/sources/consent/{consent_id}", headers=auth_headers
        )
        assert second.status_code == 200
        assert second.json()["data"]["consent"]["permission"] == "REVOKED"
        assert len(_access_logs(db_session, "PERMISSION_REVOKED")) == 1

        # Another user's row is a 404 (ids must not be probeable).
        other = client.delete(
            f"/api/privacy/sources/consent/{consent_id}", headers=second_user_headers
        )
        assert other.status_code == 404

    def test_revoked_permission_blocks_access(
        self, client, db_session, auth_headers
    ):
        consent_id = _grant_source(client, auth_headers).json()["data"]["consent"]["id"]
        client.delete(f"/api/privacy/sources/consent/{consent_id}", headers=auth_headers)

        response = client.post(
            "/api/privacy/sources/access",
            json={"source_id": PAID_SOURCE},
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ACCESS_BLOCKED_NO_PERMISSION"
        assert len(_access_logs(db_session, "ACCESS_BLOCKED_NO_PERMISSION")) == 1

    def test_expired_permission_blocks_access(
        self, client, db_session, auth_headers
    ):
        _grant_source(client, auth_headers)
        # Force the granted permission into the past.
        db_session.query(SourceConsent).update(
            {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)},
            synchronize_session=False,
        )
        db_session.commit()

        response = client.post(
            "/api/privacy/sources/access",
            json={"source_id": PAID_SOURCE},
            headers=auth_headers,
        )
        assert response.status_code == 403
        db_session.expire_all()
        assert db_session.query(SourceConsent).one().permission == "EXPIRED"

    def test_access_log_is_owner_scoped(
        self, client, db_session, auth_headers, second_user_headers
    ):
        _grant_source(client, auth_headers)
        client.post(
            "/api/privacy/sources/access",
            json={"source_id": PAID_SOURCE},
            headers=auth_headers,
        )

        mine = client.get("/api/privacy/sources/access-log", headers=auth_headers)
        assert mine.status_code == 200
        actions = [entry["action"] for entry in mine.json()["data"]]
        assert "ACCESS_PERFORMED" in actions
        assert "PERMISSION_GRANTED" in actions

        theirs = client.get(
            "/api/privacy/sources/access-log", headers=second_user_headers
        )
        assert theirs.status_code == 200
        assert theirs.json()["data"] == []


# -------------------------------------------------------
# Export (access & portability)
# -------------------------------------------------------

class TestDataExport:
    def test_export_is_owner_scoped(
        self, client, db_session, auth_headers, second_user_headers
    ):
        me = db_session.query(User).filter(User.email == "test@example.com").one()
        other = db_session.query(User).filter(User.email == "other@example.com").one()

        # My own data...
        created = client.post(
            "/api/products", json={"name": "My Ashwagandha Extract"}, headers=auth_headers
        )
        assert created.status_code == 201, created.json()
        _add_chat(db_session, me.id, content="Is my formulation novel?")

        # ...and someone else's.
        other_product = client.post(
            "/api/products",
            json={"name": "Other Persons Product"},
            headers=second_user_headers,
        )
        assert other_product.status_code == 201, other_product.json()
        _add_chat(db_session, other.id, content="Someone else's question")

        response = client.get("/api/privacy/export", headers=auth_headers)
        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        payload = response.json()

        assert payload["profile"]["email"] == "test@example.com"
        assert payload["counts"]["products"] == 1
        assert payload["counts"]["chat_messages"] >= 1
        assert any(p["name"] == "My Ashwagandha Extract" for p in payload["products"])

        raw = response.text
        assert "other@example.com" not in raw
        assert "Other Persons Product" not in raw
        assert "Someone else's question" not in raw

    def test_admin_cannot_pull_another_users_export(self, client, db_session):
        victim = User(
            username="victim",
            email="victim@example.com",
            password_hash=hash_password("victimpass123"),
            is_active=True,
        )
        db_session.add(victim)
        db_session.commit()
        db_session.refresh(victim)
        _add_chat(db_session, victim.id, content="Private question")

        admin = _make_admin(client, db_session)
        # There is no user-id parameter: asking for someone else's export is
        # ignored, and only the caller's own data comes back.
        response = client.get(
            "/api/privacy/export?user_id=%d" % victim.id, headers=admin
        )
        assert response.status_code == 200
        payload = response.json()
        assert "victim@example.com" not in response.text
        assert "Private question" not in response.text
        assert payload["data_principal"]["user_id"] != victim.id
        assert payload["counts"]["chat_messages"] == 0

    def test_export_excludes_server_paths(self, client, db_session, auth_headers):
        doc = SourceDocument(
            title="My upload",
            source_type="patent",
            uploader_id=db_session.query(User)
            .filter(User.email == "test@example.com")
            .one()
            .id,
            file_path="/srv/secret/path.pdf",
        )
        db_session.add(doc)
        db_session.commit()

        payload = client.get("/api/privacy/export", headers=auth_headers).json()
        assert payload["counts"]["uploaded_documents"] == 1
        assert "/srv/secret/path.pdf" not in client.get(
            "/api/privacy/export", headers=auth_headers
        ).text
        assert payload["uploaded_documents"][0]["title"] == "My upload"


# -------------------------------------------------------
# Erasure (right to erasure)
# -------------------------------------------------------

class TestAccountErasure:
    def test_requires_typed_confirmation(self, client, auth_headers):
        response = _delete_with_body(
            client,
            "/api/privacy/account",
            {"confirm": "wrong@example.com"},
            auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "CONFIRM_MISMATCH"

    def test_erases_anonymises_and_keeps_audit(
        self, client, db_session, auth_headers
    ):
        user = db_session.query(User).filter(User.email == "test@example.com").one()
        email = user.email
        user_id = user.id

        session, message = _add_chat(db_session, user_id, content="erase me")
        doc = SourceDocument(
            title="Erase upload", source_type="patent", uploader_id=user_id
        )
        db_session.add(doc)
        db_session.commit()
        client.post(
            "/api/privacy/consent",
            json={"purposes": ["account"], "grant": True},
            headers=auth_headers,
        )
        _grant_source(client, auth_headers)

        audit_before = (
            db_session.query(AuditLog).filter(AuditLog.user_id == user_id).count()
        )
        assert audit_before > 0

        response = _delete_with_body(
            client, "/api/privacy/account", {"confirm": email}, auth_headers
        )
        assert response.status_code == 200, response.json()
        summary = response.json()["data"]

        assert summary["erased"]["chat_messages"] == 1
        assert summary["erased"]["chat_sessions"] == 1
        assert summary["erased"]["uploaded_documents"] == 1
        assert summary["erased"]["data_consents"] == 1
        assert summary["erased"]["source_consents"] == 1
        assert summary["anonymised_user"]["email"] == f"deleted+{user_id}@example.invalid"

        db_session.expire_all()

        # Anonymised, not deleted: the row keeps its id for foreign keys.
        erased_user = db_session.query(User).filter(User.id == user_id).one()
        assert erased_user.email == f"deleted+{user_id}@example.invalid"
        assert erased_user.username is None
        assert erased_user.is_active is False

        # Personal data is gone.
        assert db_session.query(ChatSession).count() == 0
        assert db_session.query(ChatMessage).count() == 0
        assert db_session.query(SourceDocument).count() == 0
        assert db_session.query(DataConsent).count() == 0
        assert db_session.query(SourceConsent).count() == 0

        # Audit survives, detached from the identifier.
        assert (
            db_session.query(AuditLog).filter(AuditLog.user_id == user_id).count() == 0
        )
        erasure_rows = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "data_erasure")
            .all()
        )
        assert len(erasure_rows) == 1
        assert erasure_rows[0].user_id is None
        details = json.loads(erasure_rows[0].details)
        assert details["erased"]["chat_messages"] == 1
        assert email not in erasure_rows[0].details

        # No audit row was destroyed: the earlier trail is still there.
        assert (
            db_session.query(AuditLog).count() >= audit_before + 1
        )


# -------------------------------------------------------
# Audit coverage of the knowledge router (upload/delete/reindex)
# -------------------------------------------------------

class TestKnowledgeAuditCoverage:
    def test_document_delete_is_audited(self, client, db_session, auth_headers):
        me = db_session.query(User).filter(User.email == "test@example.com").one()
        doc = SourceDocument(
            title="Audit me",
            source_type="patent",
            uploader_id=me.id,
            status="PENDING",
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)
        doc_id = doc.id

        response = client.delete(f"/api/knowledge/documents/{doc_id}", headers=auth_headers)
        assert response.status_code == 204, response.text

        entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "delete_document",
                AuditLog.resource == "knowledge_document",
            )
            .one()
        )
        assert entry.resource_id == doc_id
        assert entry.ip_address is not None
        details = json.loads(entry.details)
        assert details["title"] == "Audit me"
        assert db_session.query(SourceDocument).count() == 0

    def test_document_delete_of_another_user_is_404_and_unlogged(
        self, client, db_session, auth_headers, second_user_headers
    ):
        me = db_session.query(User).filter(User.email == "test@example.com").one()
        doc = SourceDocument(
            title="Private", source_type="patent", uploader_id=me.id, status="PENDING"
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        before = db_session.query(AuditLog).filter(
            AuditLog.action == "delete_document"
        ).count()
        response = client.delete(
            f"/api/knowledge/documents/{doc.id}", headers=second_user_headers
        )
        assert response.status_code == 404
        assert (
            db_session.query(AuditLog).filter(AuditLog.action == "delete_document").count()
            == before
        )


# -------------------------------------------------------
# Data-principal entry point on the users router
# -------------------------------------------------------

class TestUserPrivacyEntryPoint:
    def test_me_privacy_maps_the_rights(self, client, auth_headers):
        response = client.get("/api/users/me/privacy", headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["notice_version"]
        assert "account" in data["purposes"]
        assert any(right["right"] == "Access" for right in data["rights"])
        assert data["endpoints"]["export"] == "GET /api/privacy/export"
        assert data["endpoints"]["erasure"] == "DELETE /api/privacy/account"

    def test_me_privacy_requires_auth(self, client):
        assert client.get("/api/users/me/privacy").status_code == 401


# -------------------------------------------------------
# Retention + purge
# -------------------------------------------------------

class TestRetention:
    def test_retention_endpoint_reflects_settings(self, client, auth_headers):
        from app.config import get_settings

        settings = get_settings()
        data = client.get("/api/privacy/retention", headers=auth_headers).json()["data"]
        by_dataset = {entry["dataset"]: entry for entry in data["datasets"]}

        assert (
            by_dataset["chat_messages_and_sessions"]["retention_days"]
            == settings.chat_retention_days
        )
        assert (
            by_dataset["uploaded_documents"]["retention_days"]
            == settings.upload_retention_days
        )
        assert (
            by_dataset["audit_logs"]["retention_days"] == settings.audit_retention_days
        )
        assert data["purge_job"]["scheduled"] is False
        assert data["purge_job"]["endpoint"] == "POST /api/privacy/purge"

    def test_purge_is_admin_only(self, client, auth_headers):
        response = client.post("/api/privacy/purge", headers=auth_headers)
        assert response.status_code == 403

    def test_purge_never_touches_when_retention_is_zero(
        self, client, db_session, auth_headers
    ):
        from app.config import get_settings

        settings = get_settings()
        assert settings.chat_retention_days == 0
        assert settings.upload_retention_days == 0
        assert settings.audit_retention_days == 0

        user = db_session.query(User).filter(User.email == "test@example.com").one()
        _, message = _add_chat(db_session, user.id, content="ancient")
        _backdate(db_session, ChatMessage, message.id, days=3650)
        audit_before = db_session.query(AuditLog).count()
        docs_before = db_session.query(SourceDocument).count()

        admin = _make_admin(client, db_session)
        response = client.post("/api/privacy/purge", headers=admin)
        assert response.status_code == 200, response.json()
        counts = response.json()["data"]["counts"]

        assert counts["chat_messages"] == 0
        assert counts["chat_sessions"] == 0
        assert counts["uploaded_documents"] == 0
        assert counts["audit_logs"] == 0

        db_session.expire_all()
        assert db_session.query(ChatMessage).count() == 1
        assert db_session.query(SourceDocument).count() == docs_before
        assert db_session.query(AuditLog).count() >= audit_before

    def test_purge_applies_a_configured_window(
        self, client, db_session, auth_headers, monkeypatch
    ):
        user = db_session.query(User).filter(User.email == "test@example.com").one()
        _, old_message = _add_chat(db_session, user.id, content="too old")
        _backdate(db_session, ChatMessage, old_message.id, days=120)
        _, fresh_message = _add_chat(db_session, user.id, content="recent")
        _backdate(db_session, ChatMessage, fresh_message.id, days=5)

        _patch_settings(
            monkeypatch,
            chat_retention_days=30,
            upload_retention_days=0,
            audit_retention_days=0,
        )

        admin = _make_admin(client, db_session)
        response = client.post("/api/privacy/purge", headers=admin)
        assert response.status_code == 200, response.json()
        counts = response.json()["data"]["counts"]

        assert counts["chat_messages"] == 1
        db_session.expire_all()
        remaining = [row.content for row in db_session.query(ChatMessage).all()]
        assert remaining == ["recent"]

    def test_purge_audit_window_kept_at_zero_by_default(
        self, client, db_session, auth_headers, monkeypatch
    ):
        user = db_session.query(User).filter(User.email == "test@example.com").one()
        audit_row = (
            db_session.query(AuditLog)
            .filter(AuditLog.user_id == user.id)
            .first()
        )
        assert audit_row is not None
        (
            db_session.query(AuditLog)
            .filter(AuditLog.id == audit_row.id)
            .update(
                {"timestamp": datetime.now(timezone.utc) - timedelta(days=3650)},
                synchronize_session=False,
            )
        )
        db_session.commit()

        _patch_settings(
            monkeypatch,
            chat_retention_days=0,
            upload_retention_days=0,
            audit_retention_days=0,
        )
        admin = _make_admin(client, db_session)
        response = client.post("/api/privacy/purge", headers=admin)
        assert response.status_code == 200
        assert response.json()["data"]["counts"]["audit_logs"] == 0
        db_session.expire_all()
        assert db_session.query(AuditLog).filter(AuditLog.id == audit_row.id).count() == 1
