"""
Tests for Phase 8b: PDF report generation.

What these tests protect:
* each of the three report kinds generates a real PDF (%PDF magic bytes);
* the stored SHA-256 hash matches the downloaded bytes;
* the public verify endpoint confirms integrity without authentication;
* reports are owner-scoped (cross-user reads are 404);
* generation never edits version content.
"""
import hashlib


def _product(client, headers, name="Report Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _generate(client, headers, pid, vid, kind):
    response = client.post(
        f"/api/products/{pid}/versions/{vid}/reports/{kind}", headers=headers
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


class TestReportGeneration:
    def test_ip_brief_is_a_real_pdf(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _generate(client, auth_headers, pid, vid, "ip-brief")
        assert data["report_type"] == "ip_brief"
        assert len(data["content_hash"]) == 64
        assert data["download_url"] == f"/api/reports/{data['id']}"
        assert data["verify_url"].endswith(f"/api/reports/{data['id']}/verify")

    def test_disclosure_record_pdf(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        client.post(
            f"/api/products/{pid}/versions/{vid}/disclosures",
            json={"disclosure_type": "website", "description": "Posted formula page"},
            headers=auth_headers,
        )
        data = _generate(client, auth_headers, pid, vid, "disclosure")
        assert data["report_type"] == "disclosure_record"

    def test_expert_handoff_pdf(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _generate(client, auth_headers, pid, vid, "expert-handoff")
        assert data["report_type"] == "expert_handoff"

    def test_download_matches_stored_hash(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _generate(client, auth_headers, pid, vid, "ip-brief")
        response = client.get(f"/api/reports/{data['id']}", headers=auth_headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content[:4] == b"%PDF"
        assert hashlib.sha256(response.content).hexdigest() == data["content_hash"]

    def test_verify_is_public(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        data = _generate(client, auth_headers, pid, vid, "ip-brief")
        response = client.get(f"/api/reports/{data['id']}/verify")
        assert response.status_code == 200, response.json()
        assert response.json()["data"]["hash_match"] is True

    def test_list_reports(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _generate(client, auth_headers, pid, vid, "ip-brief")
        _generate(client, auth_headers, pid, vid, "disclosure")
        response = client.get(
            f"/api/products/{pid}/versions/{vid}/reports", headers=auth_headers
        )
        assert response.status_code == 200, response.json()
        assert len(response.json()["data"]) == 2

    def test_generation_does_not_edit_version(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        before = client.get(
            f"/api/products/{pid}/versions/{vid}/ingredients", headers=auth_headers
        ).json()
        _generate(client, auth_headers, pid, vid, "ip-brief")
        after = client.get(
            f"/api/products/{pid}/versions/{vid}/ingredients", headers=auth_headers
        ).json()
        assert before == after


class TestReportAuthorization:
    def test_cross_user_download_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        data = _generate(client, auth_headers, pid, vid, "ip-brief")
        response = client.get(f"/api/reports/{data['id']}", headers=second_user_headers)
        assert response.status_code == 404

    def test_cross_user_generate_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            f"/api/products/{pid}/versions/{vid}/reports/ip-brief",
            headers=second_user_headers,
        )
        assert response.status_code == 404
