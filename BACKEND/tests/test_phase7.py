"""
Tests for Phase 7: the formulation change-impact simulator.

The simulator is deterministic, so these tests are fast and offline. What they
protect:

* a comparison is a real, category-labelled diff of two stored versions;
* the "cultivated -> wild" and "solvent -> cold-press" style changes the master
  prompt calls out are actually detected;
* a change flows through to the patent signal and the biodiversity/TK status;
* the report says which categories it could not compare (public disclosure,
  classification) instead of silently omitting them;
* the run is advisory - it never edits either version - and pinned to both;
* both versions must belong to the product, and the caller must own it.
"""
import json
from unittest.mock import patch

# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _product(client, headers, name="Change Impact Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _add_ingredient(client, headers, pid, vid, **fields):
    payload = {"common_name": "Ashwagandha"}
    payload.update(fields)
    response = client.post(f"{_base(pid, vid)}/ingredients", json=payload, headers=headers)
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _put_formulation(client, headers, pid, vid, **fields):
    response = client.put(f"{_base(pid, vid)}/formulation", json=fields, headers=headers)
    assert response.status_code in (200, 201), response.json()
    return response.json()["data"]


def _add_claim(client, headers, pid, vid, text, claim_type="wellness"):
    response = client.post(
        f"{_base(pid, vid)}/claims",
        json={"claim_text": text, "claim_type": claim_type},
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _add_market(client, headers, pid, vid, country):
    response = client.post(
        f"{_base(pid, vid)}/target-markets", json={"country": country}, headers=headers
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _new_version(client, headers, pid, reason="next"):
    response = client.post(
        f"/api/products/{pid}/versions", json={"change_reason": reason}, headers=headers
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def _run(client, headers, pid, old_vid, new_vid):
    response = client.post(
        f"/api/products/{pid}/change-impact",
        json={"old_version_id": old_vid, "new_version_id": new_vid},
        headers=headers,
    )
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def _categories(data):
    return {c["category"] for c in data["results"]["changes"]}


def _find(data, category, change_type=None, field=None):
    return [
        c
        for c in data["results"]["changes"]
        if c["category"] == category
        and (change_type is None or c["change_type"] == change_type)
        and (field is None or c["field"] == field)
    ]


# -------------------------------------------------------
# Authentication / authorization
# -------------------------------------------------------

class TestChangeImpactAuthorization:
    def test_requires_authentication(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        assert (
            client.post(
                f"/api/products/{pid}/change-impact",
                json={"old_version_id": vid, "new_version_id": vid + 1},
            ).status_code
            == 401
        )
        assert client.get(f"/api/products/{pid}/change-impact").status_code == 401

    def test_another_user_cannot_compare(self, client, auth_headers, second_user_headers):
        pid, vid = _product(client, auth_headers)
        vid2 = _new_version(client, auth_headers, pid)
        response = client.post(
            f"/api/products/{pid}/change-impact",
            json={"old_version_id": vid, "new_version_id": vid2},
            headers=second_user_headers,
        )
        assert response.status_code == 404
        assert client.get(f"/api/products/{pid}/change-impact", headers=second_user_headers).status_code == 404

    def test_a_version_from_another_product_is_rejected(self, client, auth_headers):
        pid, vid = _product(client, auth_headers, name="First")
        other_pid, other_vid = _product(client, auth_headers, name="Second")

        response = client.post(
            f"/api/products/{pid}/change-impact",
            json={"old_version_id": vid, "new_version_id": other_vid},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_same_version_twice_is_rejected(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        response = client.post(
            f"/api/products/{pid}/change-impact",
            json={"old_version_id": vid, "new_version_id": vid},
            headers=auth_headers,
        )
        assert response.status_code == 422


# -------------------------------------------------------
# The changes the master prompt calls out
# -------------------------------------------------------

class TestChangeDetection:
    def test_identical_versions_report_no_differences(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        _add_claim(client, auth_headers, pid, vid, "Supports stress resilience")

        vid2 = _new_version(client, auth_headers, pid)  # copies content

        data = _run(client, auth_headers, pid, vid, vid2)
        result = data["results"]
        assert result["identical"] is True
        assert result["change_count"] == 0
        assert "No content differences" in result["summary"]
        assert result["expert_review_recommended"] is False

    def test_cultivated_to_wild_is_significant(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(
            client, auth_headers, pid, vid,
            botanical_name="Withania somnifera", source_location="Uttarakhand, India",
            source_type="cultivated",
        )
        vid2 = _new_version(client, auth_headers, pid)
        # Change the sourcing on the new version.
        ing = client.get(f"{_base(pid, vid2)}/ingredients", headers=auth_headers).json()["data"][0]
        response = client.put(
            f"{_base(pid, vid2)}/ingredients/{ing['id']}",
            json={"source_type": "wild"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()

        data = _run(client, auth_headers, pid, vid, vid2)
        changes = _find(data, "cultivation", "modified", "source_type")
        assert changes, data["results"]
        assert changes[0]["old_value"] == "cultivated"
        assert changes[0]["new_value"] == "wild"
        assert changes[0]["significance"] == "significant"
        assert data["results"]["expert_review_recommended"] is True

    def test_solvent_to_cold_press_is_detected(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _put_formulation(client, auth_headers, pid, vid, extraction_method="solvent extraction", solvent="ethanol")
        vid2 = _new_version(client, auth_headers, pid)
        _put_formulation(client, auth_headers, pid, vid2, extraction_method="cold-press", solvent="water")

        data = _run(client, auth_headers, pid, vid, vid2)
        method = _find(data, "extraction", "modified", "extraction_method")
        solvent = _find(data, "extraction", "modified", "solvent")
        assert method and method[0]["old_value"] == "solvent extraction" and method[0]["new_value"] == "cold-press"
        assert solvent and solvent[0]["new_value"] == "water"
        assert method[0]["significance"] == "significant"

    def test_claim_added_and_removed(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "General wellness support", claim_type="wellness")

        vid2 = _new_version(client, auth_headers, pid)
        # Remove the inherited claim and add a therapeutic one.
        claim = client.get(f"{_base(pid, vid2)}/claims", headers=auth_headers).json()["data"][0]
        assert client.delete(f"{_base(pid, vid2)}/claims/{claim['id']}", headers=auth_headers).status_code == 200
        _add_claim(client, auth_headers, pid, vid2, "Treats insomnia", claim_type="therapeutic")

        data = _run(client, auth_headers, pid, vid, vid2)
        added = _find(data, "claims", "added")
        removed = _find(data, "claims", "removed")
        assert any("insomnia" in (c["subject"] or "") for c in added), added
        assert removed, data["results"]
        # A new therapeutic claim is significant and demands review.
        assert any(c["significance"] == "significant" for c in added)
        assert data["results"]["expert_review_recommended"] is True

    def test_quantity_change_is_detected(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, quantity=250, quantity_unit="mg")
        vid2 = _new_version(client, auth_headers, pid)
        ing = client.get(f"{_base(pid, vid2)}/ingredients", headers=auth_headers).json()["data"][0]
        client.put(
            f"{_base(pid, vid2)}/ingredients/{ing['id']}",
            json={"quantity": 500, "quantity_unit": "mg"},
            headers=auth_headers,
        )

        data = _run(client, auth_headers, pid, vid, vid2)
        quantity = _find(data, "quantities", "modified", "quantity")
        assert quantity and "250" in quantity[0]["old_value"] and "500" in quantity[0]["new_value"]

    def test_new_target_market_is_significant(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_market(client, auth_headers, pid, vid, "India")
        vid2 = _new_version(client, auth_headers, pid)
        _add_market(client, auth_headers, pid, vid2, "Germany")

        data = _run(client, auth_headers, pid, vid, vid2)
        added = _find(data, "markets", "added")
        assert any(c["subject"] == "Germany" for c in added)
        assert added[0]["significance"] == "significant"

    def test_botanical_species_change_flows_into_patent_and_tk(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera", plant_part="root")
        vid2 = _new_version(client, auth_headers, pid)
        ing = client.get(f"{_base(pid, vid2)}/ingredients", headers=auth_headers).json()["data"][0]
        client.put(
            f"{_base(pid, vid2)}/ingredients/{ing['id']}",
            json={"botanical_name": "Curcuma longa"},
            headers=auth_headers,
        )

        data = _run(client, auth_headers, pid, vid, vid2)
        cats = _categories(data)
        assert "botanical" in cats
        # The technical (patent) signal must reflect the new species.
        assert "patent_signals" in cats
        assert any(
            "Curcuma longa" in (c["new_value"] or "") for c in _find(data, "patent_signals")
        ), data["results"]["changes"]

    def test_biodiversity_status_change_is_reported(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        vid2 = _new_version(client, auth_headers, pid)
        ing = client.get(f"{_base(pid, vid2)}/ingredients", headers=auth_headers).json()["data"][0]
        client.put(
            f"{_base(pid, vid2)}/ingredients/{ing['id']}",
            json={"source_location": "Uttarakhand, India", "source_type": "wild"},
            headers=auth_headers,
        )

        data = _run(client, auth_headers, pid, vid, vid2)
        status_changes = _find(data, "biodiversity_tk")
        assert status_changes, data["results"]
        assert any(c["field"] == "biodiversity/ABS status" for c in status_changes)


# -------------------------------------------------------
# Honest gaps, ranking and questions
# -------------------------------------------------------

class TestReportShape:
    def test_classification_is_explicitly_not_compared_when_absent(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Wellness claim")
        vid2 = _new_version(client, auth_headers, pid)

        result = _run(client, auth_headers, pid, vid, vid2)["results"]
        not_compared = {n["category"] for n in result["not_compared"]}
        # Classification has no recorded analysis, so it stays not_compared.
        assert "classification" in not_compared
        # Disclosure history IS comparable since Phase 8a: no events on either
        # version means no public_disclosure change and no not_compared entry.
        assert "public_disclosure" not in not_compared
        assert any("not_compared" in w for w in result["warnings"])

    def test_new_disclosure_event_is_significant(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        vid2 = _new_version(client, auth_headers, pid)
        client.post(
            f"/api/products/{pid}/versions/{vid2}/disclosures",
            json={
                "disclosure_type": "conference_presentation",
                "description": "Presented the method at a conference",
            },
            headers=auth_headers,
        )
        result = _run(client, auth_headers, pid, vid, vid2)["results"]
        pub = [c for c in result["changes"] if c["category"] == "public_disclosure"]
        assert pub, result["changes"]
        assert pub[0]["significance"] == "significant"
        assert any(
            "disclosure" in r.lower() for r in result["expert_review_reasons"]
        )

    def test_report_is_ranked_and_carries_review_questions(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera", source_type="cultivated")
        vid2 = _new_version(client, auth_headers, pid)
        _add_claim(client, auth_headers, pid, vid2, "Treats insomnia", claim_type="therapeutic")

        result = _run(client, auth_headers, pid, vid, vid2)["results"]
        order = {"significant": 0, "review_recommended": 1, "informational": 2}
        ranks = [order[c["significance"]] for c in result["changes"]]
        assert ranks == sorted(ranks), result["changes"]

        assert result["significant_changes"]
        assert result["categories_changed"]
        categories = {q["category"] for q in result["review_questions"]}
        assert "claims" in categories
        assert "public_disclosure" in categories  # always surfaced
        assert all(q["question"] for q in result["review_questions"])
        assert result["provenance"] == "AI_ANALYSIS"

    def test_disclaimers_are_attached(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "A claim")
        vid2 = _new_version(client, auth_headers, pid)

        data = _run(client, auth_headers, pid, vid, vid2)
        assert any("not advice" in w for w in data["warnings"])
        assert any("legal" in w for w in data["warnings"])

    def test_classification_compared_when_both_versions_have_one(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "A claim")
        vid2 = _new_version(client, auth_headers, pid)

        # Record a comprehensive analysis on each version, with different categories.
        def _record(version_id, category):
            payload = json.dumps(
                {
                    "preliminary_category": category,
                    "confidence": "low",
                    "rationale": "Test fixture.",
                    "alternative_categories": [],
                    "missing_information": [],
                }
            )
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]), patch(
                "app.analysis.claim_analyzer.get_llm_provider", return_value=_mock_llm(_claim_payload())
            ), patch("app.analysis.classifier.get_llm_provider", return_value=_mock_llm(payload)):
                response = client.post(
                    f"/api/products/{pid}/versions/{version_id}/analyze", headers=auth_headers
                )
            assert response.status_code == 200, response.json()

        _record(vid, "proprietary_ayurvedic")
        _record(vid2, "possible_medicinal")

        result = _run(client, auth_headers, pid, vid, vid2)["results"]
        classification = [c for c in result["changes"] if c["category"] == "classification"]
        assert classification, result
        assert classification[0]["old_value"] == "proprietary_ayurvedic"
        assert classification[0]["new_value"] == "possible_medicinal"
        assert classification[0]["significance"] == "significant"


def _mock_llm(payload):
    from unittest.mock import MagicMock

    llm = MagicMock()
    llm.generate.return_value = payload
    return llm


def _claim_payload():
    return json.dumps({"assessments": [], "summary": "No claims reviewed.", "warnings": []})


# -------------------------------------------------------
# Advisory + persistence
# -------------------------------------------------------

class TestPersistence:
    def test_comparison_is_advisory_and_records_hashes(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        vid2 = _new_version(client, auth_headers, pid)
        client.post(
            f"{_base(pid, vid2)}/claims",
            json={"claim_text": "New claim", "claim_type": "wellness"},
            headers=auth_headers,
        )

        before = client.get(f"{_base(pid, vid)}", headers=auth_headers).json()["data"]

        data = _run(client, auth_headers, pid, vid, vid2)
        result = data["results"]
        assert result["old_version_id"] == vid
        assert result["new_version_id"] == vid2
        assert result["old_content_hash"] and result["new_content_hash"]
        assert result["old_content_hash"] != result["new_content_hash"]

        # Neither version was modified.
        after = client.get(f"{_base(pid, vid)}", headers=auth_headers).json()["data"]
        assert after["content_hash"] == before["content_hash"]
        assert len(after["ingredients"]) == len(before["ingredients"])

    def test_runs_are_listed_and_fetchable(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        vid2 = _new_version(client, auth_headers, pid)
        created = _run(client, auth_headers, pid, vid, vid2)

        listed = client.get(f"/api/products/{pid}/change-impact", headers=auth_headers).json()
        assert listed["success"] is True
        assert len(listed["data"]) == 1
        assert listed["data"][0]["id"] == created["id"]

        detail = client.get(
            f"/api/products/{pid}/change-impact/{created['id']}", headers=auth_headers
        )
        assert detail.status_code == 200, detail.json()
        assert detail.json()["data"]["results"]["kind"] == "change_impact"

        assert (
            client.get(
                f"/api/products/{pid}/change-impact/424242", headers=auth_headers
            ).status_code
            == 404
        )

    def test_each_run_is_a_new_row(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        vid2 = _new_version(client, auth_headers, pid)
        first = _run(client, auth_headers, pid, vid, vid2)
        second = _run(client, auth_headers, pid, vid, vid2)
        assert first["id"] != second["id"]

        listed = client.get(f"/api/products/{pid}/change-impact", headers=auth_headers).json()["data"]
        assert len(listed) == 2

    def test_run_is_pinned_to_both_versions(self, client, auth_headers):
        pid, vid = _product(client, auth_headers)
        vid2 = _new_version(client, auth_headers, pid)
        created = _run(client, auth_headers, pid, vid, vid2)

        # A third version must not change the recorded run.
        _new_version(client, auth_headers, pid, reason="third")
        detail = client.get(
            f"/api/products/{pid}/change-impact/{created['id']}", headers=auth_headers
        ).json()["data"]
        assert detail["results"]["new_version_id"] == vid2
