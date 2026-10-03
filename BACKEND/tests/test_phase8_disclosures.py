"""
Tests for Phase 8a: public-disclosure tracking and disclosure review.

What these tests protect:
* disclosure events are recorded against one owned version (404 otherwise);
* each record carries a SHA-256 hash and a unique verification id;
* the mandatory invention-disclosure disclaimer travels with every record;
* the verify endpoint is public and reports whether the stored hash matches;
* the review endpoint is advisory (never a legal conclusion) and returns the
  PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED vocabulary when events exist;
* an empty version reports NO_EVENTS_RECORDED rather than pretending;
* recording a disclosure never edits version content.
"""
import hashlib
import json


def _product(client, headers, name="Disclosure Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _record(client, headers, pid, vid, **fields):
    payload = {
        "disclosure_type": "conference_presentation",
        "description": "Presented the cold-press method at a conference",
    }
    payload.update(fields)
    response = client.post(f"{_base(pid, vid)}/disclosures", json=payload, headers=headers)
    assert response.status_code == 201, response.json()
    return response.json()["data"]


class TestDisclosureRecording:
    def test_create_returns_hash_and_verification_id(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _record(client, auth_headers, pid, vid)
        assert len(data["record_hash"]) == 64
        int(data["record_hash"], 16)  # valid hex
        assert data["verification_id"]
        assert "not a patent application" in data["disclaimer"]

    def test_create_requires_description(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            f"{_base(pid, vid)}/disclosures",
            json={"disclosure_type": "website", "description": "  "},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_rejects_unknown_type(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            f"{_base(pid, vid)}/disclosures",
            json={"disclosure_type": "press_release", "description": "x"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_list_returns_newest_first(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _record(client, auth_headers, pid, vid, description="first")
        second = _record(client, auth_headers, pid, vid, description="second")
        response = client.get(f"{_base(pid, vid)}/disclosures", headers=auth_headers)
        assert response.status_code == 200, response.json()
        items = response.json()["data"]
        assert len(items) == 2
        assert items[0]["id"] == second["id"]

    def test_hash_covers_payload(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _record(
            client,
            auth_headers,
            pid,
            vid,
            disclosure_type="publication",
            description="Journal draft",
            venue_or_channel="Journal of Ayurveda",
        )
        assert len(data["record_hash"]) == 64

    def test_recording_does_not_edit_version(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        before = client.get(f"{_base(pid, vid)}/ingredients", headers=auth_headers).json()
        _record(client, auth_headers, pid, vid)
        after = client.get(f"{_base(pid, vid)}/ingredients", headers=auth_headers).json()
        assert before == after


class TestDisclosureAuthorization:
    def test_cross_user_read_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        _record(client, auth_headers, pid, vid)
        response = client.get(f"{_base(pid, vid)}/disclosures", headers=second_user_headers)
        assert response.status_code == 404

    def test_cross_user_write_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            f"{_base(pid, vid)}/disclosures",
            json={"disclosure_type": "website", "description": "hi"},
            headers=second_user_headers,
        )
        assert response.status_code == 404

    def test_version_must_belong_to_product(self, client, auth_headers):
        pid_a, vid_a = _product(client, auth_headers, name="A")
        _pid_b, vid_b = _product(client, auth_headers, name="B")
        response = client.post(
            f"/api/products/{pid_a}/versions/{vid_b}/disclosures",
            json={"disclosure_type": "website", "description": "hi"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_global_get_respects_ownership(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        data = _record(client, auth_headers, pid, vid)
        response = client.get(f"/api/disclosures/{data['id']}", headers=second_user_headers)
        assert response.status_code == 404


class TestGlobalEndpoints:
    def test_global_create(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            "/api/disclosures",
            json={
                "product_id": pid,
                "product_version_id": vid,
                "disclosure_type": "investor_disclosure",
                "description": "Shared deck with investors",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.json()
        assert response.json()["data"]["product_version_id"] == vid

    def test_global_get(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        created = _record(client, auth_headers, pid, vid)
        response = client.get(f"/api/disclosures/{created['id']}", headers=auth_headers)
        assert response.status_code == 200, response.json()
        assert response.json()["data"]["id"] == created["id"]

    def test_verify_is_public_and_hash_matches(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        created = _record(client, auth_headers, pid, vid)
        response = client.get(f"/api/disclosures/{created['id']}/verify")
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["hash_match"] is True
        assert data["record_hash"] == created["record_hash"]
        assert "not a patent application" in data["disclaimer"]

    def test_verify_missing_is_404(self, client):
        assert client.get("/api/disclosures/999999/verify").status_code == 404


class TestDisclosureReview:
    def test_empty_version_reports_no_events(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(f"{_base(pid, vid)}/disclosure-review", headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["review_status"] == "NO_EVENTS_RECORDED"
        assert data["event_count"] == 0

    def test_review_recommends_review_when_events_exist(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _record(client, auth_headers, pid, vid)
        response = client.post(f"{_base(pid, vid)}/disclosure-review", headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["review_status"] == "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED"
        assert data["event_count"] == 1
        assert data["considerations"]
        assert data["review_questions"]
        blob = json.dumps(data)
        for banned in ("patentable", "definitely novel", "priority established"):
            assert banned not in blob.lower()

    def test_review_is_version_scoped(self, client, auth_headers):
        pid, vid1 = _product(client, auth_headers)
        response = client.post(
            f"/api/products/{pid}/versions", json={"change_reason": "v2"}, headers=auth_headers
        )
        vid2 = response.json()["data"]["id"]
        _record(client, auth_headers, pid, vid2)
        first = client.post(f"{_base(pid, vid1)}/disclosure-review", headers=auth_headers).json()["data"]
        second = client.post(f"{_base(pid, vid2)}/disclosure-review", headers=auth_headers).json()["data"]
        assert first["event_count"] == 0
        assert second["event_count"] == 1
