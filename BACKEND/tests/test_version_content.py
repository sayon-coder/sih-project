"""
Tests for Phase 3: ingredients, formulation, claims, evidence and target
markets under a product version.

The suite focuses on the three guarantees the phase is responsible for:

* authorization - nested content is only reachable through an owned product
* provenance    - user input stays USER_PROVIDED and verified data is protected
* integrity     - every edit refreshes the version's snapshot and content hash
"""
import re

import pytest

from app.models import Ingredient, ProductVersion
from app.services.provenance import Provenance

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _product_and_version(client, headers, name="Content Product"):
    """Helper: create a product and return (product_id, version_id)."""
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _content_hash(client, headers, pid, vid):
    response = client.get(_base(pid, vid), headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()["data"]["content_hash"]


class TestIngredientCrud:
    def test_create_list_update_delete(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        created = client.post(
            f"{base}/ingredients",
            json={
                "common_name": "Ashwagandha",
                "botanical_name": "Withania somnifera",
                "sanskrit_name": "Ashwagandha",
                "plant_part": "root",
                "quantity": 250.0,
                "quantity_unit": "mg",
                "source_type": "cultivated",
                "source_location": "Madhya Pradesh",
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.json()
        ingredient = created.json()["data"]
        assert ingredient["provenance"] == "USER_PROVIDED"
        assert ingredient["source_type"] == "cultivated"

        listed = client.get(f"{base}/ingredients", headers=auth_headers).json()
        assert listed["data"][0]["common_name"] == "Ashwagandha"

        updated = client.put(
            f"{base}/ingredients/{ingredient['id']}",
            json={"source_type": "wild", "source_location": "Himalayas"},
            headers=auth_headers,
        )
        assert updated.status_code == 200, updated.json()
        assert updated.json()["data"]["source_type"] == "wild"
        assert updated.json()["data"]["common_name"] == "Ashwagandha"

        deleted = client.delete(
            f"{base}/ingredients/{ingredient['id']}", headers=auth_headers
        )
        assert deleted.status_code == 200
        assert client.get(f"{base}/ingredients", headers=auth_headers).json()["data"] == []


class TestContentHashRefresh:
    """Each edit must move the version's content hash, and only its own."""

    def test_hash_changes_across_ingredient_lifecycle(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)
        baseline = _content_hash(client, auth_headers, pid, vid)
        assert baseline is not None

        created = client.post(
            f"{base}/ingredients",
            json={"common_name": "Turmeric", "botanical_name": "Curcuma longa"},
            headers=auth_headers,
        ).json()["data"]

        after_add = _content_hash(client, auth_headers, pid, vid)
        assert HEX64.match(after_add)
        assert after_add != baseline

        client.put(
            f"{base}/ingredients/{created['id']}",
            json={"quantity": 100.0, "quantity_unit": "mg"},
            headers=auth_headers,
        )
        after_update = _content_hash(client, auth_headers, pid, vid)
        assert after_update != after_add

        client.delete(f"{base}/ingredients/{created['id']}", headers=auth_headers)
        after_delete = _content_hash(client, auth_headers, pid, vid)
        assert after_delete != after_update
        # Back to an empty version -> identical content -> original hash.
        assert after_delete == baseline

    def test_snapshot_records_content(self, client, auth_headers, db_session):
        pid, vid = _product_and_version(client, auth_headers)
        client.post(
            f"{_base(pid, vid)}/ingredients",
            json={"common_name": "Brahmi", "botanical_name": "Bacopa monnieri"},
            headers=auth_headers,
        )

        version = db_session.query(ProductVersion).filter_by(id=vid).first()
        assert "Brahmi" in version.snapshot_data
        assert "USER_PROVIDED" in version.snapshot_data

    def test_editing_one_version_leaves_sibling_hash_untouched(
        self, client, auth_headers
    ):
        pid, v1 = _product_and_version(client, auth_headers)

        # v2 inherits v1's content, so both start with the same hash.
        v2 = client.post(
            f"/api/products/{pid}/versions",
            json={"change_reason": "second"},
            headers=auth_headers,
        ).json()["data"]["id"]

        v1_hash = _content_hash(client, auth_headers, pid, v1)
        assert _content_hash(client, auth_headers, pid, v2) == v1_hash

        client.post(
            f"{_base(pid, v2)}/ingredients",
            json={"common_name": "Guduchi"},
            headers=auth_headers,
        )

        assert _content_hash(client, auth_headers, pid, v2) != v1_hash
        assert _content_hash(client, auth_headers, pid, v1) == v1_hash


class TestFormulation:
    def test_get_is_null_before_put(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        response = client.get(f"{_base(pid, vid)}/formulation", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"] is None

    def test_put_creates_then_updates_same_row(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        created = client.put(
            f"{base}/formulation",
            json={
                "process_description": "Cold percolation",
                "extraction_method": "cold-press",
                "solvent": "water",
                "temperature": 40.0,
                "temperature_unit": "C",
                "duration": 72.0,
                "duration_unit": "hours",
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.json()
        formulation_id = created.json()["data"]["id"]

        updated = client.put(
            f"{base}/formulation",
            json={"temperature": 55.0},
            headers=auth_headers,
        )
        assert updated.status_code == 200
        payload = updated.json()["data"]
        assert payload["id"] == formulation_id
        assert payload["temperature"] == 55.0
        # Omitted field is unchanged (PUT merges instead of replacing).
        assert payload["solvent"] == "water"

    def test_formulation_changes_hash(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        before = _content_hash(client, auth_headers, pid, vid)

        client.put(
            f"{_base(pid, vid)}/formulation",
            json={"extraction_method": "soxhlet"},
            headers=auth_headers,
        )
        assert _content_hash(client, auth_headers, pid, vid) != before


class TestClaimToEvidenceFirewall:
    def test_new_claim_is_user_provided(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)

        response = client.post(
            f"{_base(pid, vid)}/claims",
            json={
                "claim_text": "Increases bioavailability by 40%",
                "claim_type": "therapeutic",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.json()
        claim = response.json()["data"]
        assert claim["provenance"] == "USER_PROVIDED"
        assert claim["evidence_status"] == "user_provided"
        assert claim["review_status"] == "pending"

    def test_user_cannot_assert_supported_evidence_status(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)

        response = client.post(
            f"{_base(pid, vid)}/claims",
            json={
                "claim_text": "Clinically proven to cure diabetes",
                "evidence_status": "supported",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
        assert "cannot be set by a user" in response.json()["detail"]

    def test_claim_crud(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        claim = client.post(
            f"{base}/claims",
            json={"claim_text": "Supports immunity", "claim_type": "wellness"},
            headers=auth_headers,
        ).json()["data"]

        listed = client.get(f"{base}/claims", headers=auth_headers).json()["data"]
        assert len(listed) == 1

        updated = client.put(
            f"{base}/claims/{claim['id']}",
            json={"claim_text": "Traditionally used to support immunity"},
            headers=auth_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["claim_text"].startswith("Traditionally")

        assert (
            client.delete(f"{base}/claims/{claim['id']}", headers=auth_headers).status_code
            == 200
        )
        assert client.get(f"{base}/claims", headers=auth_headers).json()["data"] == []

    def test_expert_verified_claim_is_protected(
        self, client, auth_headers, db_session
    ):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        claim = client.post(
            f"{base}/claims",
            json={"claim_text": "Verified claim"},
            headers=auth_headers,
        ).json()["data"]

        # Simulate the Phase 9 expert workflow promoting the record.
        from app.models import Claim

        row = db_session.query(Claim).filter_by(id=claim["id"]).first()
        row.provenance = Provenance.EXPERT_VERIFIED.value
        db_session.commit()

        update = client.put(
            f"{base}/claims/{claim['id']}",
            json={"claim_text": "Rewritten by a user"},
            headers=auth_headers,
        )
        assert update.status_code == 409
        assert "EXPERT_VERIFIED" in update.json()["detail"]

        delete = client.delete(f"{base}/claims/{claim['id']}", headers=auth_headers)
        assert delete.status_code == 409

        # The verified text is intact.
        detail = client.get(f"{base}/claims", headers=auth_headers).json()["data"]
        assert detail[0]["claim_text"] == "Verified claim"

    def test_expert_verified_ingredient_is_protected(
        self, client, auth_headers, db_session
    ):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        ingredient = client.post(
            f"{base}/ingredients", json={"common_name": "Saffron"}, headers=auth_headers
        ).json()["data"]

        row = db_session.query(Ingredient).filter_by(id=ingredient["id"]).first()
        row.provenance = Provenance.EXPERT_VERIFIED.value
        db_session.commit()

        response = client.put(
            f"{base}/ingredients/{ingredient['id']}",
            json={"common_name": "Fake saffron"},
            headers=auth_headers,
        )
        assert response.status_code == 409


class TestEvidence:
    def test_create_sets_pending_and_provenance(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)

        response = client.post(
            f"{_base(pid, vid)}/evidence",
            json={
                "title": "Clinical evaluation of Withania somnifera",
                "evidence_type": "clinical_trial",
                "doi": "10.1000/example",
                "publication_date": "2021-06-15",
                "language": "en",
                "authors": "Sharma et al.",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.json()
        evidence = response.json()["data"]
        assert evidence["provenance"] == "USER_PROVIDED"
        assert evidence["verification_status"] == "pending"
        assert evidence["publication_date"] == "2021-06-15"
        # No document has been ingested yet, so there is no file hash.
        assert evidence["document_hash"] is None

    def test_get_single_evidence(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        evidence = client.post(
            f"{base}/evidence",
            json={"title": "Charaka Samhita reference", "evidence_type": "traditional_text"},
            headers=auth_headers,
        ).json()["data"]

        response = client.get(f"{base}/evidence/{evidence['id']}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Charaka Samhita reference"

        listed = client.get(f"{base}/evidence", headers=auth_headers).json()["data"]
        assert len(listed) == 1

    def test_user_cannot_promote_verification(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        evidence = client.post(
            f"{base}/evidence",
            json={"title": "Preprint", "source_url": "https://example.org/paper"},
            headers=auth_headers,
        ).json()["data"]

        response = client.put(
            f"{base}/evidence/{evidence['id']}",
            json={"verification_status": "verified"},
            headers=auth_headers,
        )
        assert response.status_code == 422

        # Metadata edits are still allowed.
        ok = client.put(
            f"{base}/evidence/{evidence['id']}",
            json={"authors": "Anonymous"},
            headers=auth_headers,
        )
        assert ok.status_code == 200
        assert ok.json()["data"]["verification_status"] == "pending"


class TestTargetMarkets:
    def test_crud(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        base = _base(pid, vid)

        market = client.post(
            f"{base}/target-markets",
            json={"country": "India", "region": "South Asia", "regulatory_status": "planned"},
            headers=auth_headers,
        )
        assert market.status_code == 201, market.json()
        market_id = market.json()["data"]["id"]

        updated = client.put(
            f"{base}/target-markets/{market_id}",
            json={"regulatory_status": "submitted"},
            headers=auth_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["regulatory_status"] == "submitted"
        assert updated.json()["data"]["country"] == "India"

        assert (
            client.delete(f"{base}/target-markets/{market_id}", headers=auth_headers).status_code
            == 200
        )
        assert client.get(f"{base}/target-markets", headers=auth_headers).json()["data"] == []

    def test_market_changes_hash(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        before = _content_hash(client, auth_headers, pid, vid)

        client.post(
            f"{_base(pid, vid)}/target-markets",
            json={"country": "United States"},
            headers=auth_headers,
        )
        assert _content_hash(client, auth_headers, pid, vid) != before


class TestNestedAuthorization:
    """Nested content must not be reachable across users or versions."""

    def test_other_user_cannot_touch_any_nested_route(
        self, client, auth_headers, second_user_headers
    ):
        pid, vid = _product_and_version(client, auth_headers, name="Private product")
        base = _base(pid, vid)

        ingredient = client.post(
            f"{base}/ingredients", json={"common_name": "Neem"}, headers=auth_headers
        ).json()["data"]

        assert client.get(f"{base}/ingredients", headers=second_user_headers).status_code == 404
        assert (
            client.post(
                f"{base}/ingredients",
                json={"common_name": "Stolen"},
                headers=second_user_headers,
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"{base}/ingredients/{ingredient['id']}",
                json={"common_name": "Stolen"},
                headers=second_user_headers,
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"{base}/ingredients/{ingredient['id']}", headers=second_user_headers
            ).status_code
            == 404
        )
        assert client.get(f"{base}/formulation", headers=second_user_headers).status_code == 404
        assert (
            client.put(
                f"{base}/formulation", json={"solvent": "ethanol"}, headers=second_user_headers
            ).status_code
            == 404
        )
        assert client.get(f"{base}/claims", headers=second_user_headers).status_code == 404
        assert client.get(f"{base}/evidence", headers=second_user_headers).status_code == 404
        assert (
            client.get(f"{base}/target-markets", headers=second_user_headers).status_code == 404
        )

        # The owner's data is untouched.
        assert (
            client.get(f"{base}/ingredients", headers=auth_headers).json()["data"][0][
                "common_name"
            ]
            == "Neem"
        )

    def test_child_id_from_another_version_is_not_reachable(self, client, auth_headers):
        pid, v1 = _product_and_version(client, auth_headers)

        ingredient = client.post(
            f"{_base(pid, v1)}/ingredients",
            json={"common_name": "Triphala"},
            headers=auth_headers,
        ).json()["data"]

        v2 = client.post(
            f"/api/products/{pid}/versions",
            json={"change_reason": "second", "start_empty": True},
            headers=auth_headers,
        ).json()["data"]["id"]

        response = client.put(
            f"{_base(pid, v2)}/ingredients/{ingredient['id']}",
            json={"common_name": "Hijacked"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_unknown_version_returns_404(self, client, auth_headers):
        pid, _ = _product_and_version(client, auth_headers)
        response = client.get(f"{_base(pid, 99999)}/ingredients", headers=auth_headers)
        assert response.status_code == 404


class TestAuditTrail:
    """Every content edit should leave an audit entry."""

    def test_ingredient_creation_is_audited(
        self, client, auth_headers, db_session
    ):
        from app.models import AuditLog

        pid, vid = _product_and_version(client, auth_headers)
        client.post(
            f"{_base(pid, vid)}/ingredients",
            json={"common_name": "Punarnava"},
            headers=auth_headers,
        )

        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "create_ingredient")
            .first()
        )
        assert entry is not None
        assert entry.resource == "ingredient"
        assert "content_hash" in entry.details
