"""
Tests for Phase 5: claim-to-evidence analysis and comprehensive product analysis.

The LLM and retrieval layers are mocked so the suite is fast and offline. What
the tests actually protect is the set of guarantees the phase is responsible for:

* the AI cannot promote a claim to ``supported`` / ``expert_verified``;
* the AI cannot cite a chunk it was not given;
* ``EXPERT_VERIFIED`` claims are never re-assessed;
* analysis is advisory - running it does not mutate the underlying content;
* an AI outage is a controlled, recorded failure, not a silent success;
* analyses are scoped to the product version (and owner) that produced them.
"""
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.models import Claim
from app.services.provenance import Provenance


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _product_and_version(client, headers, name="Analysis Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _add_claim(client, headers, pid, vid, text, claim_type="wellness"):
    response = client.post(
        f"{_base(pid, vid)}/claims",
        json={"claim_text": text, "claim_type": claim_type},
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _chunk(chunk_id=1, title="Ashwagandha monograph", text="Withanolides are the principal constituents of Withania somnifera root."):
    from app.rag.schemas import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=7,
        title=title,
        source_type="scientific_paper",
        jurisdiction="IN",
        text=text,
        final_score=0.9,
    )


def _claim_llm_output(assessments=None, summary="Preliminary review of the recorded claims.", warnings=None):
    return json.dumps(
        {
            "assessments": assessments or [],
            "summary": summary,
            "warnings": warnings or [],
        }
    )


def _mock_llm(payload):
    llm = MagicMock()
    llm.generate.return_value = payload
    return llm


@contextmanager
def _patch_claim_analysis(chunks, payload):
    """Patch retrieval + LLM inside the claim analyzer module."""
    with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=chunks), patch(
        "app.analysis.claim_analyzer.get_llm_provider", return_value=_mock_llm(payload)
    ):
        yield


# -------------------------------------------------------
# Authentication / authorization
# -------------------------------------------------------

class TestAnalysisAuthorization:
    def test_requires_authentication(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        assert client.post(f"{_base(pid, vid)}/claims/analyze").status_code == 401
        assert client.post(f"{_base(pid, vid)}/analyze").status_code == 401
        assert client.get(f"{_base(pid, vid)}/analyses").status_code == 401

    def test_another_user_cannot_analyze(self, client, auth_headers, second_user_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Supports immunity")

        assert (
            client.post(f"{_base(pid, vid)}/claims/analyze", headers=second_user_headers).status_code
            == 404
        )
        assert client.get(f"{_base(pid, vid)}/analyses", headers=second_user_headers).status_code == 404

    def test_analysis_from_one_version_is_not_visible_from_another(
        self, client, auth_headers
    ):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Claim on v1")

        with _patch_claim_analysis([], _claim_llm_output([])):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert response.status_code == 200, response.json()
        analysis_id = response.json()["data"]["id"]

        # Create a second version and confirm the v1 analysis is not reachable there.
        second = client.post(
            f"/api/products/{pid}/versions", json={}, headers=auth_headers
        )
        assert second.status_code == 201, second.json()
        vid2 = second.json()["data"]["id"]

        assert (
            client.get(f"{_base(pid, vid2)}/analyses/{analysis_id}", headers=auth_headers).status_code
            == 404
        )


# -------------------------------------------------------
# Claim analysis
# -------------------------------------------------------

class TestClaimAnalysis:
    def test_no_claims_is_a_completed_no_op(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)

        # No LLM at all should be needed when there is nothing to review.
        with patch("app.analysis.claim_analyzer.get_llm_provider", side_effect=AssertionError("LLM must not be called")):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["analysis_type"] == "claim_analysis"
        assert data["status"] == "completed"
        assert data["results"]["claim_count"] == 0
        assert data["results"]["assessments"] == []
        assert any("no claims" in w.lower() for w in data["warnings"])

    def test_analyze_claims_produces_assessment_with_citation(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(
            client, auth_headers, pid, vid, "Supports joint comfort in adults", claim_type="wellness"
        )

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "partially_supported",
                    "risk_level": "low",
                    "rationale": "A monograph in the corpus discusses the botanical's constituents.",
                    "missing_evidence": ["Human trial data for this specific endpoint"],
                    "citation_chunk_ids": [1],
                }
            ]
        )

        with _patch_claim_analysis([_chunk()], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assert response.status_code == 200, response.json()
        result = response.json()["data"]["results"]
        assert result["kind"] == "claim_analysis"
        assert result["claim_count"] == 1

        assessment = result["assessments"][0]
        assert assessment["claim_id"] == claim["id"]
        assert assessment["suggested_evidence_status"] == "partially_supported"
        assert assessment["provenance"] == "AI_ANALYSIS"
        assert assessment["citations"][0]["chunk_id"] == 1
        assert assessment["citations"][0]["source_type"] == "scientific_paper"

    def test_ai_cannot_mark_a_claim_supported(self, client, auth_headers):
        """The firewall: an AI answer claiming 'supported' is clamped down."""
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(client, auth_headers, pid, vid, "Clinically proven to cure diabetes")

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "supported",
                    "risk_level": "high",
                    "rationale": "Model overreached.",
                    "missing_evidence": [],
                    "citation_chunk_ids": [],
                }
            ]
        )

        with _patch_claim_analysis([], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assessment = response.json()["data"]["results"]["assessments"][0]
        assert assessment["suggested_evidence_status"] != "supported"
        assert assessment["suggested_evidence_status"] == "needs_evidence"

    def test_ai_cannot_mark_a_claim_expert_verified(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(client, auth_headers, pid, vid, "Traditional use for stress")

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "expert_verified",
                    "risk_level": "low",
                    "rationale": "Model overreached.",
                    "citation_chunk_ids": [],
                }
            ]
        )

        with _patch_claim_analysis([], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assessment = response.json()["data"]["results"]["assessments"][0]
        assert assessment["suggested_evidence_status"] == "needs_evidence"
        assert assessment["provenance"] == "AI_ANALYSIS"

    def test_uncited_chunk_ids_are_dropped(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(client, auth_headers, pid, vid, "Supports relaxation")

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "partially_supported",
                    "risk_level": "low",
                    "rationale": "See citation.",
                    "missing_evidence": [],
                    # 999 was never retrieved.
                    "citation_chunk_ids": [999],
                }
            ]
        )

        with _patch_claim_analysis([_chunk(chunk_id=1)], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        data = response.json()["data"]
        assessment = data["results"]["assessments"][0]
        assert assessment["citations"] == []
        assert any("did not match the passages" in w for w in data["warnings"])

    def test_expert_verified_claim_is_locked(self, client, auth_headers, db_session):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(
            client, auth_headers, pid, vid, "Immunity claim already reviewed", claim_type="wellness"
        )

        # Promote the claim to EXPERT_VERIFIED as the Phase 9 workflow eventually will.
        row = db_session.get(Claim, claim["id"])
        row.provenance = Provenance.EXPERT_VERIFIED.value
        db_session.commit()

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "needs_evidence",
                    "risk_level": "high",
                    "rationale": "Should never be applied.",
                    "citation_chunk_ids": [],
                }
            ]
        )

        with _patch_claim_analysis([], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assessment = response.json()["data"]["results"]["assessments"][0]
        assert assessment["expert_verified_locked"] is True
        # The model proposed "needs_evidence"; a locked claim must not be touched.
        assert assessment["suggested_evidence_status"] == "user_provided"
        assert assessment["suggested_evidence_status"] != "needs_evidence"
        assert assessment["citations"] == []
        assert "does not assess" in assessment["rationale"]

    def test_analysis_does_not_mutate_claims(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(client, auth_headers, pid, vid, "Supports vitality")

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "partially_supported",
                    "risk_level": "low",
                    "rationale": "Partially supported.",
                    "citation_chunk_ids": [1],
                }
            ]
        )

        with _patch_claim_analysis([_chunk()], payload):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert response.status_code == 200, response.json()

        after = client.get(f"{_base(pid, vid)}/claims", headers=auth_headers).json()["data"][0]
        assert after["evidence_status"] == "user_provided"
        assert after["provenance"] == "USER_PROVIDED"
        assert after["review_status"] == "pending"

    def test_llm_outage_is_a_recorded_controlled_failure(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Some claim")

        with patch(
            "app.analysis.claim_analyzer.get_llm_provider",
            side_effect=RuntimeError("provider unavailable"),
        ):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

        listed = client.get(f"{_base(pid, vid)}/analyses", headers=auth_headers).json()["data"]
        assert len(listed) == 1
        assert listed[0]["status"] == "failed"

    def test_malformed_llm_output_is_a_controlled_failure(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Some claim")

        with _patch_claim_analysis([], "this is not json"):
            response = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        assert response.status_code == 503
        listed = client.get(f"{_base(pid, vid)}/analyses", headers=auth_headers).json()["data"]
        assert listed[0]["status"] == "failed"


# -------------------------------------------------------
# Comprehensive analysis
# -------------------------------------------------------

class TestComprehensiveAnalysis:
    def _classification_payload(self):
        return json.dumps(
            {
                "preliminary_category": "proprietary_ayurvedic",
                "confidence": "medium",
                "rationale": "A non-classical formulation with proprietary claims.",
                "alternative_categories": ["possible_medicinal"],
                "missing_information": ["Intended dose"],
            }
        )

    def test_comprehensive_analysis_orchestrates_components(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(
            client,
            auth_headers,
            pid,
            vid,
            "Clinically proven to cure diabetes",
            claim_type="therapeutic",
        )
        client.post(
            f"{_base(pid, vid)}/target-markets",
            json={"country": "India", "region": "South Asia"},
            headers=auth_headers,
        )
        client.post(
            f"{_base(pid, vid)}/ingredients",
            json={"common_name": "Ashwagandha", "botanical_name": "Withania somnifera"},
            headers=auth_headers,
        )

        claim_payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "needs_evidence",
                    "risk_level": "high",
                    "rationale": "No disease-treatment evidence was found.",
                    "missing_evidence": ["Regulatory evidence for a disease claim"],
                    "citation_chunk_ids": [],
                }
            ]
        )

        with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]), patch(
            "app.analysis.claim_analyzer.get_llm_provider", return_value=_mock_llm(claim_payload)
        ), patch(
            "app.analysis.classifier.get_llm_provider",
            return_value=_mock_llm(self._classification_payload()),
        ):
            response = client.post(f"{_base(pid, vid)}/analyze", headers=auth_headers)

        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        result = data["results"]

        assert data["analysis_type"] == "comprehensive"
        assert result["kind"] == "comprehensive_analysis"
        assert result["product_classification"]["category"] == "proprietary_ayurvedic"
        assert result["product_classification"]["preliminary"] is True
        assert len(result["claim_review"]["assessments"]) == 1
        assert result["market_considerations"][0]["country"] == "India"
        assert any("high-risk claim" in r for r in result["expert_review_recommendations"])
        # Phase 6 stages are now implemented and embedded in the result, so they
        # must no longer be declared as deferred.
        assert not any("Phase 6" in item for item in result["deferred_components"])
        # Phase 8 (disclosure review + reports) is implemented too.
        assert result["deferred_components"] == []
        assert result["ip_route_map"]["kind"] == "ip_route_map"
        assert len(result["ip_route_map"]["routes"]) >= 9
        assert result["patent_signals"]["kind"] == "patent_screening"
        assert result["biodiversity_screening"]["kind"] == "biodiversity_screening"
        assert result["traditional_knowledge_screening"]["kind"] == "tk_screening"
        assert data["recommendations"]

    def test_classification_failure_degrades_without_aborting(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        claim = _add_claim(client, auth_headers, pid, vid, "General wellness claim")

        claim_payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": claim["id"],
                    "suggested_evidence_status": "needs_evidence",
                    "risk_level": "low",
                    "rationale": "No corpus evidence.",
                    "citation_chunk_ids": [],
                }
            ]
        )

        with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]), patch(
            "app.analysis.claim_analyzer.get_llm_provider", return_value=_mock_llm(claim_payload)
        ), patch(
            "app.analysis.classifier.get_llm_provider",
            side_effect=RuntimeError("classifier down"),
        ):
            response = client.post(f"{_base(pid, vid)}/analyze", headers=auth_headers)

        assert response.status_code == 200, response.json()
        result = response.json()["data"]["results"]
        assert result["product_classification"] is None
        assert any("classification could not be produced" in w for w in response.json()["data"]["warnings"])


# -------------------------------------------------------
# Retrieval
# -------------------------------------------------------

class TestAnalysisRetrieval:
    def test_list_and_filter_analyses(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        _add_claim(client, auth_headers, pid, vid, "Some claim")

        payload = _claim_llm_output(
            assessments=[
                {
                    "claim_id": 1,
                    "suggested_evidence_status": "needs_evidence",
                    "risk_level": "low",
                    "rationale": "No evidence.",
                    "citation_chunk_ids": [],
                }
            ]
        )

        with _patch_claim_analysis([], payload):
            client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)

        listed = client.get(f"{_base(pid, vid)}/analyses", headers=auth_headers).json()
        assert listed["success"] is True
        assert len(listed["data"]) == 1

        filtered = client.get(
            f"{_base(pid, vid)}/analyses?analysis_type=claim_analysis", headers=auth_headers
        ).json()
        assert len(filtered["data"]) == 1

        empty = client.get(
            f"{_base(pid, vid)}/analyses?analysis_type=comprehensive", headers=auth_headers
        ).json()
        assert empty["data"] == []

        bad = client.get(
            f"{_base(pid, vid)}/analyses?analysis_type=not_a_type", headers=auth_headers
        )
        assert bad.status_code == 422

    def test_missing_analysis_returns_404(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        assert (
            client.get(f"{_base(pid, vid)}/analyses/424242", headers=auth_headers).status_code == 404
        )
