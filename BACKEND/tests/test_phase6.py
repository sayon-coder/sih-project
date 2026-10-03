"""
Tests for Phase 6: IP route map, patent screening and biodiversity/ABS/TK
screening.

The screening logic is deterministic and offline, so these tests are fast. What
they protect:

* the route map is cautious - every route carries one of the allowed careful
  labels and is never presented as legally applicable;
* patent screening always labels its output as a demonstration corpus, never a
  live search, and never invents a real patent number;
* the feature comparison is a field-by-field match with matching / different /
  unknown verdicts and a similarity indicator;
* screening is advisory - it never mutates the underlying content;
* screens are version-scoped and owner-scoped;
* restricted traditional-knowledge sources (TKDL) are always marked restricted
  and never searched or reproduced.
"""
import json
from contextlib import contextmanager
from unittest.mock import patch

from app.analysis.ip_routes import (
    LABEL_FURTHER_REVIEW,
    LABEL_INSUFFICIENT,
    LABEL_NOT_INDICATED,
    LABEL_POTENTIALLY_RELEVANT,
)
from app.data.traditional_knowledge_sources import RESTRICTED_AVAILABILITY

ALLOWED_LABELS = {
    LABEL_POTENTIALLY_RELEVANT,
    LABEL_FURTHER_REVIEW,
    LABEL_NOT_INDICATED,
    LABEL_INSUFFICIENT,
}


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _product_and_version(client, headers, name="Phase 6 Product"):
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


def _add_claim(client, headers, pid, vid, text, claim_type="wellness"):
    response = client.post(
        f"{_base(pid, vid)}/claims",
        json={"claim_text": text, "claim_type": claim_type},
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _put_formulation(client, headers, pid, vid, **fields):
    response = client.put(f"{_base(pid, vid)}/formulation", json=fields, headers=headers)
    assert response.status_code in (200, 201), response.json()
    return response.json()["data"]


def _add_market(client, headers, pid, vid, country):
    response = client.post(
        f"{_base(pid, vid)}/target-markets", json={"country": country}, headers=headers
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _chunk(chunk_id=1, source_type="scientific_paper"):
    from app.rag.schemas import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=7,
        title="Withania somnifera monograph",
        source_type=source_type,
        jurisdiction="IN",
        text="Withania somnifera root has a documented traditional use as a restorative.",
        final_score=0.9,
    )


@contextmanager
def _patch_screening_retrieval(chunks):
    """Patch the retrieval used by the screening analyzers (avoids model load)."""
    with patch("app.analysis.screening.hybrid_retrieve", return_value=chunks):
        yield


# -------------------------------------------------------
# Authentication / authorization
# -------------------------------------------------------

class TestPhase6Authorization:
    def test_requires_authentication(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        assert client.get(f"{_base(pid, vid)}/ip-routes").status_code == 401
        assert client.post(f"{_base(pid, vid)}/patents/search").status_code == 401
        assert client.get(f"{_base(pid, vid)}/patents").status_code == 401
        assert client.post(f"{_base(pid, vid)}/biodiversity/screen").status_code == 401
        assert client.post(f"{_base(pid, vid)}/traditional-knowledge/screen").status_code == 401
        assert client.get("/api/traditional-knowledge/sources").status_code == 401

    def test_another_user_cannot_reach_the_version(self, client, auth_headers, second_user_headers):
        pid, vid = _product_and_version(client, auth_headers)
        assert client.get(f"{_base(pid, vid)}/ip-routes", headers=second_user_headers).status_code == 404
        assert (
            client.post(f"{_base(pid, vid)}/patents/search", headers=second_user_headers).status_code
            == 404
        )
        assert (
            client.post(f"{_base(pid, vid)}/biodiversity/screen", headers=second_user_headers).status_code
            == 404
        )

    def test_patent_record_is_scoped_to_owner(self, client, auth_headers, second_user_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        response = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        record_id = response.json()["data"]["results"]["records"][0]["id"]

        assert client.get(f"/api/patents/{record_id}", headers=auth_headers).status_code == 200
        assert client.get(f"/api/patents/{record_id}", headers=second_user_headers).status_code == 404

    def test_screening_is_not_visible_from_another_version(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")

        with _patch_screening_retrieval([]):
            response = client.post(f"{_base(pid, vid)}/biodiversity/screen", headers=auth_headers)
        analysis_id = response.json()["data"]["id"]

        second = client.post(f"/api/products/{pid}/versions", json={}, headers=auth_headers)
        vid2 = second.json()["data"]["id"]
        assert (
            client.get(f"{_base(pid, vid2)}/analyses/{analysis_id}", headers=auth_headers).status_code
            == 404
        )


# -------------------------------------------------------
# IP route map
# -------------------------------------------------------

class TestIPRouteMap:
    def test_route_map_is_cautious_and_complete(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Ashwagandha Cold Press")
        _add_ingredient(
            client,
            auth_headers,
            pid,
            vid,
            botanical_name="Withania somnifera",
            plant_part="root",
            source_location="Uttarakhand, India",
            source_type="cultivated",
        )
        _put_formulation(client, auth_headers, pid, vid, extraction_method="cold-press", solvent="water")
        _add_claim(client, auth_headers, pid, vid, "Supports stress resilience", claim_type="wellness")
        _add_market(client, auth_headers, pid, vid, "India")

        response = client.get(f"{_base(pid, vid)}/ip-routes", headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]

        assert data["kind"] == "ip_route_map"
        assert data["preliminary"] is True
        assert len(data["routes"]) == 9  # all routes considered

        routes = {route["route"]: route for route in data["routes"]}
        assert set(routes) == {
            "patent",
            "trademark",
            "copyright",
            "design",
            "gi",
            "trade_secret",
            "plant_variety",
            "traditional_knowledge",
            "biodiversity_abs",
        }

        # Every label must be one of the careful allowed values.
        for route in data["routes"]:
            assert route["label"] in ALLOWED_LABELS, route
            assert route["provenance"] == "AI_ANALYSIS"
            assert route["rationale"]
            # Spec item 5: every route carries the five explicit fields and a
            # machine status consistent with its display label.
            assert route["status"] in {
                "POTENTIALLY_RELEVANT",
                "REVIEW_RECOMMENDED",
                "ADDITIONAL_INFORMATION_NEEDED",
                "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
            }, route
            assert route["why_flagged"], route
            assert route["next_action"], route
            assert route["limitation"], route
            assert isinstance(route["missing_information"], list), route

        # A recorded process + botanical material points at the patent route,
        # evidence-based (spec: "A technical extraction process was recorded.").
        assert routes["patent"]["label"] == LABEL_POTENTIALLY_RELEVANT
        assert routes["patent"]["status"] == "POTENTIALLY_RELEVANT"
        assert routes["patent"]["why_flagged"] == "A technical extraction process was recorded."
        assert routes["patent"]["missing_information"] == []
        assert routes["patent"]["signals"]

        # A brand name is present, so the trademark route is flagged.
        assert routes["trademark"]["label"] == LABEL_POTENTIALLY_RELEVANT

        # Disclaimer must be attached.
        assert any("not legally" in w.lower() or "never legally" in w.lower() for w in data["warnings"])

    def test_thin_version_yields_insufficient_not_legally_applicable(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Empty Product")
        response = client.get(f"{_base(pid, vid)}/ip-routes", headers=auth_headers)
        data = response.json()["data"]

        routes = {route["route"]: route for route in data["routes"]}
        # No ingredients and no process: the patent route cannot be assessed.
        assert routes["patent"]["label"] == LABEL_INSUFFICIENT
        assert data["missing_information"]


# -------------------------------------------------------
# Patent screening
# -------------------------------------------------------

class TestPatentScreening:
    def _seed_demo_version(self, client, headers):
        pid, vid = _product_and_version(client, headers, name="Cold Press Ashwagandha")
        _add_ingredient(
            client,
            headers,
            pid,
            vid,
            botanical_name="Withania somnifera",
            plant_part="root",
        )
        _put_formulation(
            client,
            headers,
            pid,
            vid,
            extraction_method="cold-press",
            solvent="none",
            temperature=4,
            temperature_unit="C",
        )
        _add_claim(client, headers, pid, vid, "Improved bioavailability", claim_type="wellness")
        return pid, vid

    def test_search_identifies_records_and_labels_demo_corpus(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers)

        response = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert response.status_code == 200, response.json()
        analysis = response.json()["data"]
        result = analysis["results"]

        assert analysis["analysis_type"] == "patent_screening"
        assert analysis["status"] == "completed"
        assert result["kind"] == "patent_screening"
        assert result["retrieval_mode"] == "DEMO_CORPUS"
        assert result["search_is_live"] is False
        assert result["record_count"] >= 1

        # The cold-press record should overlap most strongly.
        top = result["records"][0]
        assert top["record_id"] == "DEMO-PAT-0001"
        assert top["is_demo"] is True
        assert top["record_source"] == "DEMO_CORPUS"
        # Never a real patent number.
        assert top["patent_number"] is None
        assert top["relevance_label"] in {
            "Possible Technical Overlap",
            "Potentially Relevant",
            "Further Review Recommended",
        }
        assert top["similarity_band"] in {"low", "medium", "high"}

        # The comparison must include matching and unknown verdicts.
        verdicts = {feature["verdict"] for feature in top["features"]}
        assert "match" in verdicts
        assert "unknown" in verdicts

        # Demo data must be declared, and patentability never asserted.
        assert any("demonstration" in w.lower() for w in result["warnings"])
        assert any("not determinations of patentability" in w for w in result["warnings"])
        assert result["technical_features"]

    def test_search_without_overlap_reports_none(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Mineral Product")
        _add_ingredient(client, auth_headers, pid, vid, common_name="Calcium carbonate")

        response = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        result = response.json()["data"]["results"]
        assert result["record_count"] == 0
        assert result["records"] == []
        assert any("No record" in w for w in result["warnings"])

    def test_list_and_fetch_records(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers)
        client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)

        listed = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()["data"]
        assert len(listed) >= 1

        record_id = listed[0]["id"]
        detail = client.get(f"/api/patents/{record_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.json()
        assert detail.json()["data"]["record_id"] == listed[0]["record_id"]
        assert client.get("/api/patents/999999", headers=auth_headers).status_code == 404

    def test_compare_re_compares_without_creating_records(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers)
        client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        before = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()["data"]

        response = client.post(
            f"{_base(pid, vid)}/patents/compare",
            json={"patent_record_ids": [before[0]["id"]]},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()
        analysis = response.json()["data"]
        assert analysis["results"]["kind"] == "patent_feature_comparison"
        assert analysis["results"]["record_count"] == 1

        after = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()["data"]
        assert len(after) == len(before)  # compare created no records

    def test_compare_without_records_is_honest(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        response = client.post(f"{_base(pid, vid)}/patents/compare", headers=auth_headers)
        assert response.status_code == 200, response.json()
        result = response.json()["data"]["results"]
        assert result["record_count"] == 0
        assert any("nothing to compare" in w.lower() for w in result["warnings"])

    def test_screening_is_advisory(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers)
        client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)

        ingredients = client.get(f"{_base(pid, vid)}/ingredients", headers=auth_headers).json()["data"]
        assert ingredients[0]["botanical_name"] == "Withania somnifera"
        assert ingredients[0]["provenance"] == "USER_PROVIDED"


# -------------------------------------------------------
# Biodiversity / ABS screening
# -------------------------------------------------------

class TestBiodiversityScreening:
    def _run(self, client, headers, pid, vid, include_sources=False):
        url = f"{_base(pid, vid)}/biodiversity/screen"
        if include_sources:
            url += "?include_sources=true"
        with _patch_screening_retrieval([]):
            response = client.post(url, headers=headers)
        assert response.status_code == 200, response.json()
        return response.json()["data"]

    def test_no_information_needs_more(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        analysis = self._run(client, auth_headers, pid, vid)
        assert analysis["analysis_type"] == "biodiversity_screening"
        result = analysis["results"]
        assert result["status"] == "ADDITIONAL_INFORMATION_NEEDED"
        assert result["status_label"] == "Additional information needed"
        assert result["missing_information"]
        assert any("not an official determination" in w for w in result["warnings"])

    def test_botanical_with_origin_is_potentially_relevant(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(
            client,
            auth_headers,
            pid,
            vid,
            botanical_name="Withania somnifera",
            source_location="Uttarakhand, India",
            source_type="cultivated",
        )
        result = self._run(client, auth_headers, pid, vid)["results"]
        assert result["status"] == "POTENTIALLY_RELEVANT"
        assert result["collected"]["biological_resource_present"] is True
        assert "Withania somnifera" in result["collected"]["botanical_species"]

    def test_wild_source_recommends_review(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(
            client,
            auth_headers,
            pid,
            vid,
            botanical_name="Withania somnifera",
            source_location="Uttarakhand, India",
            source_type="wild",
        )
        result = self._run(client, auth_headers, pid, vid)["results"]
        assert result["status"] == "REVIEW_RECOMMENDED"

    def test_non_biological_resource_has_no_immediate_consideration(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, common_name="Calcium carbonate")
        result = self._run(client, auth_headers, pid, vid)["results"]
        assert result["status"] == "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"

    def test_registry_marks_restricted_sources_unavailable(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        result = self._run(client, auth_headers, pid, vid)["results"]

        restricted = [s for s in result["sources"] if s["availability"] == RESTRICTED_AVAILABILITY]
        assert restricted, "the TKDL must be surfaced as restricted"
        assert any("TKDL" in s["title"] for s in restricted)
        # Never reproduced: a restricted source carries no passage.
        assert all("chunk_id" not in s or s["chunk_id"] is None for s in restricted)

    def test_retrieval_failure_degrades_with_a_warning(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")

        with patch(
            "app.analysis.screening.hybrid_retrieve",
            side_effect=RuntimeError("embedding model unavailable"),
        ):
            response = client.post(
                f"{_base(pid, vid)}/biodiversity/screen?include_sources=true",
                headers=auth_headers,
            )

        assert response.status_code == 200, response.json()
        result = response.json()["data"]["results"]
        assert any("could not be searched" in w for w in result["warnings"])
        assert result["collected"]["corpus_sources_requested"] is True


# -------------------------------------------------------
# Traditional knowledge screening
# -------------------------------------------------------

class TestTraditionalKnowledgeScreening:
    def _run(self, client, headers, pid, vid, chunks=None, include_sources=False):
        url = f"{_base(pid, vid)}/traditional-knowledge/screen"
        if include_sources:
            url += "?include_sources=true"
        with _patch_screening_retrieval(chunks or []):
            response = client.post(url, headers=headers)
        assert response.status_code == 200, response.json()
        return response.json()["data"]

    def test_traditional_claim_recommends_review(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(
            client, auth_headers, pid, vid, botanical_name="Withania somnifera", sanskrit_name="Ashwagandha"
        )
        _add_claim(client, auth_headers, pid, vid, "Traditional use as a restorative", claim_type="traditional_use")

        analysis = self._run(client, auth_headers, pid, vid)
        assert analysis["analysis_type"] == "tk_screening"
        result = analysis["results"]
        assert result["kind"] == "tk_screening"
        assert result["status"] == "REVIEW_RECOMMENDED"
        assert result["collected"]["tk_involvement"] is True

    def test_public_passage_supports_potentially_relevant(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera", sanskrit_name="Ashwagandha")

        result = self._run(
            client, auth_headers, pid, vid, chunks=[_chunk()], include_sources=True
        )["results"]
        assert result["status"] == "POTENTIALLY_RELEVANT"
        assert result["collected"]["publicly_documented_traditional_use"] is True
        corpus = [s for s in result["sources"] if s.get("chunk_id") == 1]
        assert corpus and corpus[0]["availability"] == "available"

    def test_no_signals_has_no_immediate_consideration(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "A general wellness statement")
        result = self._run(client, auth_headers, pid, vid)["results"]
        assert result["status"] == "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"

    def test_restricted_note_is_present(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        result = self._run(client, auth_headers, pid, vid)["results"]
        assert any("TKDL" in w for w in result["warnings"])
        assert result["collected"]["restricted_sources_excluded"] == ["TKDL"]

    def test_sources_registry_separates_public_permitted_restricted(self, client, auth_headers):
        response = client.get("/api/traditional-knowledge/sources", headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]

        kinds = {entry["kind"] for entry in data["sources"]}
        assert {"public", "permitted", "restricted"} <= kinds
        restricted = [s for s in data["sources"] if s["kind"] == "restricted"]
        assert restricted and all(s["availability"] == RESTRICTED_AVAILABILITY for s in restricted)
        assert "not accessible" in data["restricted_note"].lower()


# -------------------------------------------------------
# Persistence
# -------------------------------------------------------

class TestScreeningPersistence:
    def test_analyses_are_recorded_and_filterable(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")

        client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        with _patch_screening_retrieval([]):
            client.post(f"{_base(pid, vid)}/biodiversity/screen", headers=auth_headers)
            client.post(f"{_base(pid, vid)}/traditional-knowledge/screen", headers=auth_headers)

        listed = client.get(f"{_base(pid, vid)}/analyses", headers=auth_headers).json()["data"]
        types = {a["analysis_type"] for a in listed}
        assert {"patent_screening", "biodiversity_screening", "tk_screening"} <= types

        filtered = client.get(
            f"{_base(pid, vid)}/analyses?analysis_type=patent_screening", headers=auth_headers
        ).json()["data"]
        assert filtered and all(a["analysis_type"] == "patent_screening" for a in filtered)

    def test_every_run_is_pinned_to_the_reviewed_version(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_ingredient(client, auth_headers, pid, vid, botanical_name="Withania somnifera")
        client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)

        listed = client.get(f"{_base(pid, vid)}/analyses", headers=auth_headers).json()["data"]
        assert all(a["product_version_id"] == vid for a in listed)
