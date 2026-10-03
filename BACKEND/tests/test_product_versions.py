"""
Tests for product versioning, version isolation, content hashes and
authorization boundaries between users.
"""
import re

import pytest

from app.models import Ingredient, ProductVersion, SourceType
from app.services.version_snapshot import refresh_version_snapshot

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _create_product(client, headers, name="Versioned Product"):
    """Helper: create a product and return (product_id, version_id)."""
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


class TestVersionIntegrityFields:
    """snapshot_data / content_hash must hold real values, not placeholders."""

    def test_initial_version_has_content_hash(self, client, auth_headers):
        product_id, _ = _create_product(client, auth_headers)

        response = client.get(f"/api/products/{product_id}/versions", headers=auth_headers)
        assert response.status_code == 200
        version = response.json()["data"][0]

        assert version["content_hash"] is not None
        assert HEX64.match(version["content_hash"])
        assert version["snapshot_data"] is not None

    def test_snapshot_reflects_content(self, client, auth_headers, db_session):
        product_id, version_id = _create_product(client, auth_headers)

        db_session.add(
            Ingredient(
                product_version_id=version_id,
                common_name="Ashwagandha",
                botanical_name="Withania somnifera",
                plant_part="root",
            )
        )
        db_session.commit()

        response = client.get(
            f"/api/products/{product_id}/versions/{version_id}", headers=auth_headers
        )
        detail = response.json()["data"]
        assert len(detail["ingredients"]) == 1

        # Recompute after a direct DB write so the hash matches the content.
        version = db_session.query(ProductVersion).filter_by(id=version_id).first()
        refresh_version_snapshot(db_session, version)

        db_session.refresh(version)
        assert version.content_hash is not None
        assert "Ashwagandha" in version.snapshot_data

    def test_hash_is_stable_for_identical_content(self, client, auth_headers, db_session):
        product_id, version_id = _create_product(client, auth_headers)

        v1 = db_session.query(ProductVersion).filter_by(id=version_id).first()
        refresh_version_snapshot(db_session, v1)
        db_session.refresh(v1)
        first_hash = v1.content_hash

        # Creating an inheriting version does not change v1's snapshot.
        client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "no content change"},
            headers=auth_headers,
        )

        db_session.refresh(v1)
        assert v1.content_hash == first_hash


class TestVersionCreation:
    """Version numbering and content inheritance."""

    def test_new_version_hashes_match_when_content_matches(
        self, client, auth_headers, db_session
    ):
        product_id, version_id = _create_product(client, auth_headers)

        v1 = db_session.query(ProductVersion).filter_by(id=version_id).first()
        refresh_version_snapshot(db_session, v1)
        db_session.refresh(v1)

        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "inherit content"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        v2 = response.json()["data"]
        assert v2["version_number"] == 2
        # Same content -> same content hash, even though the version differs.
        assert v2["content_hash"] == v1.content_hash

    def test_new_version_copies_ingredients(self, client, auth_headers, db_session):
        product_id, version_id = _create_product(client, auth_headers)

        source = Ingredient(
            product_version_id=version_id,
            common_name="Ashwagandha",
            botanical_name="Withania somnifera",
            source_type=SourceType.CULTIVATED,
        )
        db_session.add(source)
        db_session.commit()
        source_id = source.id

        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "copy forward"},
            headers=auth_headers,
        )
        v2_id = response.json()["data"]["id"]

        copied = db_session.query(Ingredient).filter_by(product_version_id=v2_id).all()
        assert len(copied) == 1
        assert copied[0].common_name == "Ashwagandha"
        assert copied[0].id != source_id

    def test_start_empty_creates_blank_version(self, client, auth_headers, db_session):
        product_id, version_id = _create_product(client, auth_headers)

        db_session.add(
            Ingredient(product_version_id=version_id, common_name="Turmeric")
        )
        db_session.commit()

        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "blank", "start_empty": True},
            headers=auth_headers,
        )
        v2_id = response.json()["data"]["id"]

        assert db_session.query(Ingredient).filter_by(product_version_id=v2_id).count() == 0

    def test_create_version_for_missing_product(self, client, auth_headers):
        response = client.post(
            "/api/products/99999/versions",
            json={"change_reason": "nope"},
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestVersionIsolation:
    """Editing one version must not touch another."""

    def test_editing_v2_does_not_change_v1_ingredients(
        self, client, auth_headers, db_session
    ):
        product_id, version_id = _create_product(client, auth_headers)

        db_session.add(
            Ingredient(
                product_version_id=version_id,
                common_name="Ashwagandha",
                source_type=SourceType.CULTIVATED,
            )
        )
        db_session.commit()

        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "switch to wild-sourced"},
            headers=auth_headers,
        )
        v2_id = response.json()["data"]["id"]

        # Simulate the Phase 3 edit "cultivated -> wild" on version 2 only.
        v2_ingredient = (
            db_session.query(Ingredient).filter_by(product_version_id=v2_id).first()
        )
        v2_ingredient.source_type = SourceType.WILD
        db_session.commit()

        v1_ingredient = (
            db_session.query(Ingredient).filter_by(product_version_id=version_id).first()
        )
        db_session.refresh(v1_ingredient)
        assert v1_ingredient.source_type == SourceType.CULTIVATED

    def test_versions_of_one_product_are_scoped(self, client, auth_headers):
        product_a, _ = _create_product(client, auth_headers, name="Product A")
        product_b, _ = _create_product(client, auth_headers, name="Product B")

        versions_b = client.get(
            f"/api/products/{product_b}/versions", headers=auth_headers
        ).json()["data"]
        version_b_id = versions_b[0]["id"]

        # Version B is not reachable through product A.
        response = client.get(
            f"/api/products/{product_a}/versions/{version_b_id}", headers=auth_headers
        )
        assert response.status_code == 404


class TestVersionMetadataUpdate:
    """PUT /versions/{id} updates metadata only."""

    def test_update_change_reason(self, client, auth_headers):
        product_id, version_id = _create_product(client, auth_headers)

        response = client.put(
            f"/api/products/{product_id}/versions/{version_id}",
            json={"change_reason": "corrected reason"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["data"]["change_reason"] == "corrected reason"

        detail = client.get(
            f"/api/products/{product_id}/versions/{version_id}", headers=auth_headers
        ).json()["data"]
        assert detail["change_reason"] == "corrected reason"

    def test_update_version_of_wrong_product(self, client, auth_headers):
        product_a, _ = _create_product(client, auth_headers, name="Product A")
        product_b, version_b = _create_product(client, auth_headers, name="Product B")

        response = client.put(
            f"/api/products/{product_a}/versions/{version_b}",
            json={"change_reason": "wrong parent"},
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestVersionClone:
    """POST /versions/{id}/clone creates an independent copy."""

    def test_clone_copies_content_and_preserves_hash(
        self, client, auth_headers, db_session
    ):
        product_id, version_id = _create_product(client, auth_headers)

        db_session.add(
            Ingredient(
                product_version_id=version_id,
                common_name="Ashwagandha",
                botanical_name="Withania somnifera",
                plant_part="root",
                source_type=SourceType.CULTIVATED,
            )
        )
        db_session.commit()

        v1 = db_session.query(ProductVersion).filter_by(id=version_id).first()
        refresh_version_snapshot(db_session, v1)
        db_session.refresh(v1)

        response = client.post(
            f"/api/products/{product_id}/versions/{version_id}/clone",
            json={"change_reason": "branch for wild sourcing"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        clone = response.json()["data"]
        assert clone["version_number"] == 2
        assert clone["content_hash"] == v1.content_hash

        cloned_ingredients = (
            db_session.query(Ingredient)
            .filter_by(product_version_id=clone["id"])
            .all()
        )
        assert len(cloned_ingredients) == 1
        assert cloned_ingredients[0].common_name == "Ashwagandha"


class TestOwnershipBoundaries:
    """A user must never reach another user's products."""

    def _product_for_first_user(self, client, auth_headers):
        return _create_product(client, auth_headers, name="Owned by user one")

    def test_product_not_listed_for_other_user(
        self, client, auth_headers, second_user_headers
    ):
        self._product_for_first_user(client, auth_headers)

        response = client.get("/api/products", headers=second_user_headers)
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_other_user_cannot_read_product(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.get(f"/api/products/{product_id}", headers=second_user_headers)
        assert response.status_code == 404

    def test_other_user_cannot_read_passport(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.get(
            f"/api/products/{product_id}/passport", headers=second_user_headers
        )
        assert response.status_code == 404

    def test_other_user_cannot_update_product(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.put(
            f"/api/products/{product_id}",
            json={"name": "Hijacked"},
            headers=second_user_headers,
        )
        assert response.status_code == 404

        # Original owner still sees the untouched name.
        owner_view = client.get(f"/api/products/{product_id}", headers=auth_headers)
        assert owner_view.json()["data"]["name"] == "Owned by user one"

    def test_other_user_cannot_delete_product(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.delete(
            f"/api/products/{product_id}", headers=second_user_headers
        )
        assert response.status_code == 404

        assert client.get(f"/api/products/{product_id}", headers=auth_headers).status_code == 200

    def test_other_user_cannot_list_versions(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.get(
            f"/api/products/{product_id}/versions", headers=second_user_headers
        )
        assert response.status_code == 404

    def test_other_user_cannot_read_version(
        self, client, auth_headers, second_user_headers
    ):
        product_id, version_id = self._product_for_first_user(client, auth_headers)

        response = client.get(
            f"/api/products/{product_id}/versions/{version_id}",
            headers=second_user_headers,
        )
        assert response.status_code == 404

    def test_other_user_cannot_create_version(
        self, client, auth_headers, second_user_headers
    ):
        product_id, _ = self._product_for_first_user(client, auth_headers)

        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "trespass"},
            headers=second_user_headers,
        )
        assert response.status_code == 404


class TestPassportEndpoint:
    """Passport metadata update."""

    def test_put_passport_updates_metadata(self, client, auth_headers):
        product_id, _ = _create_product(client, auth_headers, name="Passport Product")

        response = client.put(
            f"/api/products/{product_id}/passport",
            json={"description": "Updated from the passport screen"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert (
            response.json()["data"]["description"] == "Updated from the passport screen"
        )

    def test_passport_exposes_version_hash(self, client, auth_headers):
        product_id, _ = _create_product(client, auth_headers)

        passport = client.get(
            f"/api/products/{product_id}/passport", headers=auth_headers
        ).json()["data"]

        assert passport["version_count"] == 1
        assert HEX64.match(passport["current_version"]["content_hash"])
