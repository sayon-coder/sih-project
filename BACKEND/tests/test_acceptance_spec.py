"""
Acceptance tests for the Product Passport analysis spec (reported bugs 1-12).

The user's acceptance scenario, run end to end against the real API with only
the model layer mocked (the suite is offline):

  1. Create the product "AshwaBio-X" (version V1).
  2. Ingredient: Ashwagandha - 100 g of root, cultivated, source location
     "Uttarakhand, India", prepared as powder.
  3. Formulation: cold-press extraction at 4 C - and nothing else.
  4. Claims: a 40 % claim and a wellness claim.
  5. Target market: India.
  6. Full analysis; assert bugs 1, 3, 4, 5, 6, 7, 8, 9 and 11 on the run.
  7. Seed V2 from V1 with the four spec changes: cultivated -> wild,
     wellness claim -> "Treats insomnia", powder -> capsule, add Germany.
  8. Change-impact comparison V1 -> V2 (bug 10), then a fresh analysis of V2.

Bugs 2 (both target countries returned, no derived market) and 12 (report
content) get their own focused tests. Every asserted value comes from a
recorded row or a deterministic builder - nothing is invented.
"""
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.analysis.ip_schemas import (
    DEMO_RECORD_LABEL,
    SOURCE_TYPE_VOCAB,
    STATUS_TO_LABEL,
    VERIFICATION_SYNTHETIC,
)
from app.data.traditional_knowledge_sources import TKDL_RESTRICTED_LABEL
from app.models.disclosure_models import PUBLIC_DISCLOSURE_DISCLAIMER
from app.services.report_service import _comp_details, _formulation_lines


# -------------------------------------------------------
# Exact strings from the spec
# -------------------------------------------------------

SPEC_DISCLAIMER = (
    "Public-disclosure review is recommended before presenting or publishing "
    "the technical method. Consult a registered patent professional about "
    "appropriate filing strategy. A timestamped app record does not create "
    "patent priority or guarantee legal protection."
)
EXPECTED_REASON = (
    "The claim was entered by the user and no independently verified "
    "supporting evidence was retrieved."
)
PARAMETERS_NOTE = (
    "Solvent, pressure, duration, concentration and standardisation are not "
    "yet provided."
)
FIVE_MISSING = [
    "intended use",
    "dosage form",
    "complete ingredient list",
    "exact label claims",
    "manufacturing/licensing details",
]
POSSIBLE_CATEGORIES = [
    "proprietary_ayurvedic_product",
    "nutraceutical_or_ayurveda_aahara",
    "possible_medicinal_product",
]
ABS_ITEMS = [
    "Applicant category",
    "Exact source arrangement",
    "Activity",
    "Cultivation documentation",
    "Associated knowledge",
    "Possible exemptions",
]
BIODIVERSITY_WHY = (
    "An Indian biological resource was recorded with a stated source location."
)
BIODIVERSITY_LIMIT = (
    "This is not an official determination of approval or legal obligation."
)
CLAIM_WHY = (
    "The claim result(s) are user-provided and no independent evidence was "
    "attached."
)

PATENT_WHY = "A technical extraction process was recorded."
PATENT_NEXT = (
    "Compare the technical features with verified public patent records."
)
PATENT_LIMIT = "This is not a patentability conclusion."
TRADEMARK_MISSING = [
    "Confirmation that the name is intended for use as a brand in each target market"
]

EXPECTED_AFFECTED_AREAS = [
    "Biodiversity/source-documentation review",
    "Traditional-knowledge review",
    "Claim-risk review",
    "Product-category review",
    "Evidence requirements",
    "International/Germany review",
    "Expert review",
]
EXPECTED_REASSESSMENTS = [
    "Biodiversity/ABS screening",
    "Traditional-knowledge screening",
    "Claim analysis",
    "Patent screening",
    "Target-market regulatory review",
]
APPROVAL_BANNED = (
    "approval is required",
    "requires approval",
    "must be approved",
    "must obtain approval",
    "automatically approved",
)
DISCLOSURE_BANNED = (
    "deadline",
    "months",
    "grace period",
    "must file",
    "file within",
)


# -------------------------------------------------------
# Helpers (same conventions as the other suites)
# -------------------------------------------------------

def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _product_and_version(client, headers, name="AshwaBio-X"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _content_hash(client, headers, pid, vid):
    response = client.get(_base(pid, vid), headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()["data"]["content_hash"]


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


def _list(client, headers, pid, vid, kind):
    response = client.get(f"{_base(pid, vid)}/{kind}", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def _mock_llm(payload):
    llm = MagicMock()
    llm.generate.return_value = payload
    return llm


def _assessment(claim_id, risk="medium"):
    """One fake model answer per recorded claim (ids are copied per version)."""
    return {
        "claim_id": claim_id,
        "suggested_evidence_status": "needs_evidence",
        "risk_level": risk,
        "rationale": "No independently verified evidence was retrieved for this claim.",
        "missing_evidence": ["Independent evidence for this claim"],
        "citation_chunk_ids": [],
    }


def _claim_llm_output(claim_ids):
    return json.dumps(
        {
            "assessments": [_assessment(cid) for cid in claim_ids],
            "summary": "Preliminary review of the recorded claims.",
            "warnings": [],
        }
    )


def _classification_payload():
    # The model's single best guess - which the gate must NOT present as the
    # conclusion while information is incomplete (bug 4).
    return json.dumps(
        {
            "preliminary_category": "possible_medicinal",
            "confidence": "medium",
            "rationale": "A proprietary formulation with a quantitative claim.",
            "alternative_categories": ["proprietary_ayurvedic"],
            "missing_information": ["Intended dose"],
        }
    )


@contextmanager
def _patched_analyze(claim_ids):
    """Patch retrieval + both model providers for one full-analysis run."""
    with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]), patch(
        "app.analysis.claim_analyzer.get_llm_provider",
        return_value=_mock_llm(_claim_llm_output(claim_ids)),
    ), patch(
        "app.analysis.classifier.get_llm_provider",
        return_value=_mock_llm(_classification_payload()),
    ):
        yield


def _run_analysis(client, headers, pid, vid, claim_ids):
    with _patched_analyze(claim_ids):
        response = client.post(f"{_base(pid, vid)}/analyze", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def _claim_ids(client, headers, pid, vid):
    return [c["id"] for c in _list(client, headers, pid, vid, "claims")]


# -------------------------------------------------------
# The acceptance scenario (steps 1-6): V1 with a full analysis
# -------------------------------------------------------

@pytest.fixture
def v1(client, auth_headers):
    """AshwaBio-X V1 exactly as the acceptance test describes it."""
    pid, vid = _product_and_version(client, auth_headers)

    ingredient = _add_ingredient(
        client,
        auth_headers,
        pid,
        vid,
        botanical_name="Withania somnifera",
        plant_part="root",
        quantity=100,
        quantity_unit="g",
        source_type="cultivated",
        source_location="Uttarakhand, India",
        preparation_method="powder",
    )

    # Empty strings must be stored as null, and a recorded process whose
    # parameters are absent carries the explicit "not yet provided" note.
    formulation = _put_formulation(
        client,
        auth_headers,
        pid,
        vid,
        process_description="Cold-press extraction of the root at controlled temperature.",
        extraction_method="cold_press",
        solvent="",
        pressure="",
        concentration="",
        temperature=4,
        temperature_unit="C",
    )

    claim_40 = _add_claim(
        client,
        auth_headers,
        pid,
        vid,
        "Improves bioavailability by 40%",
        claim_type="structure_function",
    )
    claim_wellness = _add_claim(
        client,
        auth_headers,
        pid,
        vid,
        "Supports everyday wellness",
        claim_type="wellness",
    )
    _add_market(client, auth_headers, pid, vid, "India")

    analysis = _run_analysis(
        client, auth_headers, pid, vid, [claim_40["id"], claim_wellness["id"]]
    )
    assert analysis["status"] == "completed", analysis

    return SimpleNamespace(
        client=client,
        headers=auth_headers,
        pid=pid,
        vid=vid,
        ingredient=ingredient,
        formulation=formulation,
        claim_40=claim_40,
        claim_wellness=claim_wellness,
        analysis=analysis,
        result=analysis["results"],
    )


# -------------------------------------------------------
# Bug 1 - the saved claim appears in the analysis, and the
# recorded run is pinned to the content it analysed
# -------------------------------------------------------

class TestBug1ClaimsInAnalysis:
    def test_saved_claims_appear_with_their_standing(self, v1):
        review = v1.result["claim_review"]
        assert review["claim_count"] == 2
        texts = [a["claim_text"] for a in review["assessments"]]
        assert "Improves bioavailability by 40%" in texts
        assert "Supports everyday wellness" in texts

        forty = next(
            a for a in review["assessments"] if a["claim_text"].endswith("by 40%")
        )
        assert forty["claim_provenance"] == "USER_PROVIDED"
        assert forty["evidence_status"] == "USER_PROVIDED_ONLY"
        assert forty["independent_verification"] == "NOT_FOUND"
        assert forty["review_required"] is True
        assert forty["reason"] == EXPECTED_REASON

    def test_run_is_pinned_to_the_content_hash_it_analysed(self, v1):
        current = _content_hash(v1.client, v1.headers, v1.pid, v1.vid)
        assert v1.analysis["content_hash"] == current

        # A claim saved after the run must make the recorded run stale rather
        # than silently presented as current.
        _add_claim(
            v1.client, v1.headers, v1.pid, v1.vid, "A claim saved after the run"
        )
        changed = _content_hash(v1.client, v1.headers, v1.pid, v1.vid)
        assert changed != current

        listed = _list(v1.client, v1.headers, v1.pid, v1.vid, "analyses")
        row = next(a for a in listed if a["id"] == v1.analysis["id"])
        assert row["content_hash"] == current
        assert row["content_hash"] != changed

    def test_no_claims_status_is_version_scoped(self, client, auth_headers):
        pid, vid1 = _product_and_version(client, auth_headers, name="Scoped Product")
        claim = _add_claim(client, auth_headers, pid, vid1, "Supports everyday wellness")
        first = _run_analysis(client, auth_headers, pid, vid1, [claim["id"]])
        assert first["results"]["claim_review"]["claim_status"] == "REVIEWED"

        created = client.post(
            f"/api/products/{pid}/versions",
            json={"start_empty": True, "change_reason": "empty"},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.json()
        vid2 = created.json()["data"]["id"]

        second = _run_analysis(client, auth_headers, pid, vid2, [])
        review = second["results"]["claim_review"]
        assert review["claim_status"] == "NO_CLAIMS_RECORDED"
        assert "only to this product version" in review["explanation"]["limit"]

        # The claim-bearing version is unaffected.
        listed = _list(client, auth_headers, pid, vid1, "analyses")
        row = next(a for a in listed if a["id"] == first["id"])
        assert row["results"]["claim_review"]["claim_status"] == "REVIEWED"


# -------------------------------------------------------
# Bug 3 - the formulation records exactly what was entered
# -------------------------------------------------------

class TestBug3FormulationShape:
    def test_empty_strings_are_stored_as_null_and_the_note_is_added(self, v1):
        f = v1.formulation
        assert f["extraction_method"] == "cold_press"
        assert f["temperature"] == 4
        assert f["temperature_unit"] == "C"
        assert f["solvent"] is None
        assert f["pressure"] is None
        assert f["duration"] is None
        assert f["concentration"] is None
        assert f["process_description"]
        assert f["other_parameters"] == PARAMETERS_NOTE

    def test_never_infers_a_missing_parameter(self, v1):
        # The stored record shows the missing fields as absent, not filled in.
        response = v1.client.get(f"{_base(v1.pid, v1.vid)}/formulation", headers=v1.headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["solvent"] is None
        assert data["pressure"] is None
        assert data["duration"] is None
        assert data["concentration"] is None
        assert data["other_parameters"] == PARAMETERS_NOTE


# -------------------------------------------------------
# Bug 4 - the classification never leads with a category
# while information is incomplete, and updates later
# -------------------------------------------------------

class TestBug4Classification:
    def test_unresolved_with_the_five_information_requirements(self, v1):
        c = v1.result["product_classification"]
        assert c["status"] == "UNRESOLVED"
        assert c["confidence"] == "LOW"
        assert c["review_required"] is True
        assert c["possible_categories"] == POSSIBLE_CATEGORIES
        assert c["missing_information"] == FIVE_MISSING
        # The model's single category never becomes the headline.
        assert v1.result["analysis_summary"]["classification"] == "UNRESOLVED"

    def test_updates_when_the_information_arrives(self, v1):
        _add_claim(
            v1.client,
            v1.headers,
            v1.pid,
            v1.vid,
            "Relieves insomnia symptoms",
            claim_type="therapeutic",
        )
        rerun = _run_analysis(
            v1.client, v1.headers, v1.pid, v1.vid, _claim_ids(v1.client, v1.headers, v1.pid, v1.vid)
        )
        c = rerun["results"]["product_classification"]
        assert c["status"] == "PRELIMINARY"
        assert c["confidence"] == "MEDIUM"
        assert c["review_required"] is True
        assert c["possible_categories"] == []
        assert c["missing_information"][0] == "manufacturing/licensing details"
        assert rerun["results"]["analysis_summary"]["classification"] == "PRELIMINARY"


# -------------------------------------------------------
# Bug 5 - every route is evidence-based and explicit
# -------------------------------------------------------

class TestBug5RouteMap:
    def test_every_route_carries_the_five_spec_fields(self, v1):
        routes = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}
        assert len(routes) == 9
        for route in routes.values():
            assert route["status"] in STATUS_TO_LABEL, route["route"]
            assert route["label"] == STATUS_TO_LABEL[route["status"]]
            assert route["why_flagged"]
            assert isinstance(route["missing_information"], list)
            assert route["next_action"]
            assert route["limitation"]

    def test_patent_route_for_a_recorded_process(self, v1):
        patent = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}["patent"]
        assert patent["status"] == "POTENTIALLY_RELEVANT"
        assert patent["label"] == STATUS_TO_LABEL["POTENTIALLY_RELEVANT"]
        assert patent["why_flagged"] == PATENT_WHY
        assert patent["missing_information"] == []
        assert patent["next_action"] == PATENT_NEXT
        assert patent["limitation"] == PATENT_LIMIT

    def test_trademark_requires_brand_intent(self, v1):
        tm = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}["trademark"]
        assert tm["status"] == "POTENTIALLY_RELEVANT"
        assert tm["missing_information"] == TRADEMARK_MISSING

    def test_insufficient_information_routes(self, v1):
        routes = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}
        for key in ("design", "gi", "plant_variety", "traditional_knowledge"):
            assert routes[key]["status"] == "ADDITIONAL_INFORMATION_NEEDED", key
            assert routes[key]["label"] == STATUS_TO_LABEL["ADDITIONAL_INFORMATION_NEEDED"]

    def test_written_material_and_confidential_process_routes(self, v1):
        routes = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}
        assert routes["copyright"]["status"] == "POTENTIALLY_RELEVANT"
        assert "written material" in routes["copyright"]["why_flagged"]
        assert routes["trade_secret"]["status"] == "POTENTIALLY_RELEVANT"
        assert any(
            "confidential" in m for m in routes["trade_secret"]["missing_information"]
        )

    def test_biodiversity_route_with_abs_gaps(self, v1):
        bio = {r["route"]: r for r in v1.result["ip_route_map"]["routes"]}["biodiversity_abs"]
        assert bio["status"] == "POTENTIALLY_RELEVANT"
        assert bio["why_flagged"] == BIODIVERSITY_WHY
        assert bio["missing_information"] == ABS_ITEMS
        assert bio["limitation"] == BIODIVERSITY_LIMIT


# -------------------------------------------------------
# Bug 6 - demo corpus is labelled everywhere, and verified
# records can be inserted without touching analysis code
# -------------------------------------------------------

class TestBug6PatentCorpus:
    def test_comprehensive_patent_signals_declare_the_corpus(self, v1):
        patent = v1.result["patent_signals"]
        assert patent["corpus_type"] == "DEMO_CORPUS"
        assert patent["live_search_performed"] is False
        assert patent["records_verified"] is False
        assert patent["retrieval_mode"] == "DEMO_CORPUS"
        assert patent["records"], "the demo corpus returns its records"
        for record in patent["records"]:
            assert record["record_label"] == DEMO_RECORD_LABEL
            assert record["verification_status"] == VERIFICATION_SYNTHETIC

    def test_search_endpoint_response_declares_the_corpus(self, v1):
        response = v1.client.post(f"{_base(v1.pid, v1.vid)}/patents/search", headers=v1.headers)
        assert response.status_code == 200, response.json()
        results = response.json()["data"]["results"]
        assert results["corpus_type"] == "DEMO_CORPUS"
        assert results["live_search_performed"] is False
        assert results["records_verified"] is False
        for record in results["records"]:
            assert record["record_label"] == DEMO_RECORD_LABEL


# -------------------------------------------------------
# Bug 7 - sources carry explicit metadata, never
# "AVAILABLE IN {jurisdiction}" concatenations
# -------------------------------------------------------

class TestBug7SourceMetadata:
    def test_registry_sources_have_explicit_metadata(self, v1):
        sources = v1.result["biodiversity_screening"]["sources"]
        assert sources, "the source registry is attached to the screening"
        for s in sources:
            assert s["source_type"] in SOURCE_TYPE_VOCAB, s["title"]
            assert s["jurisdiction"] in ("India", "International"), s["title"]
            assert s["authority"], s["title"]
            assert s["access_status"] in ("PUBLIC", "RESTRICTED_NOT_ACCESSED")
            assert s["verification_status"] in ("VERIFIED", "PENDING_REVIEW")

    def test_tkdl_is_labelled_restricted_and_never_accessed(self, v1):
        sources = v1.result["traditional_knowledge_screening"]["sources"]
        tkdl = next(s for s in sources if "TKDL" in s["title"])
        assert tkdl["access_status"] == "RESTRICTED_NOT_ACCESSED"
        assert tkdl["availability"] == "restricted"
        assert tkdl["note"] == TKDL_RESTRICTED_LABEL
        assert tkdl["jurisdiction"] == "India"

    def test_no_ambiguous_available_labels_anywhere(self, v1):
        blob = json.dumps(v1.result)
        assert "AVAILABLE IN" not in blob
        assert "AVAILABLE INT" not in blob
        assert '"IN"' not in blob  # jurisdiction codes are never surfaced raw


# -------------------------------------------------------
# Bug 8 - the analysis summary card
# -------------------------------------------------------

class TestBug8AnalysisSummary:
    def test_summary_card_shows_the_seven_spec_facts(self, v1):
        s = v1.result["analysis_summary"]
        assert s["product_version"] == "V1"
        assert s["overall_status"] == "PARTIALLY_SUPPORTED"
        assert s["evidence_completeness"] == "INCOMPLETE"
        assert s["claim_review"] == "REQUIRED"
        assert s["patent_screening"] == "DEMO_CORPUS"
        assert s["biodiversity_screening"] == "POTENTIALLY_RELEVANT"
        assert s["classification"] == "UNRESOLVED"
        assert s["expert_review"] == "RECOMMENDED"


# -------------------------------------------------------
# Bug 9 - "Why this result?" explanations
# -------------------------------------------------------

class TestBug9Explanations:
    def test_claim_review_explanation(self, v1):
        expl = v1.result["claim_review"]["explanation"]
        assert expl["signal"]
        assert expl["why"] == CLAIM_WHY
        assert expl["missing"]
        assert expl["limit"]

    def test_patent_screening_explanation(self, v1):
        expl = v1.result["patent_signals"]["explanation"]
        assert expl["signal"]
        assert expl["why"]
        assert isinstance(expl["missing"], list)
        assert expl["limit"]

    def test_biodiversity_explanation_exact_texts(self, v1):
        expl = v1.result["biodiversity_screening"]["explanation"]
        assert expl["why"] == BIODIVERSITY_WHY
        assert expl["missing"][: len(ABS_ITEMS)] == ABS_ITEMS
        assert expl["limit"] == BIODIVERSITY_LIMIT


# -------------------------------------------------------
# Bug 11 - the public-disclosure text
# -------------------------------------------------------

class TestBug11DisclosureText:
    def test_disclaimer_is_exact_and_free_of_deadlines(self):
        assert PUBLIC_DISCLOSURE_DISCLAIMER == SPEC_DISCLAIMER
        lowered = PUBLIC_DISCLOSURE_DISCLAIMER.lower()
        for banned in DISCLOSURE_BANNED:
            assert banned not in lowered

    def test_review_returns_the_disclaimer(self, v1):
        response = v1.client.post(
            f"{_base(v1.pid, v1.vid)}/disclosure-review", headers=v1.headers
        )
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["review_status"] == "NO_EVENTS_RECORDED"
        assert SPEC_DISCLAIMER in data["warnings"]

        created = v1.client.post(
            f"{_base(v1.pid, v1.vid)}/disclosures",
            json={"disclosure_type": "conference_presentation", "description": "Slide deck"},
            headers=v1.headers,
        )
        assert created.status_code == 201, created.json()
        response = v1.client.post(
            f"{_base(v1.pid, v1.vid)}/disclosure-review", headers=v1.headers
        )
        data = response.json()["data"]
        assert data["review_status"] == "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED"
        assert SPEC_DISCLAIMER in data["warnings"]


# -------------------------------------------------------
# Bug 10 - V2 seeded from V1, the four changes, and the
# change-impact comparison (acceptance steps 7-9)
# -------------------------------------------------------

class TestBug10ChangeImpact:
    @pytest.fixture
    def comparison(self, v1):
        """V2 = V1 + the four spec changes; returns the comparison results."""
        client, h = v1.client, v1.headers

        created = client.post(
            f"/api/products/{v1.pid}/versions",
            json={"copy_from_version_id": v1.vid, "change_reason": "Spec changes"},
            headers=h,
        )
        assert created.status_code == 201, created.json()
        vid2 = created.json()["data"]["id"]
        base2 = _base(v1.pid, vid2)

        ingredients = _list(client, h, v1.pid, vid2, "ingredients")
        ing2 = next(i for i in ingredients if i["common_name"] == "Ashwagandha")
        claims = _list(client, h, v1.pid, vid2, "claims")
        wellness2 = next(c for c in claims if "wellness" in c["claim_text"])

        for payload in (
            {"source_type": "wild"},                # cultivated -> wild
            {"preparation_method": "capsule"},      # powder -> capsule
        ):
            response = client.put(
                f"{base2}/ingredients/{ing2['id']}", json=payload, headers=h
            )
            assert response.status_code == 200, response.json()

        response = client.put(
            f"{base2}/claims/{wellness2['id']}",
            json={"claim_text": "Treats insomnia"},  # wellness claim text change
            headers=h,
        )
        assert response.status_code == 200, response.json()

        _add_market(client, h, v1.pid, vid2, "Germany")  # India -> India + Germany

        response = client.post(
            f"/api/products/{v1.pid}/change-impact",
            json={"old_version_id": v1.vid, "new_version_id": vid2},
            headers=h,
        )
        assert response.status_code == 200, response.json()
        return SimpleNamespace(v1=v1, vid2=vid2, ing2=ing2, results=response.json()["data"]["results"])

    def test_comparison_returns_all_five_spec_fields(self, comparison):
        res = comparison.results
        assert res["kind"] == "change_impact"
        assert res["changes"]
        assert res["affected_areas"]
        assert res["reassessment_recommended"]
        assert res["missing_information"]
        assert res["review_questions"]

    def test_affected_areas_match_the_spec_exactly(self, comparison):
        assert comparison.results["affected_areas"] == EXPECTED_AFFECTED_AREAS

    def test_reassessment_recommended_matches_the_changed_categories(self, comparison):
        assert comparison.results["reassessment_recommended"] == EXPECTED_REASSESSMENTS

    def test_the_four_changes_are_recorded(self, comparison):
        categories = {c["category"] for c in comparison.results["changes"]}
        assert {"cultivation", "claims", "formulation", "markets", "biodiversity_tk"} <= categories

        missing = comparison.results["missing_information"]
        assert any("wild-collected" in m for m in missing)
        assert any("German regulatory pathway" in m for m in missing)
        assert any("Formulation and process details" in m for m in missing)

        assert comparison.results["expert_review_reasons"]

    def test_no_automatic_approval_statement(self, comparison):
        blob = json.dumps(comparison.results).lower()
        for banned in APPROVAL_BANNED:
            assert banned not in blob

    def test_fresh_v2_analysis_reflects_the_new_content(self, comparison):
        v1, vid2 = comparison.v1, comparison.vid2
        client, h = v1.client, v1.headers

        analysis = _run_analysis(
            client, h, v1.pid, vid2, _claim_ids(client, h, v1.pid, vid2)
        )
        results = analysis["results"]

        # Fresh run: pinned to V2's current content.
        assert analysis["content_hash"] == _content_hash(client, h, v1.pid, vid2)

        texts = [a["claim_text"] for a in results["claim_review"]["assessments"]]
        assert "Treats insomnia" in texts
        assert "Supports everyday wellness" not in texts

        # Wild-harvested material moves the biodiversity status.
        assert results["analysis_summary"]["biodiversity_screening"] == "REVIEW_RECOMMENDED"
        # Both target markets are returned as their own countries.
        countries = {m["country"] for m in results["market_considerations"]}
        assert countries == {"India", "Germany"}


# -------------------------------------------------------
# Bug 2 - source location stays a source location; both
# target countries are returned; no derived market
# -------------------------------------------------------

class TestBug2TargetMarkets:
    def test_both_countries_returned_and_no_derived_market(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Market Product")
        _add_ingredient(
            client,
            auth_headers,
            pid,
            vid,
            botanical_name="Withania somnifera",
            plant_part="root",
            source_type="cultivated",
            source_location="Uttarakhand, India",
            preparation_method="powder",
        )
        _add_claim(client, auth_headers, pid, vid, "Supports everyday wellness")
        _put_formulation(
            client,
            auth_headers,
            pid,
            vid,
            extraction_method="cold_press",
            temperature=4,
            temperature_unit="C",
        )
        _add_market(client, auth_headers, pid, vid, "India")
        _add_market(client, auth_headers, pid, vid, "Germany")

        analysis = _run_analysis(
            client, auth_headers, pid, vid, _claim_ids(client, auth_headers, pid, vid)
        )
        result = analysis["results"]

        countries = {m["country"] for m in result["market_considerations"]}
        assert countries == {"India", "Germany"}

        # The ingredient's source location is displayed as recorded, and is
        # never turned into a target market.
        ingredients = _list(client, auth_headers, pid, vid, "ingredients")
        assert any(i["source_location"] == "Uttarakhand, India" for i in ingredients)
        markets = _list(client, auth_headers, pid, vid, "target-markets")
        assert {m["country"] for m in markets} == {"India", "Germany"}

        blob = json.dumps(result).lower()
        assert "west bengal" not in blob


# -------------------------------------------------------
# Bug 12 - reports use the actual recorded content
# -------------------------------------------------------

class TestBug12Reports:
    def test_ip_brief_and_handoff_generate_from_recorded_rows(self, v1):
        for kind in ("ip-brief", "expert-handoff"):
            response = v1.client.post(
                f"{_base(v1.pid, v1.vid)}/reports/{kind}", headers=v1.headers
            )
            assert response.status_code in (200, 201), response.json()
            data = response.json()["data"]
            pdf = v1.client.get(data["download_url"], headers=v1.headers)
            assert pdf.status_code == 200
            assert pdf.content.startswith(b"%PDF")

    def test_report_context_derives_labels_from_recorded_rows(self, v1):
        details = _comp_details(v1.result)

        assert any("DEMO_CORPUS" in line for line in details["corpus_lines"])
        assert any(
            line == "Live search performed: no" for line in details["corpus_lines"]
        )
        assert any(
            line == "Records verified: no" for line in details["corpus_lines"]
        )
        standing = " ".join(details["standing_lines"])
        assert "USER_PROVIDED" in standing
        assert "USER_PROVIDED_ONLY" in standing
        assert "NOT_FOUND" in standing
        assert "independent verification" in details["citation_line"]

    def test_formulation_lines_show_only_recorded_fields(self, v1):
        fields = (
            "process_description",
            "extraction_method",
            "solvent",
            "temperature",
            "temperature_unit",
            "pressure",
            "pressure_unit",
            "duration",
            "duration_unit",
            "concentration",
            "other_parameters",
        )
        record = SimpleNamespace(
            **{name: v1.formulation.get(name) for name in fields}
        )
        lines = _formulation_lines(record)
        assert any(line.startswith("Extraction method: cold_press") for line in lines)
        assert any(line.startswith("Temperature: 4") for line in lines)
        assert any(line.startswith("Solvent: not provided") for line in lines)
        assert any(line.startswith("Pressure: not provided") for line in lines)
        assert any(line.startswith("Duration: not provided") for line in lines)
        assert any(line.startswith("Concentration: not provided") for line in lines)
        assert any(PARAMETERS_NOTE in line for line in lines)
