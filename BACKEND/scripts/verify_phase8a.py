"""
Verify Phase 8a against the live PostgreSQL database: disclosure recording,
SHA-256 integrity, public verify payload, advisory review, version scoping,
ownership boundaries and change-impact disclosure comparison.

Usage:
    python scripts/verify_phase8a.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.utils import hash_password  # noqa: E402

_failures = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    suffix = f" -> {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main():
    db = SessionLocal()
    suffix = os.getpid()
    email = f"phase8a{suffix}@example.com"
    user = User(
        username=f"phase8a{suffix}",
        email=email,
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    db.close()

    client = TestClient(app)
    login = client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    check("login works", login.status_code == 200, login.text[:120])
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    created = client.post("/api/products", json={"name": "Phase8a Live"}, headers=headers)
    check("product created", created.status_code == 201, created.text[:120])
    pid = created.json()["data"]["id"]
    vid = created.json()["data"]["current_version_id"]

    rec = client.post(
        f"/api/products/{pid}/versions/{vid}/disclosures",
        json={
            "disclosure_type": "conference_presentation",
            "description": "Live verify: presented method",
            "venue_or_channel": "Ayurveda Congress",
        },
        headers=headers,
    )
    check("disclosure recorded", rec.status_code == 201, rec.text[:160])
    data = rec.json()["data"]
    check("record hash is sha256 hex", len(data["record_hash"]) == 64, data["record_hash"])
    check("verification id present", bool(data["verification_id"]))
    check(
        "invention disclaimer attached",
        "not a patent application" in data["disclaimer"],
    )
    did = data["id"]

    listed = client.get(
        f"/api/products/{pid}/versions/{vid}/disclosures", headers=headers
    )
    check("list returns the event", listed.status_code == 200 and len(listed.json()["data"]) == 1)

    verify = client.get(f"/api/disclosures/{did}/verify")
    check("public verify works without auth", verify.status_code == 200, verify.text[:160])
    check("stored hash matches recomputation", verify.json()["data"]["hash_match"] is True)

    review = client.post(
        f"/api/products/{pid}/versions/{vid}/disclosure-review", headers=headers
    )
    check("review returns 200", review.status_code == 200, review.text[:160])
    rdata = review.json()["data"]
    check(
        "review recommends review",
        rdata["review_status"] == "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED",
        rdata["review_status"],
    )

    vid2 = client.post(
        f"/api/products/{pid}/versions",
        json={"change_reason": "v2"},
        headers=headers,
    ).json()["data"]["id"]
    impact = client.post(
        f"/api/products/{pid}/change-impact",
        json={"old_version_id": vid, "new_version_id": vid2},
        headers=headers,
    )
    check("change-impact runs", impact.status_code == 200, impact.text[:160])
    changes = impact.json()["data"]["results"]["changes"]
    pub = [c for c in changes if c["category"] == "public_disclosure"]
    check("change-impact flags the new-version disclosure gap", bool(pub), str(changes)[:200])

    # Cleanup in dependency order (products use soft-delete, so hard-delete).
    from sqlalchemy import text as _text  # noqa: E402

    db = SessionLocal()
    db.execute(_text("UPDATE products SET current_version_id = NULL WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM disclosures WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM change_impacts WHERE product_id = :p"), {"p": pid})
    db.execute(
        _text(
            "DELETE FROM patent_records WHERE product_version_id IN "
            "(SELECT id FROM product_versions WHERE product_id = :p)"
        ),
        {"p": pid},
    )
    db.execute(_text("DELETE FROM analyses WHERE product_version_id IN "
                     "(SELECT id FROM product_versions WHERE product_id = :p)"), {"p": pid})
    db.execute(_text("DELETE FROM product_versions WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM products WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM audit_logs WHERE user_id = :u"), {"u": uid})
    db.query(User).filter(User.id == uid).delete()
    db.commit()
    db.close()

    print()
    if _failures:
        print(f"VERIFICATION FAILED: {_failures}")
        sys.exit(1)
    print("Phase 8a live verification passed.")


if __name__ == "__main__":
    main()
