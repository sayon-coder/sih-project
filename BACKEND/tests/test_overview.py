"""
Overall Product View tests (spec items 16, 19 and 20).

What these protect:

* the endpoint reports stored rows for the *selected* version only and never
  mixes data from another version;
* missing values are reported as missing, never invented;
* demo-corpus patent records are never returned as results;
* the status vocabularies stay inside the allowed sets (no "safe to launch",
  no approved/compliant wording, no hard-coded risk scores);
* an analysis whose content hash no longer matches the version is flagged
  ANALYSIS_OUTDATED rather than presented as current;
* biodiversity / traditional-knowledge / disclosure sections report what the
  recorded screenings actually say, including their exact spec sentences;
* recommended actions are derived from real gaps only;
* the chatbot's prompt carries the same aggregate the page shows (item 17);
* reports stay bound to the selected version;
* the AshwaBio-X V1 acceptance scenario (item 19) holds end to end.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.overview_service import (
    ANALYSIS_OUTDATED_NOTICE,
    BIODIVERSITY_POTENTIALLY_RELEVANT_REASON,
    CLAIM_USER_PROVIDED_WARNING,
    DISCLOSURE_ADVISORY,
    NO_DISCLOSURE_EVENT,
    NO_EVIDENCE_DOCS,
    NO_MARKET_EVIDENCE,
    NO_PATENT_RESULT,
    OVERVIEW_NOTICE,
    SOURCE_DOC_MISSING,
    TK_NO_SOURCE_NOTICE,
    STATUS_ANALYSIS_NOT_RUN,
    STATUS_ANALYSIS_OUTDATED,
    STATUS_COMPLETE_FOR_REVIEW,
    STATUS_INSUFFICIENT_INFORMATION,
    STATUS_PARTIALLY_COMPLETE,
    STATUS_REVIEW_REQUIRED,
    _overall_status,
)
from tests.test_chat_jurisdiction import ScriptedLLM, chat, make_product

CLAIM_40 = (
    "Our cold-press Ashwagandha extraction method increases bioavailability by 40%."
)

OVERALL_STATUSES = {
    STATUS_COMPLETE_FOR_REVIEW,
    STATUS_PARTIALLY_COMPLETE,
    STATUS_INSUFFICIENT_INFORMATION,
    STATUS_ANALYSIS_NOT_RUN,
    STATUS_ANALYSIS_OUTDATED,
    STATUS_REVIEW_REQUIRED,
}
CONFIDENCES = {"HIGH", "MEDIUM", "LOW", "NOT_ASSESSED"}
CLAIM_STATUSES = {
    "SUPPORTED_BY_ATTACHED_EVIDENCE",
    "USER_PROVIDED_ONLY",
    "EVIDENCE_MISSING",
    "EVIDENCE_REVIEW_REQUIRED",
    "SOURCE_BACKED",
    "NOT_ASSESSED",
}
BIO_STATUSES = {
    "NOT_ASSESSED",
    "INFORMATION_MISSING",
    "POTENTIALLY_RELEVANT",
    "REVIEW_REQUIRED",
    "SOURCE_DOCUMENTATION_RECORDED",
}
IP_STATUSES = {
    "NOT_ASSESSED",
    "SEARCH_NOT_RUN",
    "SEARCH_UNAVAILABLE",
    "NO_RELEVANT_RECORD_IDENTIFIED",
    "POTENTIALLY_RELEVANT",
    "FURTHER_REVIEW_RECOMMENDED",
    "VERIFIED_PUBLIC_RECORD",
}
MARKET_SECTION_STATUSES = {"REVIEW_REQUIRED", "ANALYSIS_NOT_RUN"}

#: Values the overview must never display (spec items 3, 4, 15).
FORBIDDEN_TEXT = (
    "SAFE_TO_LAUNCH",
    "LEGALLY_COMPLIANT",
    "PATENT_SAFE",
    "NO_RISK",
    "risk_score",
    "illustrative demo data",
    "Live Demo",
)


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _create(client, headers, **payload):
    response = client.post("/api/products", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _overview(client, headers, pid, vid):
    response = client.get(f"{_base(pid, vid)}/overview", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


def _fields(block):
    return {item["key"]: item for item in block["fields"]}


def _version_hash(client, headers, pid, vid):
    response = client.get(f"/api/products/{pid}/versions/{vid}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["content_hash"]


def _strings(node, out=None):
    """Every string anywhere inside a JSON-like structure."""
    if out is None:
        out = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            out.append(str(key))
            _strings(value, out)
    elif isinstance(node, list):
        for item in node:
            _strings(item, out)
    return out


def _mock_llm(payload):
    llm = MagicMock()
    llm.generate.return_value = payload
    return llm


def _classification_payload():
    return json.dumps(
        {
            "preliminary_category": "proprietary_ayurvedic",
            "confidence": "medium",
            "rationale": "A non-classical formulation with user-recorded claims.",
            "alternative_categories": ["possible_medicinal"],
            "missing_information": ["Intended dose"],
        }
    )


def _run_comprehensive(client, headers, pid, vid):
    """Run the real comprehensive analysis with the LLM layer mocked."""
    claims = client.get(f"{_base(pid, vid)}/claims", headers=headers).json()["data"]
    assessments = [
        {
            "claim_id": claim["id"],
            "suggested_evidence_status": "needs_evidence",
            "risk_level": "medium",
            "rationale": "No corpus evidence was retrieved for this claim.",
            "citation_chunk_ids": [],
        }
        for claim in claims
    ]
    claim_payload = json.dumps(
        {"assessments": assessments, "summary": "Recorded claims reviewed.", "warnings": []}
    )
    with patch(
        "app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]
    ), patch(
        "app.analysis.claim_analyzer.get_llm_provider",
        return_value=_mock_llm(claim_payload),
    ), patch(
        "app.analysis.classifier.get_llm_provider",
        return_value=_mock_llm(_classification_payload()),
    ):
        response = client.post(f"{_base(pid, vid)}/analyze", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# -------------------------------------------------------
# Endpoint contract
# -------------------------------------------------------

class TestOverviewEndpoint:
    def test_requires_authentication(self, client, auth_headers):
        pid, vid = _create(client, auth_headers, name="Auth Overview")
        assert client.get(f"{_base(pid, vid)}/overview").status_code == 401

    def test_other_users_version_is_404(self, client, auth_headers, second_user_headers):
        pid, vid = _create(client, auth_headers, name="Private Overview")
        response = client.get(
            f"{_base(pid, vid)}/overview", headers=second_user_headers
        )
        assert response.status_code == 404

    def test_contract_keys_and_disclaimers(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)

        for key in (
            "product",
            "overall_status",
            "facts",
            "formulation",
            "ingredients",
            "claims",
            "evidence",
            "target_markets",
            "regulatory_classification",
            "ip_review",
            "biodiversity_abs_review",
            "traditional_knowledge_review",
            "disclosures",
            "analysis_history",
            "recommended_actions",
            "missing_information",
            "provenance",
            "disclaimers",
        ):
            assert key in overview, f"missing contract key: {key}"

        product = overview["product"]
        assert product["name"].startswith("AshwaBio-")
        assert product["version"] == 1
        assert isinstance(overview["disclaimers"], list)
        assert overview["disclaimers"][0] == OVERVIEW_NOTICE
        assert len(overview["disclaimers"]) >= 2
        assert isinstance(overview["missing_information"], list)
        for section in ("facts", "formulation", "ingredients", "claims"):
            assert overview["provenance"].get(section), section

    def test_status_vocabularies_and_forbidden_text(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India", "Germany"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)

        overall = overview["overall_status"]
        assert overall["status"] in OVERALL_STATUSES
        assert overall["confidence"] in CONFIDENCES

        classification = overview["regulatory_classification"]
        assert classification["status"] in {"UNRESOLVED", "PRELIMINARY"}
        assert classification["confidence"] in {"HIGH", "MEDIUM", "LOW"}

        assert overview["ip_review"]["status"] in IP_STATUSES
        assert overview["biodiversity_abs_review"]["status"] in BIO_STATUSES
        assert overview["traditional_knowledge_review"]["status"] in {
            "NOT_ASSESSED",
            "ADDITIONAL_INFORMATION_NEEDED",
            "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
            "REVIEW_RECOMMENDED",
            "POTENTIALLY_RELEVANT",
        }
        for claim in overview["claims"]:
            assert claim["evidence_status"] in CLAIM_STATUSES
            assert claim["review_status"] in {
                "REVIEW_REQUIRED",
                "REVIEWED",
                "CHANGES_REQUESTED",
            }
        for section in overview["target_markets"]["sections"]:
            assert section["status"] in MARKET_SECTION_STATUSES
        for action in overview["recommended_actions"]:
            assert action["priority"] in {"HIGH", "MEDIUM", "LOW"}

        blob = json.dumps(overview)
        for token in FORBIDDEN_TEXT:
            assert token not in blob, f"forbidden text rendered: {token}"

    def test_get_does_not_modify_the_version(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        before_hash = _version_hash(client, auth_headers, pid, vid)
        before_claims = client.get(
            f"{_base(pid, vid)}/claims", headers=auth_headers
        ).json()["data"]
        before_ingredients = client.get(
            f"{_base(pid, vid)}/ingredients", headers=auth_headers
        ).json()["data"]

        _overview(client, auth_headers, pid, vid)

        assert _version_hash(client, auth_headers, pid, vid) == before_hash
        after_claims = client.get(
            f"{_base(pid, vid)}/claims", headers=auth_headers
        ).json()["data"]
        after_ingredients = client.get(
            f"{_base(pid, vid)}/ingredients", headers=auth_headers
        ).json()["data"]
        assert after_claims == before_claims
        assert after_ingredients == before_ingredients


# -------------------------------------------------------
# Version isolation / stale-state prevention
# -------------------------------------------------------

class TestVersionIsolation:
    def test_versions_never_mix(self, client, auth_headers):
        pid, v1 = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        created = client.post(
            f"/api/products/{pid}/versions", json={}, headers=auth_headers
        )
        assert created.status_code in (200, 201), created.text
        v2 = created.json()["data"]["id"]

        response = client.post(
            f"{_base(pid, v2)}/claims",
            json={"claim_text": "Second version only claim", "claim_type": "wellness"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        overview_v1 = _overview(client, auth_headers, pid, v1)
        overview_v2 = _overview(client, auth_headers, pid, v2)

        v1_texts = [claim["claim_text"] for claim in overview_v1["claims"]]
        v2_texts = [claim["claim_text"] for claim in overview_v2["claims"]]

        assert CLAIM_40 in v1_texts
        assert "Second version only claim" in v2_texts
        assert "Second version only claim" not in v1_texts
        assert overview_v1["product"]["version"] == 1
        assert overview_v2["product"]["version"] == 2

        # Every claim the overview shows must belong to that version's own
        # stored rows - never to the other one.
        stored_v1 = {
            claim["claim_text"]
            for claim in client.get(
                f"{_base(pid, v1)}/claims", headers=auth_headers
            ).json()["data"]
        }
        stored_v2 = {
            claim["claim_text"]
            for claim in client.get(
                f"{_base(pid, v2)}/claims", headers=auth_headers
            ).json()["data"]
        }
        assert set(v1_texts) <= stored_v1
        assert set(v2_texts) <= stored_v2

    def test_each_overview_reports_its_own_content_hash(self, client, auth_headers):
        pid, v1 = make_product(client, auth_headers, markets=["India"])
        created = client.post(
            f"/api/products/{pid}/versions", json={}, headers=auth_headers
        )
        v2 = created.json()["data"]["id"]
        response = client.post(
            f"{_base(pid, v2)}/claims",
            json={"claim_text": "A later claim", "claim_type": "wellness"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        overview_v1 = _overview(client, auth_headers, pid, v1)
        overview_v2 = _overview(client, auth_headers, pid, v2)

        assert overview_v1["product"]["content_hash"] == _version_hash(
            client, auth_headers, pid, v1
        )
        assert overview_v2["product"]["content_hash"] == _version_hash(
            client, auth_headers, pid, v2
        )
        assert overview_v1["product"]["content_hash"] != overview_v2["product"][
            "content_hash"
        ]


# -------------------------------------------------------
# Facts / formulation / ingredients
# -------------------------------------------------------

class TestProductFacts:
    def test_missing_fields_reported_honestly(self, client, auth_headers):
        pid, vid = _create(client, auth_headers, name="AshwaBio-X")
        overview = _overview(client, auth_headers, pid, vid)
        facts = _fields(overview["facts"])

        assert facts["common_product_name"]["value"] == "AshwaBio-X"
        assert facts["product_name"]["value"] == "AshwaBio-X"
        # The product owner is recorded (viewer may see their own record).
        assert facts["owner"]["value"] == "testuser"
        assert facts["owner"]["provenance"] == "USER_PROVIDED"
        for key in ("intended_use", "dosage_form", "manufacturing_status"):
            assert facts[key]["value"] == "Not provided", key
            assert facts[key]["provenance"] == "NOT_PROVIDED", key
        assert facts["product_description"]["value"] == "Not provided"
        assert facts["ingredient_count"]["value"] == 0
        assert facts["ingredient_count"]["provenance"] == "SYSTEM_DERIVED"
        assert facts["target_market_count"]["value"] == 0
        assert facts["disclosure_event_count"]["value"] == 0


class TestFormulation:
    def test_formulation_maps_stored_fields_with_provenance(self, client, auth_headers):
        pid, vid = make_product(client, auth_headers, markets=["India"])
        overview = _overview(client, auth_headers, pid, vid)
        fields = _fields(overview["formulation"])

        assert overview["formulation"]["present"] is True
        assert fields["extraction_method"]["value"] == "cold_press"
        assert fields["extraction_method"]["provenance"] == "USER_PROVIDED"
        assert fields["temperature"]["value"] == "4°C"
        # Not recorded fields are shown as missing, never filled in.
        for key in (
            "solvent",
            "pressure",
            "duration",
            "concentration",
            "standardisation",
        ):
            assert fields[key]["value"] == "Not provided", key
            assert fields[key]["provenance"] == "NOT_PROVIDED", key

        summary = _fields({"fields": overview["formulation"]["source_summary"]})
        assert summary["source_status"]["value"] == "cultivated"
        assert summary["source_location"]["value"] == "Uttarakhand, India"

    def test_missing_formulation_reports_missing(self, client, auth_headers):
        pid, vid = _create(client, auth_headers, name="No Formulation")
        overview = _overview(client, auth_headers, pid, vid)
        assert overview["formulation"]["present"] is False
        for item in overview["formulation"]["fields"]:
            assert item["value"] == "Not provided"
            assert item["provenance"] == "NOT_PROVIDED"


class TestIngredients:
    def test_ingredient_source_and_documentation(self, client, auth_headers):
        pid, vid = make_product(client, auth_headers, markets=["India"])
        overview = _overview(client, auth_headers, pid, vid)

        assert len(overview["ingredients"]) == 1
        ingredient = overview["ingredients"][0]
        fields = _fields(ingredient)
        assert fields["common_name"]["value"] == "Ashwagandha"
        assert fields["botanical_name"]["value"] == "Withania somnifera"
        assert fields["quantity"]["value"] == "100 g"
        assert fields["source_status"]["value"] == "cultivated"
        assert fields["source_location"]["value"] == "Uttarakhand, India"
        # No supplier column exists anywhere in the data model.
        assert fields["supplier"]["value"] == "Not provided"
        assert fields["documentation_status"]["value"] == SOURCE_DOC_MISSING
        assert fields["documentation_status"]["provenance"] == "NOT_PROVIDED"


# -------------------------------------------------------
# Claims and evidence
# -------------------------------------------------------

class TestClaimsEvidence:
    def test_claim_standing_warning_and_marketing_status(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India", "Germany"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)

        assert overview["evidence"] == []
        assert len(overview["claims"]) == 1
        claim = overview["claims"][0]
        assert claim["claim_text"] == CLAIM_40
        assert claim["provenance"] == "USER_PROVIDED"
        assert claim["evidence_status"] == "USER_PROVIDED_ONLY"
        assert claim["independent_verification"] == "NOT_FOUND"
        assert claim["review_required"] is True
        assert claim["review_status"] == "REVIEW_REQUIRED"
        assert claim["marketing_status"] == "DO NOT PRESENT AS VERIFIED"
        assert claim["warning"] == CLAIM_USER_PROVIDED_WARNING
        assert claim["linked_evidence"] == []
        assert claim["evidence_linkage"] == NO_EVIDENCE_DOCS
        assert claim["markets_affected"] == ["India", "Germany"]
        assert claim["linked_analysis"] is None

    def test_verified_evidence_produces_supported_status(
        self, client, auth_headers, db_session
    ):
        from app.models import Evidence
        from app.models.ingredient_models import VerificationStatus

        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        response = client.post(
            f"{_base(pid, vid)}/evidence",
            json={
                "title": "Withanolides assay report",
                "evidence_type": "scientific_paper",
                "source_url": "https://example.org/assay",
                "doi": "10.1000/assay",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        # The expert workflow (not the user API) marks evidence verified; the
        # test records that workflow's outcome directly on the row.
        evidence = (
            db_session.query(Evidence)
            .filter(Evidence.product_version_id == vid)
            .one()
        )
        evidence.verification_status = VerificationStatus.VERIFIED
        db_session.commit()

        overview = _overview(client, auth_headers, pid, vid)
        claim = overview["claims"][0]
        assert claim["evidence_status"] == "SUPPORTED_BY_ATTACHED_EVIDENCE"
        assert len(claim["linked_evidence"]) == 1
        assert claim["evidence_linkage"].startswith(
            "Evidence is recorded for the product version."
        )

        stored = overview["evidence"][0]
        assert stored["verification_status"] == "verified"
        assert stored["source_url"] == "https://example.org/assay"
        assert stored["doi"] == "10.1000/assay"


# -------------------------------------------------------
# Target markets
# -------------------------------------------------------

class TestTargetMarkets:
    def test_markets_separated_from_source_location(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India", "Germany"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)
        markets = overview["target_markets"]

        assert [row["country"] for row in markets["markets"]] == ["India", "Germany"]
        labels = [section["label"] for section in markets["sections"]]
        assert labels == ["INDIA", "GERMANY/EU"]
        for section in markets["sections"]:
            assert section["evidence_note"] == NO_MARKET_EVIDENCE
            assert section["sources_used"] == []
            assert section["missing_information"]
            assert section["next_action"]

        # The ingredient source location is never presented as a market.
        blob = json.dumps(markets)
        assert "Uttarakhand" not in blob
        assert "cultivated" not in blob


# -------------------------------------------------------
# Regulatory classification
# -------------------------------------------------------

class TestClassification:
    def test_unresolved_without_recorded_analysis(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)
        classification = overview["regulatory_classification"]

        assert classification["status"] == "UNRESOLVED"
        assert classification["confidence"] == "LOW"
        assert classification["reason"] == (
            "Insufficient product and intended-use information."
        )
        assert classification["review_required"] is True
        assert classification["classification"] == "UNRESOLVED"
        assert classification["possible_pathways"]
        assert classification["analysis_run"] is None
        assert classification["source"] == "NOT_ASSESSED"
        assert "intended use" in classification["missing_information"]

    def test_classification_from_recorded_analysis(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        _run_comprehensive(client, auth_headers, pid, vid)
        overview = _overview(client, auth_headers, pid, vid)
        classification = overview["regulatory_classification"]

        assert classification["source"] == "ANALYSIS_DERIVED"
        assert classification["analysis_run"]["run_id"]
        assert classification["analysis_run"]["analysis_type"] in {
            "comprehensive",
            "product_classification",
        }
        # A single non-therapeutic claim leaves the category unresolved: the
        # analysis reports candidate pathways instead of one conclusion.
        assert classification["status"] == "UNRESOLVED"
        assert classification["confidence"] == "LOW"
        assert classification["review_required"] is True
        assert "possible_medicinal" in classification["possible_pathways"] or (
            classification["candidate_category"] == "proprietary_ayurvedic"
        )
        assert classification["possible_pathways_note"]


# -------------------------------------------------------
# IP and prior-art review
# -------------------------------------------------------

class TestIPReview:
    def test_no_search_reports_search_not_run(self, client, auth_headers):
        pid, vid = make_product(client, auth_headers, markets=["India"])
        overview = _overview(client, auth_headers, pid, vid)
        ip_review = overview["ip_review"]

        assert ip_review["status"] == "SEARCH_NOT_RUN"
        assert ip_review["notice"] == NO_PATENT_RESULT
        assert ip_review["reason"] == (
            "No patent screening has been recorded for this version."
        )
        assert ip_review["records"] == []
        assert ip_review["run"] is None

    def test_search_never_returns_demo_records(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        response = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert response.status_code == 200, response.text

        listed = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()[
            "data"
        ]
        overview = _overview(client, auth_headers, pid, vid)
        ip_review = overview["ip_review"]

        # Synthetic demonstration records exist on the platform, but the
        # overview never presents them as results for this version.
        assert ip_review["records"] == []
        assert ip_review["status"] == "SEARCH_UNAVAILABLE"
        assert ip_review["notice"] == NO_PATENT_RESULT
        assert ip_review["run"] is not None
        if listed:
            assert ip_review["synthetic_records_omitted"] == len(listed)
            assert ip_review["demo_notice"]

        blob = json.dumps(overview)
        for record in listed:
            assert record["record_id"] not in blob
            if record.get("patent_number"):
                assert record["patent_number"] not in blob
        # The exact spec sentence is shown for the record list.
        assert NO_PATENT_RESULT in blob


# -------------------------------------------------------
# Biodiversity / ABS and traditional knowledge
# -------------------------------------------------------

class TestScreenings:
    def test_biodiversity_potentially_relevant_for_indian_origin(
        self, client, auth_headers
    ):
        pid, vid = make_product(client, auth_headers, markets=["India"])
        before = _overview(client, auth_headers, pid, vid)
        assert before["biodiversity_abs_review"]["status"] == "NOT_ASSESSED"

        response = client.post(
            f"{_base(pid, vid)}/biodiversity/screen", headers=auth_headers
        )
        assert response.status_code == 200, response.text

        overview = _overview(client, auth_headers, pid, vid)
        bio = overview["biodiversity_abs_review"]
        assert bio["status"] == "POTENTIALLY_RELEVANT"
        assert bio["screening_status"] == "POTENTIALLY_RELEVANT"
        assert bio["reason"] == BIODIVERSITY_POTENTIALLY_RELEVANT_REASON
        assert bio["run"] is not None
        assert "Exact supplier" in bio["missing_fields"]
        assert "Access arrangement" in bio["missing_fields"]
        assert "Permits or declarations" in bio["missing_fields"]
        # The collected screening fields show the recorded source, not a
        # conclusion about obligations.
        assert any(
            "Uttarakhand" in str(origin)
            for origin in bio["collected"].get("origins", [])
        )

    def test_traditional_knowledge_status_and_restricted_sources(
        self, client, auth_headers
    ):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        before = _overview(client, auth_headers, pid, vid)
        assert before["traditional_knowledge_review"]["status"] == "NOT_ASSESSED"

        response = client.post(
            f"{_base(pid, vid)}/traditional-knowledge/screen", headers=auth_headers
        )
        assert response.status_code == 200, response.text

        overview = _overview(client, auth_headers, pid, vid)
        tk = overview["traditional_knowledge_review"]
        assert tk["status"] == "ADDITIONAL_INFORMATION_NEEDED"
        assert tk["notice"] == TK_NO_SOURCE_NOTICE
        assert tk["traditional_use_recorded"] == "NO"
        assert tk["source_supplied"] == "NO"
        assert tk["restricted_sources_excluded"] == ["TKDL"]
        assert tk["run"] is not None
        # The platform never claims to have searched restricted sources.
        blob = json.dumps(tk)
        assert "not accessed, searched or reproduced" in blob
        assert tk["potential_considerations"]


# -------------------------------------------------------
# Disclosure history
# -------------------------------------------------------

class TestDisclosures:
    def test_disclosure_history_states(self, client, auth_headers):
        pid, vid = make_product(client, auth_headers, markets=["India"])
        before = _overview(client, auth_headers, pid, vid)
        assert before["disclosures"]["event_count"] == 0
        assert before["disclosures"]["review_status"] == "NO_EVENTS_RECORDED"
        assert before["disclosures"]["notice"] == NO_DISCLOSURE_EVENT
        assert before["disclosures"]["advisory"] == DISCLOSURE_ADVISORY

        response = client.post(
            f"{_base(pid, vid)}/disclosures",
            json={
                "disclosure_type": "conference_presentation",
                "description": "Presented the formulation at a conference.",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        after = _overview(client, auth_headers, pid, vid)
        assert after["disclosures"]["event_count"] == 1
        assert after["disclosures"]["notice"] is None
        assert after["disclosures"]["review_status"] == (
            "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED"
        )
        event = after["disclosures"]["events"][0]
        assert event["disclosure_type"] == "conference_presentation"
        assert event["description"] == "Presented the formulation at a conference."


# -------------------------------------------------------
# Analysis history / outdated runs
# -------------------------------------------------------

class TestAnalysisHistory:
    def test_history_records_runs_and_hash_comparison(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        _run_comprehensive(client, auth_headers, pid, vid)
        overview = _overview(client, auth_headers, pid, vid)

        assert overview["analysis_history"], "a completed run must be listed"
        entry = overview["analysis_history"][0]
        assert entry["analysis_type"] == "comprehensive"
        assert entry["status"] == "completed"
        assert entry["content_hash"] == overview["product"]["content_hash"]
        assert entry["hash_matches"] is True
        assert entry["outdated"] is False
        assert entry["timestamp"]
        assert entry["claims_analysed"] == 1
        assert entry["missing_information_count"] is not None
        assert entry["outdated_notice"] is None

        assert overview["analysis"]["status"] == "completed"
        assert overview["analysis"]["completed_runs"] >= 1

    def test_outdated_analysis_is_flagged(self, client, auth_headers):
        pid, vid = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40]
        )
        _run_comprehensive(client, auth_headers, pid, vid)

        # Change the version's content after the run: the stored hash no
        # longer matches the current version (real stale state, not a fake).
        claims = client.get(f"{_base(pid, vid)}/claims", headers=auth_headers).json()[
            "data"
        ]
        response = client.put(
            f"{_base(pid, vid)}/claims/{claims[0]['id']}",
            json={"claim_text": CLAIM_40 + " Updated wording."},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        overview = _overview(client, auth_headers, pid, vid)
        overall = overview["overall_status"]
        assert overall["status"] == STATUS_ANALYSIS_OUTDATED
        assert overall["reason"] == ANALYSIS_OUTDATED_NOTICE
        assert overall["outdated_notice"] == ANALYSIS_OUTDATED_NOTICE
        assert overall["analysis_outdated"] is True
        assert overall["analysis_version_hash"] != overall["current_version_hash"]
        assert overview["analysis"]["outdated"] is True

        entry = overview["analysis_history"][0]
        assert entry["outdated"] is True
        assert entry["hash_matches"] is False
        assert "OUTDATED" in entry["outdated_notice"]


# -------------------------------------------------------
# Overall status ladder (deterministic unit test)
# -------------------------------------------------------

class TestOverallStatusLadder:
    def test_precedence_and_confidence_ladder(self):
        run = object()  # any completed-analysis sentinel

        first = _overall_status(None, None, "hash", False, [], [], [], None)
        assert first["status"] == STATUS_ANALYSIS_NOT_RUN
        assert first["confidence"] == "NOT_ASSESSED"

        outdated = _overall_status(run, "old", "new", True, ["m"], ["r"], ["s"], "t")
        assert outdated["status"] == STATUS_ANALYSIS_OUTDATED
        assert outdated["confidence"] == "LOW"
        assert outdated["analysis_outdated"] is True

        insufficient = _overall_status(
            run, "hash", "hash", False, ["missing"], ["review"], ["soft"], "t"
        )
        assert insufficient["status"] == STATUS_INSUFFICIENT_INFORMATION
        assert insufficient["confidence"] == "LOW"

        review = _overall_status(run, "hash", "hash", False, [], ["review"], ["soft"], "t")
        assert review["status"] == STATUS_REVIEW_REQUIRED
        assert review["confidence"] == "MEDIUM"

        partial = _overall_status(run, "hash", "hash", False, [], [], ["soft"], "t")
        assert partial["status"] == STATUS_PARTIALLY_COMPLETE
        assert partial["confidence"] == "MEDIUM"

        complete = _overall_status(run, "hash", "hash", False, [], [], [], "t")
        assert complete["status"] == STATUS_COMPLETE_FOR_REVIEW
        assert complete["confidence"] == "HIGH"


# -------------------------------------------------------
# Recommended actions
# -------------------------------------------------------

class TestRecommendedActions:
    def test_actions_derive_from_real_gaps(self, client, auth_headers):
        pid, vid = _create(client, auth_headers, name="Bare Product")
        overview = _overview(client, auth_headers, pid, vid)
        actions = {action["id"]: action for action in overview["recommended_actions"]}

        assert "run_analysis" in actions
        assert "confirm_product_category" in actions
        assert "add_target_markets" in actions
        assert "add_ingredients" in actions
        # No claims recorded -> no evidence action; no disclosures -> none either.
        assert "attach_claim_evidence" not in actions
        assert "review_disclosures" not in actions

        for action in overview["recommended_actions"]:
            assert action["priority"] in {"HIGH", "MEDIUM", "LOW"}
            assert action["reason"]
            assert action["section"]
            assert action["link"].startswith("/")
            assert action["status"] == "OPEN"

    def test_no_action_for_present_data(self, client, auth_headers):
        pid, vid = _create(
            client,
            auth_headers,
            name="Complete Enough",
            category="proprietary_ayurvedic",
        )
        make_product_setup = client.post(
            f"{_base(pid, vid)}/ingredients",
            json={
                "common_name": "Ashwagandha",
                "botanical_name": "Withania somnifera",
                "source_type": "cultivated",
                "source_location": "Uttarakhand, India",
                "preparation_method": "powder",
            },
            headers=auth_headers,
        )
        assert make_product_setup.status_code == 201, make_product_setup.text
        client.post(
            f"{_base(pid, vid)}/target-markets",
            json={"country": "India"},
            headers=auth_headers,
        )

        overview = _overview(client, auth_headers, pid, vid)
        ids = {action["id"] for action in overview["recommended_actions"]}
        assert "add_target_markets" not in ids
        assert "add_ingredients" not in ids
        assert "confirm_product_category" not in ids


# -------------------------------------------------------
# Chatbot consistency (spec item 17)
# -------------------------------------------------------

class TestChatConsistency:
    def test_chat_prompt_carries_the_same_overview(
        self, client, auth_headers, monkeypatch
    ):
        pid, vid = make_product(
            client, auth_headers, markets=["India", "Germany"], claims=[CLAIM_40]
        )
        overview = _overview(client, auth_headers, pid, vid)
        assert overview["product"]["content_hash"]

        fake = ScriptedLLM(
            json.dumps(
                {
                    "answer": "The recorded overview is shown in the Product View.",
                    "citations": [],
                    "insufficient_evidence": False,
                    "warnings": [],
                }
            )
        )
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)
        monkeypatch.setattr("app.routers.assistant.hybrid_retrieve", lambda *a, **k: [])

        response = chat(
            client,
            auth_headers,
            {
                "message": "What does my product overview say?",
                "product_id": pid,
                "product_version_id": vid,
                "include_my_documents": True,
            },
        )
        assert response.status_code == 200, response.text

        prompt = fake.user_prompts[0]
        assert '"overview"' in prompt
        assert f'"overall_status": "{overview["overall_status"]["status"]}"' in prompt
        assert f'"content_hash": "{overview["product"]["content_hash"]}"' in prompt
        assert (
            f'"classification": "{overview["regulatory_classification"]["classification"]}"'
            in prompt
        )
        assert (
            f'"status": "{overview["ip_review"]["status"]}"' in prompt
        )
        # The same disclaimers travel with the data.
        assert overview["disclaimers"][0][:40] in prompt or '"notice"' in prompt


# -------------------------------------------------------
# Reports stay bound to the selected version
# -------------------------------------------------------

class TestReports:
    def test_report_is_bound_to_selected_version(self, client, auth_headers):
        pid, v1 = make_product(client, auth_headers, markets=["India"])
        created = client.post(
            f"/api/products/{pid}/versions", json={}, headers=auth_headers
        )
        v2 = created.json()["data"]["id"]
        response = client.post(
            f"{_base(pid, v2)}/ingredients",
            json={"common_name": "Extra", "botanical_name": "Extraus plantus"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        report = client.post(
            f"{_base(pid, v1)}/reports/expert-handoff", headers=auth_headers
        )
        assert report.status_code == 201, report.text
        report_data = report.json()["data"]

        # The report row is pinned to the selected version; its own
        # content_hash is the PDF file hash (spec Phase 8b), not the version
        # hash, so version binding is asserted through the version id and the
        # version-scoped listing below.
        assert report_data["product_version_id"] == v1
        assert report_data["product_version_id"] != v2

        listed_v1 = client.get(f"{_base(pid, v1)}/reports", headers=auth_headers).json()[
            "data"
        ]
        listed_v2 = client.get(f"{_base(pid, v2)}/reports", headers=auth_headers).json()[
            "data"
        ]
        assert [row["id"] for row in listed_v1] == [report_data["id"]]
        assert listed_v2 == []


# -------------------------------------------------------
# Acceptance scenario: AshwaBio-X V1 (spec item 19)
# -------------------------------------------------------

class TestAcceptanceAshwaBioXV1:
    def test_ashwa_bio_x_v1_overall_product_view(self, client, auth_headers):
        pid, vid = make_product(
            client,
            auth_headers,
            name="AshwaBio-X",
            markets=["India", "Germany"],
            claims=[CLAIM_40],
        )

        # Recorded runs for this version (all deterministic or LLM-mocked).
        for path in (
            "/biodiversity/screen",
            "/traditional-knowledge/screen",
            "/patents/search",
        ):
            response = client.post(f"{_base(pid, vid)}{path}", headers=auth_headers)
            assert response.status_code == 200, f"{path}: {response.text}"
        _run_comprehensive(client, auth_headers, pid, vid)

        overview = _overview(client, auth_headers, pid, vid)
        blob = json.dumps(overview)

        # --- product / version header ---------------------------------
        assert overview["product"]["name"] == "AshwaBio-X"
        assert overview["product"]["version"] == 1
        assert overview["product"]["content_hash"] == _version_hash(
            client, auth_headers, pid, vid
        )

        # --- expected saved data (never invented) ---------------------
        ingredient = _fields(overview["ingredients"][0])
        assert ingredient["common_name"]["value"] == "Ashwagandha"
        assert ingredient["botanical_name"]["value"] == "Withania somnifera"
        assert ingredient["plant_part"]["value"] == "root"
        assert ingredient["quantity"]["value"] == "100 g"
        assert ingredient["source_location"]["value"] == "Uttarakhand, India"
        formulation = _fields(overview["formulation"])
        assert formulation["extraction_method"]["value"] == "cold_press"
        assert formulation["temperature"]["value"] == "4°C"
        assert formulation["solvent"]["value"] == "Not provided"
        assert formulation["pressure"]["value"] == "Not provided"
        assert formulation["duration"]["value"] == "Not provided"
        assert formulation["concentration"]["value"] == "Not provided"

        # --- claim values, provenance and analysis link ----------------
        claim = overview["claims"][0]
        assert claim["claim_text"] == CLAIM_40
        assert claim["provenance"] == "USER_PROVIDED"
        assert claim["evidence_status"] == "USER_PROVIDED_ONLY"
        assert claim["independent_verification"] == "NOT_FOUND"
        assert claim["review_required"] is True
        assert claim["marketing_status"] == "DO NOT PRESENT AS VERIFIED"
        assert claim["linked_analysis"] is not None
        assert claim["linked_analysis"]["analysis_type"] in {
            "comprehensive",
            "claim_analysis",
        }

        # --- overall status stays inside the allowed set ----------------
        overall = overview["overall_status"]
        assert overall["status"] == STATUS_INSUFFICIENT_INFORMATION
        assert overall["status"] in OVERALL_STATUSES
        assert overall["confidence"] in CONFIDENCES

        # --- classification uncertainty --------------------------------
        classification = overview["regulatory_classification"]
        assert classification["status"] == "UNRESOLVED"
        assert classification["confidence"] == "LOW"
        assert classification["reason"] == (
            "Insufficient product and intended-use information."
        )
        assert classification["review_required"] is True

        # --- markets separated from the source location -----------------
        countries = {row["country"] for row in overview["target_markets"]["markets"]}
        assert countries == {"India", "Germany"}
        assert "Uttarakhand" not in json.dumps(overview["target_markets"])
        germany = next(
            section
            for section in overview["target_markets"]["sections"]
            if section["label"] == "GERMANY/EU"
        )
        assert germany["evidence_note"] == NO_MARKET_EVIDENCE
        assert germany["status"] in MARKET_SECTION_STATUSES
        assert germany["missing_information"]

        # --- biodiversity / traditional knowledge / disclosures ---------
        bio = overview["biodiversity_abs_review"]
        assert bio["status"] == "POTENTIALLY_RELEVANT"
        assert bio["reason"] == BIODIVERSITY_POTENTIALLY_RELEVANT_REASON
        tk = overview["traditional_knowledge_review"]
        assert tk["status"] == "ADDITIONAL_INFORMATION_NEEDED"
        assert overview["disclosures"]["event_count"] == 0
        assert overview["disclosures"]["notice"] == NO_DISCLOSURE_EVENT

        # --- IP review: no synthetic records, exact spec sentence -------
        ip_review = overview["ip_review"]
        assert ip_review["records"] == []
        assert ip_review["status"] in IP_STATUSES
        assert ip_review["notice"] == NO_PATENT_RESULT
        assert NO_PATENT_RESULT in blob

        # --- analysis history and outdated marker ----------------------
        assert overview["analysis_history"]
        for entry in overview["analysis_history"]:
            assert entry["outdated"] is False
        assert overall["analysis_outdated"] is False

        # --- no hard-coded risk scores / approval language -------------
        for token in FORBIDDEN_TEXT:
            assert token not in blob, token
        # --- no legal-obligation conclusion for biodiversity ------------
        assert "insufficient to determine whether any specific legal obligation" in blob
