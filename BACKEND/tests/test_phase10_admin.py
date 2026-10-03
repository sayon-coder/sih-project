"""
Tests for Phase 10: dashboard, audit and admin endpoints.

What these tests protect:
* the dashboard reflects real counts (products, versions, reviews, claims);
* audit endpoints only expose the caller's own entries (404 otherwise);
* every admin route is 403 for non-admins and functional for admins.
"""
from app.models import Role, RoleName, User, UserRole
from app.utils import hash_password


def _product(client, headers, name="Dashboard Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _make_admin(client, db_session):
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
        "/api/auth/login", json={"email": "admin@example.com", "password": "adminpass123"}
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


class TestDashboard:
    def test_counts_reflect_reality(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        client.post(
            f"/api/products/{pid}/versions/{vid}/claims",
            json={"claim_text": "Needs proof", "claim_type": "therapeutic"},
            headers=auth_headers,
        )
        # flip the claim to needs_evidence via analyze? No - create directly:
        data = client.get("/api/dashboard", headers=auth_headers).json()["data"]
        assert data["product_count"] == 1
        assert data["version_count"] == 1
        assert data["pending_reviews"] == 0
        assert data["recent_activity"], "creating a product must be audited"

    def test_second_user_sees_only_own(self, client, auth_headers, second_user_headers):
        _product(client, auth_headers)
        data = client.get("/api/dashboard", headers=second_user_headers).json()["data"]
        assert data["product_count"] == 0


class TestAudit:
    def test_own_entries_visible(self, client, auth_headers):
        _product(client, auth_headers)
        data = client.get("/api/audit", headers=auth_headers).json()["data"]
        assert any(e["action"] == "create_product" for e in data)

    def test_other_users_entry_is_404(self, client, auth_headers, second_user_headers):
        _product(client, auth_headers)
        mine = client.get("/api/audit", headers=auth_headers).json()["data"][0]["id"]
        assert client.get(f"/api/audit/{mine}", headers=second_user_headers).status_code == 404

    def test_missing_entry_is_404(self, client, auth_headers):
        assert client.get("/api/audit/999999", headers=auth_headers).status_code == 404


class TestAdmin:
    def test_non_admin_forbidden_everywhere(self, client, auth_headers):
        assert client.get("/api/admin/users", headers=auth_headers).status_code == 403
        assert client.get("/api/admin/sources", headers=auth_headers).status_code == 403
        assert client.get("/api/admin/rag/status", headers=auth_headers).status_code == 403
        assert client.get("/api/admin/audit", headers=auth_headers).status_code == 403
        assert client.post(
            "/api/admin/sources",
            json={"title": "x", "source_type": "law"},
            headers=auth_headers,
        ).status_code == 403

    def test_admin_users_and_audit(self, client, db_session, auth_headers):
        admin = _make_admin(client, db_session)
        _product(client, auth_headers)
        users = client.get("/api/admin/users", headers=admin).json()["data"]
        assert len(users) >= 2
        entries = client.get("/api/admin/audit", headers=admin).json()["data"]
        assert any(e["action"] == "create_product" for e in entries)

    def test_admin_source_crud(self, client, db_session, auth_headers):
        admin = _make_admin(client, db_session)
        created = client.post(
            "/api/admin/sources",
            json={"title": "Test Act", "source_type": "law", "jurisdiction": "IN"},
            headers=admin,
        )
        assert created.status_code == 201, created.json()
        sid = created.json()["data"]["id"]

        updated = client.put(
            f"/api/admin/sources/{sid}", json={"is_public": True}, headers=admin
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["is_public"] is True

        listed = client.get("/api/admin/sources", headers=admin).json()["data"]
        assert any(s["id"] == sid for s in listed)

        deleted = client.delete(f"/api/admin/sources/{sid}", headers=admin)
        assert deleted.status_code == 200
        assert client.get("/api/admin/sources", headers=admin).json()["data"] == [
            s for s in listed if s["id"] != sid
        ]

    def test_admin_rag_status(self, client, db_session, auth_headers):
        admin = _make_admin(client, db_session)
        data = client.get("/api/admin/rag/status", headers=admin).json()["data"]
        assert "documents_total" in data
        assert "embedding_model" in data
        assert "demo_mode" in data
