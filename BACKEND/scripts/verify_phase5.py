"""
Phase 5 end-to-end verification against the *real* configured database.

The pytest suite runs on in-memory SQLite. This script drives the actual
PostgreSQL database through the real HTTP app so it proves the migration, the
enum label, the analyses table and the analysis routes work together outside of
tests.

The LLM and retrieval layers are mocked (patched) so the script is offline and
deterministic. What it verifies is the platform's behaviour around the model,
not the model itself:

* the analysis is persisted against the exact version it reviewed;
* an AI answer cannot promote a claim to supported / expert-verified;
* an AI answer cannot cite a passage it was not given;
* running an analysis never mutates the underlying content;
* an AI outage is recorded as a failed run and reported as a controlled error;
* analyses are scoped to the owning user and the correct version.

It creates two temporary users and one product, and always deletes everything it
created (even on failure).

Usage:
    python scripts/verify_phase5.py
"""
import datetime
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.rag.schemas import RetrievedChunk  # noqa: E402

PASSWORD = "VerifyPhase5!234"

_results = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record and print a single verification result."""
    _results.append((label, condition))
    mark = "PASS" if condition else "FAIL"
    suffix = f" -> {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    if not condition:
        raise AssertionError(f"{label}{suffix}")


def cleanup(user_ids):
    """Remove every row this script created (products cascade to their content)."""
    if not user_ids:
        return
    with engine.begin() as conn:
        for user_id in user_ids:
            conn.execute(
                text("UPDATE products SET current_version_id = NULL WHERE created_by = :uid"),
                {"uid": user_id},
            )
            conn.execute(text("DELETE FROM products WHERE created_by = :uid"), {"uid": user_id})
            conn.execute(
                text("DELETE FROM chat_messages WHERE session_id IN "
                     "(SELECT id FROM chat_sessions WHERE user_id = :uid)"),
                {"uid": user_id},
            )
            conn.execute(text("DELETE FROM chat_sessions WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM audit_logs WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    print(f"\nCleaned up temporary users: {user_ids}")


def _chunk(chunk_id=1):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=7,
        title="Withania somnifera review",
        source_type="scientific_paper",
        jurisdiction="IN",
        text="Withanolides are the principal constituents of Withania somnifera root.",
        final_score=0.9,
    )


def _llm(payload: str) -> MagicMock:
    mock = MagicMock()
    mock.generate.return_value = payload
    return mock


def _claim_payload(claim_id: int, status: str, chunk_ids=None) -> str:
    return json.dumps(
        {
            "assessments": [
                {
                    "claim_id": claim_id,
                    "suggested_evidence_status": status,
                    "risk_level": "high",
                    "rationale": "Preliminary review of the available corpus.",
                    "missing_evidence": ["Endpoint-specific human data"],
                    "citation_chunk_ids": chunk_ids or [],
                }
            ],
            "summary": "Preliminary review of the recorded claims.",
            "warnings": [],
        }
    )


def _classification_payload() -> str:
    return json.dumps(
        {
            "preliminary_category": "proprietary_ayurvedic",
            "confidence": "medium",
            "rationale": "A proprietary formulation with its own claims.",
            "alternative_categories": ["possible_medicinal"],
            "missing_information": ["Intended dose"],
        }
    )


def main() -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    owner_email = f"phase5-verify-{stamp}@example.com"
    other_email = f"phase5-verify-other-{stamp}@example.com"

    owner_id = None
    other_id = None
    claim_id = None

    try:
        # ---------- migration / schema ----------
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            labels = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = 'analysistype'"
                    )
                )
            }
        # Read the head from the migration scripts so this check does not rot
        # every time a later phase adds a migration.
        from alembic.config import Config as _AlembicConfig
        from alembic.script import ScriptDirectory as _ScriptDirectory

        _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _cfg = _AlembicConfig(os.path.join(_backend_dir, "alembic.ini"))
        _cfg.set_main_option("script_location", os.path.join(_backend_dir, "alembic"))
        head = _ScriptDirectory.from_config(_cfg).get_current_head()

        check(f"Alembic is at head ({head})", revision == head, str(revision))
        check(
            "CLAIM_ANALYSIS exists in the analysistype enum",
            "CLAIM_ANALYSIS" in labels,
            str(sorted(labels)),
        )

        with TestClient(app) as client:
            health = client.get("/api/health").json()
            check(
                "Health endpoint reports phase 5 or later",
                int(health.get("phase", 0)) >= 5,
                str(health),
            )

            # ---------- auth ----------
            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify5-{stamp}",
                    "email": owner_email,
                    "password": PASSWORD,
                    "confirm_password": PASSWORD,
                },
            )
            check("Register owner user", response.status_code == 201, str(response.json()))
            owner_id = response.json()["data"]["id"]

            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify5-other-{stamp}",
                    "email": other_email,
                    "password": PASSWORD,
                    "confirm_password": PASSWORD,
                },
            )
            check("Register second user", response.status_code == 201)
            other_id = response.json()["data"]["id"]

            owner = {
                "Authorization": "Bearer "
                + client.post(
                    "/api/auth/login", json={"email": owner_email, "password": PASSWORD}
                ).json()["data"]["access_token"]
            }
            other = {
                "Authorization": "Bearer "
                + client.post(
                    "/api/auth/login", json={"email": other_email, "password": PASSWORD}
                ).json()["data"]["access_token"]
            }

            # ---------- product + content ----------
            response = client.post(
                "/api/products",
                json={"name": f"Phase5 Verify Product {stamp}"},
                headers=owner,
            )
            check("Create product", response.status_code == 201, str(response.json()))
            product = response.json()["data"]
            product_id = product["id"]
            version_id = product["current_version_id"]
            base = f"/api/products/{product_id}/versions/{version_id}"

            response = client.post(
                f"{base}/claims",
                json={"claim_text": "Clinically proven to cure diabetes", "claim_type": "therapeutic"},
                headers=owner,
            )
            check("Create claim", response.status_code == 201, str(response.json()))
            claim_id = response.json()["data"]["id"]

            client.post(
                f"{base}/target-markets",
                json={"country": "India", "region": "South Asia"},
                headers=owner,
            )
            client.post(
                f"{base}/ingredients",
                json={"common_name": "Ashwagandha", "botanical_name": "Withania somnifera"},
                headers=owner,
            )

            # ---------- claim analysis ----------
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.analysis.claim_analyzer.get_llm_provider",
                return_value=_llm(_claim_payload(claim_id, "partially_supported", [1])),
            ):
                response = client.post(f"{base}/claims/analyze", headers=owner)

            check("Claim analysis succeeds", response.status_code == 200, str(response.json()))
            analysis = response.json()["data"]
            check("Analysis type is claim_analysis", analysis["analysis_type"] == "claim_analysis")
            check("Analysis status is completed", analysis["status"] == "completed")
            check("Analysis is pinned to the reviewed version", analysis["product_version_id"] == version_id)
            assessment = analysis["results"]["assessments"][0]
            check("Assessment is AI_ANALYSIS provenance", assessment["provenance"] == "AI_ANALYSIS")
            check("Legitimate citation is kept", assessment["citations"][0]["chunk_id"] == 1)
            check(
                "Disclaimer is attached to the run",
                any("not legal" in w or "preliminary" in w for w in analysis["warnings"]),
            )

            analysis_id = analysis["id"]

            # ---------- firewall: AI cannot promote ----------
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.analysis.claim_analyzer.get_llm_provider",
                return_value=_llm(_claim_payload(claim_id, "supported", [1])),
            ):
                response = client.post(f"{base}/claims/analyze", headers=owner)
            promoted = response.json()["data"]["results"]["assessments"][0]["suggested_evidence_status"]
            check("AI cannot suggest 'supported'", promoted != "supported", promoted)

            # ---------- citation validation ----------
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.analysis.claim_analyzer.get_llm_provider",
                return_value=_llm(_claim_payload(claim_id, "partially_supported", [4242])),
            ):
                response = client.post(f"{base}/claims/analyze", headers=owner)
            dropped = response.json()["data"]["results"]["assessments"][0]["citations"]
            check("Unretrieved chunk ids are dropped", dropped == [], str(dropped))

            # ---------- analysis is advisory ----------
            stored = client.get(f"{base}/claims", headers=owner).json()["data"][0]
            check(
                "Running an analysis does not mutate the claim",
                stored["evidence_status"] == "user_provided"
                and stored["provenance"] == "USER_PROVIDED",
                str(stored),
            )

            # ---------- controlled failure ----------
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.analysis.claim_analyzer.get_llm_provider", return_value=_llm("not json at all")
            ):
                response = client.post(f"{base}/claims/analyze", headers=owner)
            check("Malformed AI output returns 503", response.status_code == 503, str(response.status_code))
            listed = client.get(f"{base}/analyses", headers=owner).json()["data"]
            check(
                "Failed run is recorded",
                any(a["status"] == "failed" for a in listed),
                str([a["status"] for a in listed]),
            )

            # ---------- comprehensive analysis ----------
            with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.analysis.claim_analyzer.get_llm_provider",
                return_value=_llm(_claim_payload(claim_id, "needs_evidence", [])),
            ), patch(
                "app.analysis.classifier.get_llm_provider",
                return_value=_llm(_classification_payload()),
            ):
                response = client.post(f"{base}/analyze", headers=owner)

            check("Comprehensive analysis succeeds", response.status_code == 200, str(response.json()))
            comprehensive = response.json()["data"]
            result = comprehensive["results"]
            check("Analysis type is comprehensive", comprehensive["analysis_type"] == "comprehensive")
            check(
                "Preliminary classification is present",
                result["product_classification"]["category"] == "proprietary_ayurvedic",
            )
            check(
                "Classification is flagged preliminary",
                result["product_classification"]["preliminary"] is True,
            )
            check(
                "Phase 6 stages are no longer deferred",
                not any("Phase 6" in item for item in result["deferred_components"])
                and any("Phase 8" in item for item in result["deferred_components"]),
                str(result["deferred_components"]),
            )
            check(
                "Comprehensive analysis embeds the Phase 6 components",
                result.get("ip_route_map", {}).get("kind") == "ip_route_map"
                and result.get("patent_signals", {}).get("kind") == "patent_screening"
                and result.get("biodiversity_screening", {}).get("kind") == "biodiversity_screening"
                and result.get("traditional_knowledge_screening", {}).get("kind") == "tk_screening",
            )
            check(
                "Target-market considerations are produced",
                result["market_considerations"][0]["country"] == "India",
            )
            check(
                "Expert-review recommendations are produced",
                len(result["expert_review_recommendations"]) >= 1,
            )

            # ---------- retrieval + scoping ----------
            filtered = client.get(
                f"{base}/analyses?analysis_type=claim_analysis", headers=owner
            ).json()["data"]
            check("Filter by analysis_type works", len(filtered) >= 2, str(len(filtered)))
            bad = client.get(f"{base}/analyses?analysis_type=nonsense", headers=owner)
            check("Unknown analysis_type is rejected", bad.status_code == 422, str(bad.status_code))

            check(
                "Analysis detail is retrievable",
                client.get(f"{base}/analyses/{analysis_id}", headers=owner).status_code == 200,
            )
            check(
                "Other user cannot read the analysis",
                client.get(f"{base}/analyses/{analysis_id}", headers=other).status_code == 404,
            )
            check(
                "Other user cannot run an analysis",
                client.post(f"{base}/claims/analyze", headers=other).status_code == 404,
            )

            # ---------- version isolation ----------
            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Phase 5 verification: second version"},
                headers=owner,
            )
            check("Create version 2", response.status_code == 201, str(response.json()))
            version_2_id = response.json()["data"]["id"]
            check(
                "v1 analysis is not reachable through v2",
                client.get(
                    f"/api/products/{product_id}/versions/{version_2_id}/analyses/{analysis_id}",
                    headers=owner,
                ).status_code
                == 404,
            )
            check(
                "v2 has no inherited analyses",
                client.get(
                    f"/api/products/{product_id}/versions/{version_2_id}/analyses", headers=owner
                ).json()["data"]
                == [],
            )

            # ---------- assistant provenance ----------
            with patch("app.routers.assistant.hybrid_retrieve", return_value=[_chunk()]), patch(
                "app.routers.assistant.get_llm_provider",
                return_value=_llm(
                    json.dumps(
                        {
                            "answer": "Based on the available evidence, this is preliminary.",
                            "insufficient_evidence": False,
                            "citations": [
                                {
                                    "chunk_id": 1,
                                    "document_id": 7,
                                    "title": "Withania somnifera review",
                                    "source_type": "scientific_paper",
                                    "relevant_text": "Withanolides are the principal constituents.",
                                }
                            ],
                            "warnings": [],
                        }
                    )
                ),
            ):
                response = client.post(
                    "/api/assistant/chat",
                    json={"message": "What is known about Ashwagandha?", "product_id": product_id,
                          "product_version_id": version_id},
                    headers=owner,
                )
            chat = response.json()
            check("Assistant chat succeeds", response.status_code == 200, str(response.status_code))
            check("Chat response echoes product context", chat.get("product_version_id") == version_id)
            check("Chat response reports source provenance", "provenance" in chat)

        print(f"\nAll {len(_results)} checks passed against {engine.url.host}.")
        return 0

    except Exception as exc:  # noqa: BLE001 - report then clean up
        print(f"\nVERIFICATION FAILED: {exc}")
        print(f"({sum(1 for _, ok in _results if ok)}/{len(_results)} checks passed before failing)")
        return 1

    finally:
        cleanup([uid for uid in (owner_id, other_id) if uid])


if __name__ == "__main__":
    sys.exit(main())
