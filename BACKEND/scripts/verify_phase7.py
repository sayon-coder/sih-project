"""
Phase 7 end-to-end verification against the *real* configured database.

The pytest suite runs on in-memory SQLite. This script drives the actual
PostgreSQL database through the real HTTP app, proving that migration 006, the
``change_impacts`` table and the Phase 7 routes work together outside of tests.

The simulator is deterministic, so nothing here needs the LLM and nothing needs
corpus retrieval. The script drives the demo scenario's central change -
cultivated -> wild sourcing, a solvent -> cold-press process change and a new
high-risk claim - and checks that each difference is detected, ranked, and
accompanied by review questions.

It creates two temporary users and one product with two versions, and always
deletes everything it created (even on failure).

Usage:
    python scripts/verify_phase7.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "VerifyPhase7!234"

SIGNIFICANCE_ORDER = {"significant": 0, "review_recommended": 1, "informational": 2}

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


def _changes(result, category=None):
    changes = result["changes"]
    if category is not None:
        changes = [c for c in changes if c["category"] == category]
    return changes


def main() -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    owner_email = f"phase7-verify-{stamp}@example.com"
    other_email = f"phase7-verify-other-{stamp}@example.com"

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
        check("change_impacts table exists", "change_impacts" in tables)

        with TestClient(app) as client:
            health = client.get("/api/health").json()
            check(
                "Health endpoint reports phase 7 or later",
                int(health.get("phase", 0)) >= 7,
                str(health),
            )

            # ---------- auth ----------
            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify7-{stamp}",
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
                    "username": f"verify7-other-{stamp}",
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

            # ---------- product + version 1 content ----------
            response = client.post(
                "/api/products", json={"name": f"Phase7 Verify Product {stamp}"}, headers=owner
            )
            check("Create product", response.status_code == 201, str(response.json()))
            product = response.json()["data"]
            product_id = product["id"]
            v1 = product["current_version_id"]
            base1 = f"/api/products/{product_id}/versions/{v1}"

            response = client.post(
                f"{base1}/ingredients",
                json={
                    "common_name": "Ashwagandha",
                    "botanical_name": "Withania somnifera",
                    "plant_part": "root",
                    "quantity": 250,
                    "quantity_unit": "mg",
                    "source_type": "cultivated",
                    "source_location": "Uttarakhand, India",
                },
                headers=owner,
            )
            check("Create v1 ingredient", response.status_code == 201, str(response.json()))

            response = client.put(
                f"{base1}/formulation",
                json={"extraction_method": "solvent extraction", "solvent": "ethanol", "temperature": 60},
                headers=owner,
            )
            check("Set v1 formulation", response.status_code in (200, 201), str(response.json()))

            response = client.post(
                f"{base1}/claims",
                json={"claim_text": "General wellness support", "claim_type": "wellness"},
                headers=owner,
            )
            check("Create v1 claim", response.status_code == 201, str(response.json()))

            response = client.post(
                f"{base1}/target-markets", json={"country": "India"}, headers=owner
            )
            check("Create v1 market", response.status_code == 201, str(response.json()))

            v1_hash = client.get(base1, headers=owner).json()["data"]["content_hash"]

            # ---------- version 2 (copies v1 content, then change it) ----------
            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Cold-press, wild-sourced, new claim"},
                headers=owner,
            )
            check("Create version 2", response.status_code == 201, str(response.json()))
            v2 = response.json()["data"]["id"]
            base2 = f"/api/products/{product_id}/versions/{v2}"

            v2_ingredient = client.get(f"{base2}/ingredients", headers=owner).json()["data"][0]
            response = client.put(
                f"{base2}/ingredients/{v2_ingredient['id']}",
                json={"source_type": "wild", "quantity": 500},
                headers=owner,
            )
            check("Change v2 sourcing and quantity", response.status_code == 200, str(response.json()))

            response = client.put(
                f"{base2}/formulation",
                json={"extraction_method": "cold-press", "solvent": "water", "temperature": 4},
                headers=owner,
            )
            check("Change v2 process", response.status_code in (200, 201), str(response.json()))

            # Remove the inherited claim, add a high-risk one.
            v2_claim = client.get(f"{base2}/claims", headers=owner).json()["data"][0]
            check(
                "Remove inherited v2 claim",
                client.delete(f"{base2}/claims/{v2_claim['id']}", headers=owner).status_code == 200,
            )
            response = client.post(
                f"{base2}/claims",
                json={"claim_text": "Improves sleep onset", "claim_type": "therapeutic"},
                headers=owner,
            )
            check("Add high-risk v2 claim", response.status_code == 201, str(response.json()))
            response = client.post(
                f"{base2}/target-markets", json={"country": "Germany"}, headers=owner
            )
            check("Add a second target market", response.status_code == 201, str(response.json()))

            # ---------- identical versions ----------
            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Copy of v2"},
                headers=owner,
            )
            v3 = response.json()["data"]["id"]
            response = client.post(
                f"/api/products/{product_id}/change-impact",
                json={"old_version_id": v2, "new_version_id": v3},
                headers=owner,
            )
            check("Identical comparison succeeds", response.status_code == 200, str(response.json()))
            identical = response.json()["data"]["results"]
            check("Identical versions report no differences", identical["identical"] is True and identical["change_count"] == 0)

            # ---------- the real comparison ----------
            response = client.post(
                f"/api/products/{product_id}/change-impact",
                json={"old_version_id": v1, "new_version_id": v2},
                headers=owner,
            )
            check("Change-impact run succeeds", response.status_code == 200, str(response.json()))
            created = response.json()["data"]
            result = created["results"]

            check("Result kind is change_impact", result["kind"] == "change_impact")
            check("Run is pinned to both versions", result["old_version_id"] == v1 and result["new_version_id"] == v2)
            check("Both content hashes are recorded", bool(result["old_content_hash"]) and bool(result["new_content_hash"]))
            check("Differences were found", result["change_count"] > 0, str(result["change_count"]))

            categories = set(result["categories_changed"])
            check("Cultivation change detected", "cultivation" in categories, str(sorted(categories)))
            check("Extraction change detected", "extraction" in categories)
            check("Claim change detected", "claims" in categories)
            check("Quantity change detected", "quantities" in categories)
            check("Target-market change detected", "markets" in categories)
            check("Plant-part/patent signal surfaced", "patent_signals" in categories, str(sorted(categories)))

            cultivation = [c for c in _changes(result, "cultivation") if c["field"] == "source_type"]
            check(
                "Cultivated -> wild is significant",
                cultivation
                and cultivation[0]["old_value"] == "cultivated"
                and cultivation[0]["new_value"] == "wild"
                and cultivation[0]["significance"] == "significant",
                str(cultivation),
            )

            extraction = [c for c in _changes(result, "extraction") if c["field"] == "extraction_method"]
            check(
                "solvent extraction -> cold-press is captured",
                extraction
                and extraction[0]["old_value"] == "solvent extraction"
                and extraction[0]["new_value"] == "cold-press",
                str(extraction),
            )

            added_claims = [c for c in _changes(result, "claims") if c["change_type"] == "added"]
            check(
                "A new therapeutic claim is flagged significant",
                any(c["significance"] == "significant" for c in added_claims),
                str(added_claims),
            )

            ranks = [SIGNIFICANCE_ORDER[c["significance"]] for c in result["changes"]]
            check("Differences are ranked by significance", ranks == sorted(ranks))

            check(
                "Expert review is recommended for these changes",
                result["expert_review_recommended"] is True
                and len(result["expert_review_reasons"]) >= 1,
                str(result["expert_review_reasons"]),
            )

            question_categories = {q["category"] for q in result["review_questions"]}
            check(
                "Review questions cover the changed categories",
                {"claims", "extraction", "cultivation"} <= question_categories,
                str(sorted(question_categories)),
            )
            check(
                "Disclosure timing is always surfaced as a question",
                "public_disclosure" in question_categories,
            )

            not_compared = {n["category"] for n in result["not_compared"]}
            check(
                "Uncomparable categories are declared, not hidden",
                {"public_disclosure", "classification"} <= not_compared,
                str(sorted(not_compared)),
            )
            check(
                "Phase 8 disclosure tracking is named explicitly",
                any("Phase 8" in n["reason"] for n in result["not_compared"]),
            )

            check(
                "Disclaimers are attached",
                any("not advice" in w for w in created["warnings"]),
            )

            # ---------- advisory ----------
            v1_after = client.get(base1, headers=owner).json()["data"]["content_hash"]
            check("Comparison did not modify the old version", v1_after == v1_hash)

            # ---------- input validation ----------
            response = client.post(
                f"/api/products/{product_id}/change-impact",
                json={"old_version_id": v1, "new_version_id": v1},
                headers=owner,
            )
            check("Comparing a version with itself is rejected", response.status_code == 422, str(response.status_code))

            response = client.post(
                "/api/products",
                json={"name": f"Phase7 Other Product {stamp}"},
                headers=owner,
            )
            other_product = response.json()["data"]
            response = client.post(
                f"/api/products/{product_id}/change-impact",
                json={"old_version_id": v1, "new_version_id": other_product["current_version_id"]},
                headers=owner,
            )
            check(
                "A version from another product is rejected",
                response.status_code == 404,
                str(response.status_code),
            )
            client.delete(f"/api/products/{other_product['id']}", headers=owner)

            # ---------- retrieval + scoping ----------
            response = client.get(f"/api/products/{product_id}/change-impact", headers=owner)
            check("List runs", response.status_code == 200 and len(response.json()["data"]) >= 2)
            run_id = created["id"]
            check(
                "Fetch one run",
                client.get(f"/api/products/{product_id}/change-impact/{run_id}", headers=owner).status_code
                == 200,
            )
            check(
                "Unknown run is a 404",
                client.get(
                    f"/api/products/{product_id}/change-impact/424242", headers=owner
                ).status_code
                == 404,
            )
            check(
                "Other user cannot read the runs",
                client.get(f"/api/products/{product_id}/change-impact", headers=other).status_code == 404,
            )
            check(
                "Other user cannot run a comparison",
                client.post(
                    f"/api/products/{product_id}/change-impact",
                    json={"old_version_id": v1, "new_version_id": v2},
                    headers=other,
                ).status_code
                == 404,
            )

            # ---------- audit trail ----------
            with engine.connect() as conn:
                audited = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_logs "
                        "WHERE user_id = :uid AND action = 'change_impact'"
                    ),
                    {"uid": owner_id},
                ).scalar()
            check("Change-impact runs are audit-logged", audited >= 2, str(audited))

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
