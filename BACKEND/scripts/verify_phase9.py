"""
Verify Phase 9 against the live PostgreSQL database: full review lifecycle,
correction round-trip, expert verification promotion, and role boundaries.

Usage:
    python scripts/verify_phase9.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text as _text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, RoleName, User, UserRole  # noqa: E402
from app.utils import hash_password  # noqa: E402

_failures = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    suffix = f" -> {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main():
    suffix = os.getpid()
    db = SessionLocal()
    req = User(username=f"req9{suffix}", email=f"req9{suffix}@example.com",
               password_hash=hash_password("password123"), is_active=True)
    exp = User(username=f"exp9{suffix}", email=f"exp9{suffix}@example.com",
               password_hash=hash_password("password123"), is_active=True)
    db.add_all([req, exp])
    db.commit()
    role = db.query(Role).filter(Role.name == RoleName.EXPERT).first()
    db.add(UserRole(user_id=exp.id, role_id=role.id))
    db.commit()
    req_id, exp_id = req.id, exp.id
    db.close()

    client = TestClient(app)
    t_req = client.post("/api/auth/login", json={
        "email": f"req9{suffix}@example.com", "password": "password123"}).json()["data"]["access_token"]
    t_exp = client.post("/api/auth/login", json={
        "email": f"exp9{suffix}@example.com", "password": "password123"}).json()["data"]["access_token"]
    h_req = {"Authorization": f"Bearer {t_req}"}
    h_exp = {"Authorization": f"Bearer {t_exp}"}

    prod = client.post("/api/products", json={"name": "Phase9 Live"}, headers=h_req).json()["data"]
    pid, vid = prod["id"], prod["current_version_id"]
    claim = client.post(f"/api/products/{pid}/versions/{vid}/claims",
                        json={"claim_text": "Live claim", "claim_type": "wellness"},
                        headers=h_req).json()["data"]

    review = client.post("/api/reviews", json={
        "product_id": pid, "product_version_id": vid, "title": "Live review"},
        headers=h_req)
    check("review created as DRAFT", review.status_code == 201
          and review.json()["data"]["status"] == "DRAFT", review.text[:120])
    rid = review.json()["data"]["id"]

    s1 = client.post(f"/api/reviews/{rid}/submit", headers=h_req).json()["data"]
    check("submit runs AI screen", s1["status"] == "AI_SCREENED" and bool(s1["ai_screen_summary"]))
    s2 = client.post(f"/api/reviews/{rid}/request-review", headers=h_req).json()["data"]
    check("review requested", s2["status"] == "REVIEW_REQUIRED")
    s3 = client.post(f"/api/reviews/{rid}/comment", json={"body": "On it"}, headers=h_exp).json()["data"]
    check("expert comment opens EXPERT_REVIEW", s3["status"] == "EXPERT_REVIEW")
    s4 = client.post(f"/api/reviews/{rid}/request-correction", json={"note": "Fix notes"},
                     headers=h_exp).json()["data"]
    check("correction requested", s4["status"] == "CORRECTION_REQUESTED")
    s5 = client.post(f"/api/reviews/{rid}/resubmit", json={"note": "Fixed"}, headers=h_req).json()["data"]
    check("resubmitted", s5["status"] == "RESUBMITTED")
    s6 = client.post(f"/api/reviews/{rid}/complete", json={"verify_claim_ids": [claim["id"]]},
                     headers=h_exp)
    check("completed", s6.status_code == 200
          and s6.json()["data"]["status"] == "REVIEWED", s6.text[:160])
    claims = client.get(f"/api/products/{pid}/versions/{vid}/claims", headers=h_req).json()["data"]
    promoted = [c for c in claims if c["id"] == claim["id"]][0]
    check("claim promoted to EXPERT_VERIFIED", promoted["provenance"] == "EXPERT_VERIFIED",
          str(promoted))
    s7 = client.post(f"/api/reviews/{rid}/archive", headers=h_exp).json()["data"]
    check("archived", s7["status"] == "ARCHIVED")

    # Cleanup in dependency order.
    db = SessionLocal()
    db.execute(_text("DELETE FROM review_comments WHERE review_id = :r"), {"r": rid})
    db.execute(_text("DELETE FROM expert_reviews WHERE id = :r"), {"r": rid})
    db.execute(_text("UPDATE products SET current_version_id = NULL WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM claims WHERE product_version_id = :v"), {"v": vid})
    db.execute(_text("DELETE FROM product_versions WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM products WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM audit_logs WHERE user_id IN (:a, :b)"), {"a": req_id, "b": exp_id})
    db.execute(_text("DELETE FROM user_roles WHERE user_id IN (:a, :b)"), {"a": req_id, "b": exp_id})
    db.query(User).filter(User.id.in_([req_id, exp_id])).delete(synchronize_session=False)
    db.commit()
    db.close()

    print()
    if _failures:
        print(f"VERIFICATION FAILED: {_failures}")
        sys.exit(1)
    print("Phase 9 live verification passed.")


if __name__ == "__main__":
    main()
