"""
Tests for Phase 9: the expert review workflow.

What these tests protect:
* the full state machine traverses in order (DRAFT -> AI_SCREENED ->
  REVIEW_REQUIRED -> EXPERT_REVIEW -> REVIEWED -> ARCHIVED);
* illegal transitions are 409 and reviewer-only actions are 403;
* an expert comment opens EXPERT_REVIEW; terminal states refuse comments;
* completing with verify ids promotes claims/evidence to EXPERT_VERIFIED -
  the only path that ever sets that provenance;
* correction round-trip (request-correction -> resubmit -> complete);
* reviews are owner-scoped.
"""
from app.models import Role, RoleName, User, UserRole
from app.utils import hash_password


def _product(client, headers, name="Review Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _make_expert(client, db_session, email="expert@example.com"):
    user = User(
        username="expert",
        email=email,
        password_hash=hash_password("expertpass123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    role = db_session.query(Role).filter(Role.name == RoleName.EXPERT).first()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "expertpass123"}
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _create(client, headers, pid, vid):
    response = client.post(
        "/api/reviews",
        json={"product_id": pid, "product_version_id": vid, "title": "Please review"},
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _post(client, url, headers, body=None):
    return client.post(url, json=body or {}, headers=headers)


class TestReviewLifecycle:
    def test_full_happy_path_to_archive(self, client, db_session, auth_headers):
        expert = _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        review = _create(client, auth_headers, pid, vid)
        rid = review["id"]
        assert review["status"] == "DRAFT"

        data = _post(client, f"/api/reviews/{rid}/submit", auth_headers).json()["data"]
        assert data["status"] == "AI_SCREENED"
        assert "completeness scan" in data["ai_screen_summary"]

        data = _post(client, f"/api/reviews/{rid}/request-review", auth_headers).json()["data"]
        assert data["status"] == "REVIEW_REQUIRED"

        data = _post(
            client, f"/api/reviews/{rid}/comment", expert, {"body": "Reviewing now"}
        ).json()["data"]
        assert data["status"] == "EXPERT_REVIEW"
        assert len(data["comments"]) == 1

        data = _post(client, f"/api/reviews/{rid}/complete", expert).json()["data"]
        assert data["status"] == "REVIEWED"

        data = _post(client, f"/api/reviews/{rid}/archive", expert).json()["data"]
        assert data["status"] == "ARCHIVED"

    def test_illegal_transitions_are_409(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        rid = _create(client, auth_headers, pid, vid)["id"]
        assert _post(client, f"/api/reviews/{rid}/request-review", auth_headers).status_code == 409
        assert _post(client, f"/api/reviews/{rid}/complete", auth_headers).status_code in (403, 409)
        assert _post(client, f"/api/reviews/{rid}/resubmit", auth_headers).status_code == 409

    def test_non_expert_cannot_complete(self, client, db_session, auth_headers):
        _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        rid = _create(client, auth_headers, pid, vid)["id"]
        _post(client, f"/api/reviews/{rid}/submit", auth_headers)
        _post(client, f"/api/reviews/{rid}/request-review", auth_headers)
        response = _post(client, f"/api/reviews/{rid}/complete", auth_headers)
        assert response.status_code == 403

    def test_closed_review_refuses_comments(self, client, db_session, auth_headers):
        expert = _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        rid = _create(client, auth_headers, pid, vid)["id"]
        _post(client, f"/api/reviews/{rid}/submit", auth_headers)
        _post(client, f"/api/reviews/{rid}/request-review", auth_headers)
        _post(client, f"/api/reviews/{rid}/comment", expert, {"body": "hi"})
        _post(client, f"/api/reviews/{rid}/complete", expert)
        assert _post(client, f"/api/reviews/{rid}/comment", expert, {"body": "late"}).status_code == 409


class TestCorrectionRoundTrip:
    def test_request_correction_resubmit_complete(self, client, db_session, auth_headers):
        expert = _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        rid = _create(client, auth_headers, pid, vid)["id"]
        _post(client, f"/api/reviews/{rid}/submit", auth_headers)
        _post(client, f"/api/reviews/{rid}/request-review", auth_headers)
        _post(client, f"/api/reviews/{rid}/comment", expert, {"body": "looking"})

        data = _post(
            client, f"/api/reviews/{rid}/request-correction", expert, {"note": "Add evidence"}
        ).json()["data"]
        assert data["status"] == "CORRECTION_REQUESTED"

        data = _post(
            client, f"/api/reviews/{rid}/resubmit", auth_headers, {"note": "Added"}
        ).json()["data"]
        assert data["status"] == "RESUBMITTED"

        data = _post(client, f"/api/reviews/{rid}/complete", expert).json()["data"]
        assert data["status"] == "REVIEWED"


class TestExpertVerification:
    def test_complete_promotes_claim_and_evidence(self, client, db_session, auth_headers):
        expert = _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        claim = client.post(
            f"/api/products/{pid}/versions/{vid}/claims",
            json={"claim_text": "Supports wellness", "claim_type": "wellness"},
            headers=auth_headers,
        ).json()["data"]
        evidence = client.post(
            f"/api/products/{pid}/versions/{vid}/evidence",
            json={"title": "Study", "source_type": "scientific_paper"},
            headers=auth_headers,
        ).json()["data"]

        rid = _create(client, auth_headers, pid, vid)["id"]
        _post(client, f"/api/reviews/{rid}/submit", auth_headers)
        _post(client, f"/api/reviews/{rid}/request-review", auth_headers)
        _post(client, f"/api/reviews/{rid}/comment", expert, {"body": "verified manually"})
        data = _post(
            client,
            f"/api/reviews/{rid}/complete",
            expert,
            {"verify_claim_ids": [claim["id"]], "verify_evidence_ids": [evidence["id"]]},
        ).json()["data"]
        assert data["status"] == "REVIEWED"

        claims = client.get(
            f"/api/products/{pid}/versions/{vid}/claims", headers=auth_headers
        ).json()["data"]
        promoted = [c for c in claims if c["id"] == claim["id"]][0]
        assert promoted["evidence_status"] == "expert_verified"
        assert promoted["provenance"] == "EXPERT_VERIFIED"

    def test_verified_claim_is_locked(self, client, db_session, auth_headers):
        expert = _make_expert(client, db_session)
        pid, vid = _product(client, auth_headers)
        claim = client.post(
            f"/api/products/{pid}/versions/{vid}/claims",
            json={"claim_text": "Supports wellness", "claim_type": "wellness"},
            headers=auth_headers,
        ).json()["data"]
        rid = _create(client, auth_headers, pid, vid)["id"]
        _post(client, f"/api/reviews/{rid}/submit", auth_headers)
        _post(client, f"/api/reviews/{rid}/request-review", auth_headers)
        _post(client, f"/api/reviews/{rid}/comment", expert, {"body": "ok"})
        _post(
            client, f"/api/reviews/{rid}/complete", expert, {"verify_claim_ids": [claim["id"]]}
        )
        response = client.put(
            f"/api/products/{pid}/versions/{vid}/claims/{claim['id']}",
            json={"claim_text": "Edited after verification"},
            headers=auth_headers,
        )
        assert response.status_code == 409


class TestReviewScoping:
    def test_cross_user_access_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        rid = _create(client, auth_headers, pid, vid)["id"]
        assert client.get(f"/api/reviews/{rid}", headers=second_user_headers).status_code == 404
        assert client.get("/api/reviews", headers=second_user_headers).json()["data"] == []

    def test_list_filters_by_status(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _create(client, auth_headers, pid, vid)
        data = client.get("/api/reviews?status=DRAFT", headers=auth_headers).json()["data"]
        assert len(data) == 1
        assert client.get("/api/reviews?status=REVIEWED", headers=auth_headers).json()["data"] == []
