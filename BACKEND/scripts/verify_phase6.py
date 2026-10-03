"""
Phase 6 end-to-end verification against the *real* configured database.

The pytest suite runs on in-memory SQLite. This script drives the actual
PostgreSQL database through the real HTTP app, proving that migration 005, the
new tables and the Phase 6 routes work together outside of tests.

The screening logic is deterministic, so nothing here needs the LLM. The only
external dependency is corpus retrieval (used to attach sources to a screening);
it is patched so the script is offline and deterministic, and one check confirms
that a retrieval failure degrades gracefully instead of breaking the screening.

It creates two temporary users, one product and its content, and always deletes
everything it created (even on failure).

Usage:
    python scripts/verify_phase6.py
"""
import datetime
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "VerifyPhase6!234"

ALLOWED_LABELS = {
    "Potentially Relevant",
    "Further Review Recommended",
    "Not Indicated",
    "Insufficient Information",
}
ALLOWED_STATUSES = {
    "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
    "ADDITIONAL_INFORMATION_NEEDED",
    "POTENTIALLY_RELEVANT",
    "REVIEW_RECOMMENDED",
}

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
                text(
                    "DELETE FROM chat_messages WHERE session_id IN "
                    "(SELECT id FROM chat_sessions WHERE user_id = :uid)"
                ),
                {"uid": user_id},
            )
            conn.execute(text("DELETE FROM chat_sessions WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM audit_logs WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    print(f"\nCleaned up temporary users: {user_ids}")


def main() -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    owner_email = f"phase6-verify-{stamp}@example.com"
    other_email = f"phase6-verify-other-{stamp}@example.com"

    owner_id = None
    other_id = None

    try:
        # ---------- migration / schema ----------
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
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
        check("patent_records table exists", "patent_records" in tables)
        check("patent_features table exists", "patent_features" in tables)

        with TestClient(app) as client:
            health = client.get("/api/health").json()
            check(
                "Health endpoint reports phase 6 or later",
                int(health.get("phase", 0)) >= 6,
                str(health),
            )

            # ---------- auth ----------
            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify6-{stamp}",
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
                    "username": f"verify6-other-{stamp}",
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
                "/api/products", json={"name": f"Phase6 Verify Product {stamp}"}, headers=owner
            )
            check("Create product", response.status_code == 201, str(response.json()))
            product = response.json()["data"]
            product_id = product["id"]
            version_id = product["current_version_id"]
            base = f"/api/products/{product_id}/versions/{version_id}"

            response = client.post(
                f"{base}/ingredients",
                json={
                    "common_name": "Ashwagandha",
                    "botanical_name": "Withania somnifera",
                    "sanskrit_name": "Ashwagandha",
                    "plant_part": "root",
                    "source_location": "Uttarakhand, India",
                    "source_type": "cultivated",
                },
                headers=owner,
            )
            check("Create ingredient", response.status_code == 201, str(response.json()))

            response = client.put(
                f"{base}/formulation",
                json={
                    "extraction_method": "cold-press",
                    "solvent": "none",
                    "temperature": 4,
                    "temperature_unit": "C",
                },
                headers=owner,
            )
            check("Set formulation", response.status_code in (200, 201), str(response.json()))

            response = client.post(
                f"{base}/claims",
                json={"claim_text": "Improved bioavailability", "claim_type": "wellness"},
                headers=owner,
            )
            check("Create claim", response.status_code == 201, str(response.json()))

            response = client.post(
                f"{base}/target-markets",
                json={"country": "India", "region": "South Asia"},
                headers=owner,
            )
            check("Create target market", response.status_code == 201, str(response.json()))

            # ---------- IP route map ----------
            response = client.get(f"{base}/ip-routes", headers=owner)
            check("IP route map succeeds", response.status_code == 200, str(response.json()))
            route_map = response.json()["data"]
            check("Route map considers all nine routes", len(route_map["routes"]) == 9, str(len(route_map["routes"])))
            check(
                "Every route label is a careful allowed value",
                all(r["label"] in ALLOWED_LABELS for r in route_map["routes"]),
                str(sorted({r["label"] for r in route_map["routes"]})),
            )
            routes = {r["route"]: r for r in route_map["routes"]}
            check(
                "A recorded process flags the patent route for review",
                routes["patent"]["label"] == "Further Review Recommended",
                routes["patent"]["label"],
            )
            check(
                "Route map carries the disclaimer",
                any("never legally" in w.lower() for w in route_map["warnings"]),
            )

            # ---------- patent screening ----------
            response = client.post(f"{base}/patents/search", headers=owner)
            check("Patent screening succeeds", response.status_code == 200, str(response.json()))
            analysis = response.json()["data"]
            result = analysis["results"]
            check("Analysis type is patent_screening", analysis["analysis_type"] == "patent_screening")
            check("Records are labelled DEMO_CORPUS", result["retrieval_mode"] == "DEMO_CORPUS")
            check("Search is explicitly not live", result["search_is_live"] is False)
            check("At least one candidate record identified", result["record_count"] >= 1, str(result["record_count"]))
            top = result["records"][0]
            check("Top record is the cold-press demo record", top["record_id"] == "DEMO-PAT-0001", top["record_id"])
            check("No real patent number is fabricated", top["patent_number"] is None)
            check("Record is flagged demo", top["is_demo"] is True and top["record_source"] == "DEMO_CORPUS")
            verdicts = {f["verdict"] for f in top["features"]}
            check("Feature comparison has match and unknown verdicts", {"match", "unknown"} <= verdicts, str(verdicts))
            check(
                "Patentability is never asserted",
                any("not determinations of patentability" in w for w in result["warnings"]),
            )
            check(
                "Demo data is declared",
                any("demonstration" in w.lower() for w in result["warnings"]),
            )

            # ---------- list / fetch records ----------
            listed = client.get(f"{base}/patents", headers=owner)
            check("List identified records", listed.status_code == 200 and len(listed.json()["data"]) >= 1)
            record_id = listed.json()["data"][0]["id"]
            check("Fetch one record", client.get(f"/api/patents/{record_id}", headers=owner).status_code == 200)
            check(
                "Other user cannot fetch the record",
                client.get(f"/api/patents/{record_id}", headers=other).status_code == 404,
            )

            # ---------- feature comparison ----------
            response = client.post(
                f"{base}/patents/compare",
                json={"patent_record_ids": [record_id]},
                headers=owner,
            )
            check("Feature comparison succeeds", response.status_code == 200, str(response.json()))
            comparison = response.json()["data"]["results"]
            check("Comparison kind is feature comparison", comparison["kind"] == "patent_feature_comparison")
            check("Comparison covers the selected record", comparison["record_count"] == 1, str(comparison["record_count"]))
            check(
                "Comparison does not create new records",
                len(client.get(f"{base}/patents", headers=owner).json()["data"]) == len(listed.json()["data"]),
            )

            # ---------- biodiversity screening ----------
            with patch("app.analysis.screening.hybrid_retrieve", return_value=[]):
                response = client.post(
                    f"{base}/biodiversity/screen?include_sources=true", headers=owner
                )
            check("Biodiversity screening succeeds", response.status_code == 200, str(response.json()))
            biodiversity = response.json()["data"]
            check("Analysis type is biodiversity_screening", biodiversity["analysis_type"] == "biodiversity_screening")
            bio_result = biodiversity["results"]
            check("Status is one of the allowed values", bio_result["status"] in ALLOWED_STATUSES, bio_result["status"])
            check(
                "A cultivated, originated botanical is potentially relevant",
                bio_result["status"] == "POTENTIALLY_RELEVANT",
                bio_result["status"],
            )
            restricted = [s for s in bio_result["sources"] if s["availability"] == "restricted"]
            check("TKDL is surfaced as restricted", any("TKDL" in s["title"] for s in restricted))
            check(
                "Biodiversity disclaimer is attached",
                any("not an official determination" in w for w in bio_result["warnings"]),
            )

            # ---------- degradation ----------
            with patch(
                "app.analysis.screening.hybrid_retrieve",
                side_effect=RuntimeError("embedding model unavailable"),
            ):
                response = client.post(
                    f"{base}/biodiversity/screen?include_sources=true", headers=owner
                )
            check("Retrieval failure does not fail the screening", response.status_code == 200)
            check(
                "Retrieval failure is reported as a warning",
                any("could not be searched" in w for w in response.json()["data"]["results"]["warnings"]),
            )

            # ---------- traditional knowledge screening ----------
            with patch("app.analysis.screening.hybrid_retrieve", return_value=[]):
                response = client.post(f"{base}/traditional-knowledge/screen", headers=owner)
            check("TK screening succeeds", response.status_code == 200, str(response.json()))
            tk = response.json()["data"]
            check("Analysis type is tk_screening", tk["analysis_type"] == "tk_screening")
            tk_result = tk["results"]
            check("TK status is one of the allowed values", tk_result["status"] in ALLOWED_STATUSES, tk_result["status"])
            check("TK involvement is detected", tk_result["collected"]["tk_involvement"] is True)
            restricted = [s for s in tk_result["sources"] if s["availability"] == "restricted"]
            check("Restricted TK source present", restricted and all(s.get("chunk_id") is None for s in restricted))
            check(
                "Restricted material is never reproduced",
                all(not s.get("url") for s in restricted),
            )

            # ---------- source registry ----------
            response = client.get("/api/traditional-knowledge/sources", headers=owner)
            check("Source registry is reachable", response.status_code == 200, str(response.json()))
            registry = response.json()["data"]
            kinds = {entry["kind"] for entry in registry["sources"]}
            check(
                "Registry separates public, permitted and restricted",
                {"public", "permitted", "restricted"} <= kinds,
                str(sorted(kinds)),
            )

            # ---------- advisory ----------
            stored = client.get(f"{base}/ingredients", headers=owner).json()["data"][0]
            check(
                "Screening never mutates the underlying content",
                stored["provenance"] == "USER_PROVIDED",
                str(stored.get("provenance")),
            )

            # ---------- analysis history / scoping ----------
            listed = client.get(f"{base}/analyses", headers=owner).json()["data"]
            types = {a["analysis_type"] for a in listed}
            check(
                "Phase 6 runs are recorded with their own types",
                {"patent_screening", "biodiversity_screening", "tk_screening"} <= types,
                str(sorted(types)),
            )
            filtered = client.get(f"{base}/analyses?analysis_type=patent_screening", headers=owner).json()["data"]
            check("Filter by patent_screening works", len(filtered) >= 2, str(len(filtered)))
            check(
                "Other user cannot read the analyses",
                client.get(f"{base}/analyses", headers=other).status_code == 404,
            )
            check(
                "Other user cannot run a screening",
                client.post(f"{base}/biodiversity/screen", headers=other).status_code == 404,
            )

            # ---------- version isolation ----------
            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Phase 6 verification: second version"},
                headers=owner,
            )
            check("Create version 2", response.status_code == 201, str(response.json()))
            version_2_id = response.json()["data"]["id"]
            check(
                "v1 patent records are not reachable through v2",
                client.get(f"/api/products/{product_id}/versions/{version_2_id}/patents", headers=owner).json()["data"]
                == [],
            )

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
