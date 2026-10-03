"""
Phase 2 end-to-end verification against the *real* configured database.

Unlike the pytest suite (which runs on in-memory SQLite), this script exercises
the actual PostgreSQL database, so it proves that migrations, enum types,
foreign keys and the API work together outside of tests.

It creates two temporary users and one product, drives the whole Phase 2 flow
through the real HTTP app, prints a PASS/FAIL line per check, and always deletes
everything it created (even on failure).

Usage:
    python scripts/verify_phase2.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "VerifyPhase2!234"

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
    # NOTE: must be a normal domain - Pydantic's EmailStr rejects special-use
    # TLDs such as .local or .test.
    owner_email = f"phase2-verify-{stamp}@example.com"
    other_email = f"phase2-verify-other-{stamp}@example.com"

    owner_id = None
    other_id = None
    product_id = None

    try:
        with TestClient(app) as client:
            check("Health endpoint responds", client.get("/api/health").status_code == 200)

            # ---------- auth ----------
            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify-{stamp}",
                    "email": owner_email,
                    "password": PASSWORD,
                    "confirm_password": PASSWORD,
                },
            )
            check("Register owner user", response.status_code == 201, str(response.status_code))
            owner_id = response.json()["data"]["id"]

            response = client.post(
                "/api/auth/register",
                json={
                    "username": f"verify-other-{stamp}",
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

            check(
                "GET /api/auth/me returns the owner",
                client.get("/api/auth/me", headers=owner).json()["data"]["email"]
                == owner_email,
            )

            # ---------- product + passport ----------
            response = client.post(
                "/api/products",
                json={
                    "name": f"Phase2 Verify Ashwagandha {stamp}",
                    "description": "Temporary product created by verify_phase2.py",
                    # API enum values are lowercase (e.g. "proprietary_ayurvedic")
                    "category": "proprietary_ayurvedic",
                },
                headers=owner,
            )
            check("Create product", response.status_code == 201, str(response.json()))
            product = response.json()["data"]
            product_id = product["id"]
            check("Product has an initial version", product["current_version_id"] is not None)

            passport = client.get(f"/api/products/{product_id}/passport", headers=owner)
            check("Get product passport", passport.status_code == 200)
            passport_data = passport.json()["data"]
            check("Passport reports one version", passport_data["version_count"] == 1)
            check(
                "Passport version carries a content hash",
                len(passport_data["current_version"]["content_hash"]) == 64,
                passport_data["current_version"]["content_hash"][:12] + "...",
            )

            check(
                "Product appears in the owner's list",
                any(
                    item["id"] == product_id
                    for item in client.get("/api/products", headers=owner).json()["data"]
                ),
            )

            # ---------- versioning ----------
            versions = client.get(
                f"/api/products/{product_id}/versions", headers=owner
            ).json()["data"]
            check("Version list has version 1", len(versions) == 1 and versions[0]["version_number"] == 1)
            version_1_id = versions[0]["id"]
            version_1_hash = versions[0]["content_hash"]

            response = client.post(
                f"/api/products/{product_id}/versions",
                json={"change_reason": "Verification run: second version"},
                headers=owner,
            )
            check("Create version 2", response.status_code == 201, str(response.json()))
            version_2 = response.json()["data"]
            check("Version 2 is numbered 2", version_2["version_number"] == 2)
            check(
                "Inherited version keeps the same content hash",
                version_2["content_hash"] == version_1_hash,
            )

            response = client.post(
                f"/api/products/{product_id}/versions/{version_1_id}/clone",
                json={"change_reason": "Verification run: clone of version 1"},
                headers=owner,
            )
            check("Clone version 1", response.status_code == 201, str(response.json()))
            clone = response.json()["data"]
            check("Clone preserves the content hash", clone["content_hash"] == version_1_hash)

            check(
                "Current version advanced to the clone",
                client.get(f"/api/products/{product_id}", headers=owner).json()["data"][
                    "current_version_id"
                ]
                == clone["id"],
            )

            response = client.put(
                f"/api/products/{product_id}/versions/{version_2['id']}",
                json={"change_reason": "Verification run: corrected reason"},
                headers=owner,
            )
            check(
                "Update version metadata",
                response.status_code == 200
                and response.json()["data"]["change_reason"]
                == "Verification run: corrected reason",
            )

            detail = client.get(
                f"/api/products/{product_id}/versions/{version_1_id}", headers=owner
            )
            check("Version detail readable", detail.status_code == 200)
            check(
                "Version detail exposes empty-but-real collections",
                detail.json()["data"]["ingredients"] == []
                and detail.json()["data"]["claims"] == [],
            )

            # ---------- authorization boundaries ----------
            check(
                "Other user cannot read the product",
                client.get(f"/api/products/{product_id}", headers=other).status_code == 404,
            )
            check(
                "Other user cannot read the passport",
                client.get(
                    f"/api/products/{product_id}/passport", headers=other
                ).status_code
                == 404,
            )
            check(
                "Other user cannot update the product",
                client.put(
                    f"/api/products/{product_id}",
                    json={"name": "hijacked"},
                    headers=other,
                ).status_code
                == 404,
            )
            check(
                "Other user cannot create a version",
                client.post(
                    f"/api/products/{product_id}/versions",
                    json={"change_reason": "trespass"},
                    headers=other,
                ).status_code
                == 404,
            )
            check(
                "Other user's product list is empty",
                client.get("/api/products", headers=other).json()["data"] == [],
            )

            # ---------- soft delete ----------
            check(
                "Delete product",
                client.delete(f"/api/products/{product_id}", headers=owner).status_code == 200,
            )
            check(
                "Deleted product is no longer readable",
                client.get(f"/api/products/{product_id}", headers=owner).status_code == 404,
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
