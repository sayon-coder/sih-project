"""
Tests for the gap-closure endpoints (master prompt section 7):

  - Public sources API : GET /api/sources, /sources/search, /sources/{id}
  - Users API          : GET/PUT /api/users/me, GET /api/users/me/history
  - Knowledge index    : POST /api/knowledge/index

These endpoints were specified in the master prompt but missing from the
initial route inventory; this suite pins their behaviour (visibility rules,
privilege safety, audit logging and honest index counts).
"""
import os
import tempfile

import pytest

from app.models.rag_models import SourceDocument
from app.services.audit_service import AuditService


# -------------------------------------------------------
# Helpers / fixtures
# -------------------------------------------------------

def _make_doc(db, uploader_id, title, status, file_path=None, is_public=False):
    doc = SourceDocument(
        title=title,
        source_type="other",
        language="en",
        uploader_id=uploader_id,
        is_public=is_public,
        status=status,
        chunk_count=0,
        file_path=file_path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _tmp_text_file() -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="gap-index-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("Ashwagandha root supports restful sleep. " * 30)
    return path


@pytest.fixture
def public_source(db_session, test_user):
    doc = SourceDocument(
        title="Ayurveda Pharmacopoeia of India",
        source_type="official_guidance",
        jurisdiction="IN",
        language="en",
        author="AYUSH",
        source_url="https://example.gov.in/pharmacopoeia",
        is_public=True,
        uploader_id=test_user.id,
        status="INDEXED",
        chunk_count=3,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


@pytest.fixture
def private_foreign_source(db_session, second_user):
    return _make_doc(
        db_session,
        second_user.id,
        "Unpublished research notes on Withania",
        "INDEXED",
        is_public=False,
    )


# -------------------------------------------------------
# Public sources API
# -------------------------------------------------------

class TestSourcesApi:
    def test_sources_require_authentication(self, client):
        assert client.get("/api/sources").status_code == 401
        assert client.get("/api/sources/search?q=ayurveda").status_code == 401
        assert client.get("/api/sources/1").status_code == 401

    def test_list_sources_shows_public_hides_foreign_private(
        self, client, auth_headers, public_source, private_foreign_source
    ):
        resp = client.get("/api/sources", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        ids = [s["id"] for s in body["data"]]
        assert public_source.id in ids
        assert private_foreign_source.id not in ids

    def test_list_response_exposes_no_internals(
        self, client, auth_headers, public_source
    ):
        resp = client.get("/api/sources", headers=auth_headers)
        item = resp.json()["data"][0]
        assert "file_path" not in item
        assert "document_hash" not in item

    def test_search_matches_visible_sources(
        self, client, auth_headers, public_source, private_foreign_source
    ):
        resp = client.get("/api/sources/search?q=pharmacopoeia", headers=auth_headers)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["data"]]
        assert ids == [public_source.id]

    def test_search_never_leaks_foreign_private(
        self, client, auth_headers, private_foreign_source
    ):
        resp = client.get("/api/sources/search?q=Withania", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_search_requires_query(self, client, auth_headers):
        assert client.get("/api/sources/search", headers=auth_headers).status_code == 422

    def test_fetch_single_source(
        self, client, auth_headers, public_source, private_foreign_source
    ):
        resp = client.get(f"/api/sources/{public_source.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "Ayurveda Pharmacopoeia of India"

        # another user's private document behaves as if it does not exist
        assert (
            client.get(f"/api/sources/{private_foreign_source.id}", headers=auth_headers)
            .status_code
            == 404
        )
        assert client.get("/api/sources/999999", headers=auth_headers).status_code == 404


# -------------------------------------------------------
# Users API
# -------------------------------------------------------

class TestUsersApi:
    def test_me_requires_authentication(self, client):
        assert client.get("/api/users/me").status_code == 401
        assert client.put("/api/users/me", json={"username": "x-user"}).status_code == 401
        assert client.get("/api/users/me/history").status_code == 401

    def test_get_me_returns_own_profile(self, client, auth_headers, test_user):
        resp = client.get("/api/users/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == test_user.id
        assert data["email"] == "test@example.com"
        assert data["is_active"] is True
        assert isinstance(data["roles"], list)

    def test_update_username_round_trips(self, client, auth_headers, test_user, db_session):
        resp = client.put("/api/users/me", json={"username": "renamed-user"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "renamed-user"

        db_session.refresh(test_user)
        assert test_user.username == "renamed-user"

        again = client.get("/api/users/me", headers=auth_headers)
        assert again.json()["data"]["username"] == "renamed-user"

    def test_update_email_round_trips(self, client, auth_headers, test_user, db_session):
        resp = client.put(
            "/api/users/me", json={"email": "renamed@example.com"}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == "renamed@example.com"
        db_session.refresh(test_user)
        assert test_user.email == "renamed@example.com"

    def test_email_conflict_is_rejected(self, client, auth_headers, second_user):
        resp = client.put(
            "/api/users/me", json={"email": "other@example.com"}, headers=auth_headers
        )
        assert resp.status_code == 409

    def test_invalid_email_is_rejected(self, client, auth_headers):
        resp = client.put("/api/users/me", json={"email": "not-an-email"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_empty_update_is_rejected(self, client, auth_headers):
        resp = client.put("/api/users/me", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_privileged_fields_are_not_writable(
        self, client, auth_headers, test_user, db_session
    ):
        resp = client.put(
            "/api/users/me",
            json={
                "username": "sneaky-user",
                "is_active": False,
                "roles": ["ADMIN"],
                "password_hash": "not-a-hash",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["username"] == "sneaky-user"
        assert data["roles"] == []
        assert data["is_active"] is True

        db_session.refresh(test_user)
        assert test_user.is_active is True
        assert test_user.password_hash.startswith(("$2b$", "$2a$", "$2y$"))

    def test_history_contains_profile_update(
        self, client, auth_headers, second_user, db_session
    ):
        # an action belonging to another user must never appear
        AuditService.log_action(
            db_session, second_user.id, "delete_product", "product", 999
        )

        resp = client.put("/api/users/me", json={"username": "history-user"}, headers=auth_headers)
        assert resp.status_code == 200

        hist = client.get("/api/users/me/history", headers=auth_headers)
        assert hist.status_code == 200
        entries = hist.json()["data"]
        actions = [e["action"] for e in entries]
        assert "update_profile" in actions
        assert "delete_product" not in actions
        assert all("timestamp" in e and "resource" in e for e in entries)

    def test_history_honours_limit(self, client, auth_headers):
        resp = client.get("/api/users/me/history?limit=1", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) <= 1


# -------------------------------------------------------
# Knowledge index trigger
# -------------------------------------------------------

class TestKnowledgeIndex:
    def test_index_requires_authentication(self, client):
        assert client.post("/api/knowledge/index", json={}).status_code == 401

    def test_index_with_nothing_pending(self, client, auth_headers):
        resp = client.post("/api/knowledge/index", json={}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == {
            "attempted": 0,
            "indexed": 0,
            "failed": 0,
            "skipped": 0,
        }

    def test_index_scopes_to_own_documents(
        self, client, auth_headers, db_session, second_user
    ):
        path = _tmp_text_file()
        try:
            foreign = _make_doc(
                db_session, second_user.id, "Foreign pending doc", "PENDING", file_path=path
            )
            resp = client.post("/api/knowledge/index", json={}, headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json()["data"]["attempted"] == 0

            db_session.refresh(foreign)
            assert foreign.status == "PENDING"
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_index_skips_documents_without_files(
        self, client, auth_headers, db_session, test_user
    ):
        registered = _make_doc(
            db_session, test_user.id, "Registered source without file", "PENDING"
        )
        resp = client.post("/api/knowledge/index", json={}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["attempted"] == 0
        assert data["skipped"] == 1

        db_session.refresh(registered)
        assert registered.status == "PENDING"

    def test_index_processes_own_pending_document(
        self, client, auth_headers, db_session, test_user
    ):
        path = _tmp_text_file()
        try:
            doc = _make_doc(
                db_session, test_user.id, "Own pending doc", "PENDING", file_path=path
            )
            resp = client.post("/api/knowledge/index", json={}, headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["attempted"] == 1
            assert data["skipped"] == 0
            assert data["indexed"] + data["failed"] == 1

            db_session.refresh(doc)
            # Outcome depends on the environment (PostgreSQL+embeddings vs the
            # SQLite test harness); either way the status must be terminal and
            # failures must record a reason.
            assert doc.status in ("INDEXED", "FAILED")
            if doc.status == "FAILED":
                assert doc.error_message
            else:
                assert doc.chunk_count >= 1
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_index_counts_are_reported(
        self, client, auth_headers, db_session, test_user
    ):
        path = _tmp_text_file()
        try:
            _make_doc(db_session, test_user.id, "Pending A", "PENDING", file_path=path)
            _make_doc(db_session, test_user.id, "Registered B", "PENDING")
            resp = client.post("/api/knowledge/index", json={}, headers=auth_headers)
            data = resp.json()["data"]
            assert data["attempted"] == 1
            assert data["skipped"] == 1
            assert data["indexed"] + data["failed"] == 1
        finally:
            if os.path.exists(path):
                os.remove(path)
