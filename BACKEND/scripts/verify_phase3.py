"""
Phase 3 end-to-end verification against the *real* configured database.

The pytest suite runs on in-memory SQLite. This script exercises the actual
PostgreSQL database so it proves migrations, enum types, foreign keys and the
nested content routes work together outside of tests.

It creates two temporary users and one product, drives the whole Phase 3 flow
through the real HTTP app, prints a PASS/FAIL line per check, and always deletes
everything it created (even on failure).

Usage:
    python scripts/verify_phase3.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "VerifyPhase3!234"

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
            conn.execute(
                text("DELETE FROM products WHERE created_by = :uid"), {"uid": user_id}
            )
            conn.execute(
                text("DELETE FROM audit_logs WHERE user_id = :uid"), {"uid": user_id}
            )
            conn.execute(
                text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id}
            )
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    print(f"\nCleaned up temporary users: {user_ids}")


def main() -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    owner_email = f"phase3-verify-{stamp}@example.com"
    other_email = f"phase3-verify-other-{stamp}@example.com"

    owner_id = None
    other_id = None

    try:
        with TestClient(app) as client:
            check("Health endpoint responds", client.get("/api/health").status_code == 200)

            # ---------- auth ----------
            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify3-{stamp}",
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
                    "username": f"verify3-other-{stamp}",
                    "email": other_email,
                    "password": PASSWORD,
                    "confirm_password": PASSWORD,
                },
            )
            check("Register second user", response.status_code == 201)
            other_id = response.json()["data"]["id"]

            token = client.post(
                "/api/auth/login", json={"email": owner_email, "password": PASSWORD}
            ).json()["data"]["access_token"]
            other_token = client.post(
                "/api/auth/login", json={"email": other_email, "password": PASSWORD}
            ).json()["data"]["access_token"]

            owner = {"Authorization": f"Bearer {token}"}
            other = {"Authorization": f"Bearer {other_token}"}

            # ---------- product + version ----------
            response = client.post(
                "/api/products",
                json={"name": f"Phase3 Verify Product {stamp}"},
                headers=owner,
            )
            check("Create product", response.status_code == 201, str(response.json()))
            product = response.json()["data"]
            product_id = product["id"]
            version_id = product["current_version_id"]
            base = f"/api/products/{product_id}/versions/{version_id}"

            def content_hash(pid, vid):
                return client.get(
                    f"/api/products/{pid}/versions/{vid}", headers=owner
                ).json()["data"]["content_hash"]

            baseline_hash = content_hash(product_id, version_id)

            # ---------- ingredients ----------
            response = client.post(
                f"{base}/ingredients",
                json={
                    "common_name": "Ashwagandha",
                    "botanical_name": "Withania somnifera",
                    "plant_part": "root",
                    "quantity": 250.0,
                    "quantity_unit": "mg",
                    "source_type": "cultivated",
                    "source_location": "Madhya Pradesh",
                },
                headers=owner,
            )
            check("Create ingredient", response.status_code == 201, str(response.json()))
            ingredient = response.json()["data"]
            check(
                "Ingredient is USER_PROVIDED",
                ingredient["provenance"] == "USER_PROVIDED",
                ingredient["provenance"],
            )
            check("Ingredient source_type round-trips", ingredient["source_type"] == "cultivated")

            after_add_hash = content_hash(product_id, version_id)
            check("Content hash changes after ingredient add", after_add_hash != baseline_hash)
            check("Content hash is 64 hex chars", len(after_add_hash) == 64)

            response = client.get(f"{base}/ingredients", headers=owner)
            check(
                "List ingredients returns the row",
                response.status_code == 200 and len(response.json()["data"]) == 1,
            )

            response = client.put(
                f"{base}/ingredients/{ingredient['id']}",
                json={"source_type": "wild"},
                headers=owner,
            )
            check(
                "Update ingredient",
                response.status_code == 200 and response.json()["data"]["source_type"] == "wild",
            )
            after_update_hash = content_hash(product_id, version_id)
            check("Content hash changes after ingredient update", after_update_hash != after_add_hash)

            # ---------- formulation ----------
            response = client.get(f"{base}/formulation", headers=owner)
            check(
                "Formulation absent before PUT",
                response.status_code == 200 and response.json()["data"] is None,
            )

            response = client.put(
                f"{base}/formulation",
                json={
                    "process_description": "Cold percolation",
                    "extraction_method": "cold-press",
                    "solvent": "water",
                    "temperature": 40.0,
                    "temperature_unit": "C",
                },
                headers=owner,
            )
            check("Create formulation", response.status_code == 200, str(response.json()))
            formulation_id = response.json()["data"]["id"]

            response = client.put(
                f"{base}/formulation", json={"temperature": 55.0}, headers=owner
            )
            check(
                "Update formulation merges fields",
                response.status_code == 200
                and response.json()["data"]["id"] == formulation_id
                and response.json()["data"]["solvent"] == "water",
            )

            # ---------- claims + firewall ----------
            response = client.post(
                f"{base}/claims",
                json={
                    "claim_text": "Increases bioavailability by 40%",
                    "claim_type": "therapeutic",
                },
                headers=owner,
            )
            check("Create claim", response.status_code == 201, str(response.json()))
            claim = response.json()["data"]
            check("Claim is USER_PROVIDED", claim["provenance"] == "USER_PROVIDED")
            check("Claim evidence_status defaults to user_provided", claim["evidence_status"] == "user_provided")

            response = client.post(
                f"{base}/claims",
                json={"claim_text": "Cures diabetes", "evidence_status": "supported"},
                headers=owner,
            )
            check(
                "User cannot self-declare supported evidence",
                response.status_code == 422,
                str(response.status_code),
            )

            response = client.put(
                f"{base}/claims/{claim['id']}",
                json={"evidence_notes": "Not yet independently verified"},
                headers=owner,
            )
            check("Update claim notes", response.status_code == 200)

            # ---------- evidence ----------
            response = client.post(
                f"{base}/evidence",
                json={
                    "title": "Clinical evaluation of Withania somnifera",
                    "evidence_type": "clinical_trial",
                    "doi": "10.1000/example",
                    "publication_date": "2021-06-15",
                    "language": "en",
                    "authors": "Sharma et al.",
                },
                headers=owner,
            )
            check("Create evidence", response.status_code == 201, str(response.json()))
            evidence = response.json()["data"]
            check(
                "Evidence is USER_PROVIDED and pending",
                evidence["provenance"] == "USER_PROVIDED"
                and evidence["verification_status"] == "pending",
            )
            check(
                "Evidence publication_date lands as a date",
                evidence["publication_date"] == "2021-06-15",
                str(evidence["publication_date"]),
            )

            response = client.get(f"{base}/evidence/{evidence['id']}", headers=owner)
            check("Get single evidence", response.status_code == 200)

            response = client.put(
                f"{base}/evidence/{evidence['id']}",
                json={"verification_status": "verified"},
                headers=owner,
            )
            check(
                "User cannot promote evidence verification",
                response.status_code == 422,
                str(response.status_code),
            )

            # ---------- target markets ----------
            response = client.post(
                f"{base}/target-markets",
                json={"country": "India", "region": "South Asia", "regulatory_status": "planned"},
                headers=owner,
            )
            check("Create target market", response.status_code == 201, str(response.json()))
            market_id = response.json()["data"]["id"]

            response = client.put(
                f"{base}/target-markets/{market_id}",
                json={"regulatory_status": "submitted"},
                headers=owner,
            )
            check(
                "Update target market",
                response.status_code == 200
                and response.json()["data"]["regulatory_status"] == "submitted",
            )

            # ---------- version isolation ----------
            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Verification run: second version"},
                headers=owner,
            )
            check("Create version 2", response.status_code == 201, str(response.json()))
            version_2_id = response.json()["data"]["id"]
            v1_hash_before_v2_edit = content_hash(product_id, version_id)
            check(
                "Inherited version has the same content hash",
                response.json()["data"]["content_hash"] == v1_hash_before_v2_edit,
            )

            client.post(
                f"/api/products/{product_id}/versions/{version_2_id}/ingredients",
                json={"common_name": "Guduchi", "botanical_name": "Tinospora cordifolia"},
                headers=owner,
            )
            check(
                "Editing version 2 does not change version 1 hash",
                content_hash(product_id, version_id) == v1_hash_before_v2_edit,
            )
            check(
                "Version 2 hash differs from version 1",
                content_hash(product_id, version_2_id) != v1_hash_before_v2_edit,
            )

            # ---------- ownership boundaries ----------
            check(
                "Other user cannot list ingredients",
                client.get(f"{base}/ingredients", headers=other).status_code == 404,
            )
            check(
                "Other user cannot add an ingredient",
                client.post(
                    f"{base}/ingredients", json={"common_name": "Stolen"}, headers=other
                ).status_code
                == 404,
            )
            check(
                "Other user cannot read the formulation",
                client.get(f"{base}/formulation", headers=other).status_code == 404,
            )
            check(
                "Other user cannot list claims",
                client.get(f"{base}/claims", headers=other).status_code == 404,
            )
            check(
                "Other user cannot list evidence",
                client.get(f"{base}/evidence", headers=other).status_code == 404,
            )
            check(
                "Other user cannot list target markets",
                client.get(f"{base}/target-markets", headers=other).status_code == 404,
            )

            # ---------- passport carries the content ----------
            passport = client.get(
                f"/api/products/{product_id}/passport", headers=owner
            ).json()["data"]["current_version"]
            check(
                "Passport current version exposes all content collections",
                len(passport["ingredients"]) >= 1
                and passport["formulation"] is not None
                and len(passport["claims"]) == 1
                and len(passport["evidence"]) == 1
                and len(passport["target_markets"]) == 1,
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
