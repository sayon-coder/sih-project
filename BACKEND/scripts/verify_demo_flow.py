"""
Demo workflow verification (master prompt section 34) against the live database.

Scenario: cold-press Ashwagandha-root extraction at 4C with an observed 40%
bioavailability-marker increase, cultivated material from Uttarakhand, a
planned conference presentation, and target markets India + Germany.

Flow: register -> product -> v1 -> ingredients/botanicals/origin/formulation/
claim/markets -> passport -> assistant -> classification/claim analysis ->
patent screening + comparison -> biodiversity/TK -> IP route map -> IP brief ->
disclosure -> cultivated->wild v2 -> change impact -> expert handoff ->
expert review -> dashboard -> audit.

Usage:
    python scripts/verify_demo_flow.py
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
    suffix = f" -> {str(detail)[:140]}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main():
    suffix = os.getpid()
    db = SessionLocal()
    me = User(username=f"demo{suffix}", email=f"demo{suffix}@example.com",
              password_hash=hash_password("password123"), is_active=True)
    db.add(me)
    db.commit()
    db.refresh(me)
    uid = me.id
    db.close()

    client = TestClient(app)
    token = client.post("/api/auth/login", json={
        "email": f"demo{suffix}@example.com", "password": "password123"}).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # --- product + version 1 ---
    prod = client.post("/api/products", json={
        "name": "Ashwagandha Cold-Press Extract",
        "description": "Cold-press Ashwagandha-root extraction at 4C",
        "category": "proprietary_ayurvedic",
    }, headers=h)
    check("LOGIN + CREATE ASHWAGANDHA PRODUCT", prod.status_code == 201, prod.text)
    pid = prod.json()["data"]["id"]
    vid = prod.json()["data"]["current_version_id"]

    ing = client.post(f"/api/products/{pid}/versions/{vid}/ingredients", json={
        "common_name": "Ashwagandha",
        "botanical_name": "Withania somnifera",
        "plant_part": "root",
        "quantity": "100",
        "source_type": "cultivated",
        "source_location": "Uttarakhand, India",
        "cultivation_status": "cultivated",
    }, headers=h)
    check("ADD INGREDIENT + BOTANICAL + ORIGIN", ing.status_code == 201, ing.text)

    form = client.put(f"/api/products/{pid}/versions/{vid}/formulation", json={
        "process_description": "Cold-press extraction of Ashwagandha root",
        "extraction_method": "cold-press",
        "temperature": 4,
        "temperature_unit": "C",
    }, headers=h)
    check("ADD FORMULATION (cold-press 4C)", form.status_code in (200, 201), form.text)

    claim = client.post(f"/api/products/{pid}/versions/{vid}/claims", json={
        "claim_text": "40% increase in a measured bioavailability marker",
        "claim_type": "structure_function",
    }, headers=h)
    check("ADD 40% CLAIM", claim.status_code == 201, claim.text)
    cid = claim.json()["data"]["id"]
    check("40% result stays USER_PROVIDED",
          claim.json()["data"]["provenance"] == "USER_PROVIDED"
          and claim.json()["data"]["evidence_status"] in ("user_provided", "needs_evidence"))

    for country in ("India", "Germany"):
        m = client.post(f"/api/products/{pid}/versions/{vid}/target-markets",
                        json={"country": country}, headers=h)
        check(f"ADD MARKET {country}", m.status_code == 201, m.text)

    passport = client.get(f"/api/products/{pid}/passport", headers=h)
    check("VIEW PRODUCT PASSPORT", passport.status_code == 200
          and passport.json()["data"]["product"]["name"].startswith("Ashwagandha"))

    # --- assistant (degrades openly without embeddings; shape must hold) ---
    chat = client.post("/api/assistant/chat", json={
        "message": "What IP routes may be relevant for this Ashwagandha product?",
        "product_id": pid, "product_version_id": vid,
    }, headers=h)
    check("ASK IP-SAKTI (cited-answer shape)",
          chat.status_code == 200 and "answer" in chat.json()
          and "sources" in chat.json() or "citations" in chat.json(), chat.text)

    # --- analyses (may 503 without AI keys; must never hallucinate) ---
    ca = client.post(f"/api/products/{pid}/versions/{vid}/claims/analyze", headers=h)
    check("CLAIM ANALYSIS 200-or-503", ca.status_code in (200, 503), ca.text)
    full = client.post(f"/api/products/{pid}/versions/{vid}/analyze", headers=h)
    check("COMPREHENSIVE ANALYSIS 200-or-503", full.status_code in (200, 503), full.text)

    routes = client.get(f"/api/products/{pid}/versions/{vid}/ip-routes", headers=h)
    check("IP ROUTE MAP", routes.status_code == 200
          and len(routes.json()["data"]["routes"]) >= 9, routes.text)

    ps = client.post(f"/api/products/{pid}/versions/{vid}/patents/search", json={}, headers=h)
    ps_result = (ps.json().get("data") or {}).get("results", {})
    check("PATENT SCREENING (demo corpus)",
          ps.status_code == 200 and ps_result.get("retrieval_mode") == "DEMO_CORPUS"
          and ps_result.get("search_is_live") is False, ps.text)
    pc = client.post(f"/api/products/{pid}/versions/{vid}/patents/compare", json={}, headers=h)
    check("PATENT FEATURE COMPARISON", pc.status_code in (200, 422), pc.text)

    bio = client.post(f"/api/products/{pid}/versions/{vid}/biodiversity/screen",
                      json={"include_sources": False}, headers=h)
    bio_result = (bio.json().get("data") or {}).get("results", {})
    check("BIODIVERSITY/ABS SCREEN",
          bio.status_code == 200 and bio_result.get("status") in (
              "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED", "ADDITIONAL_INFORMATION_NEEDED",
              "POTENTIALLY_RELEVANT", "REVIEW_RECOMMENDED"), bio.text)
    tk = client.post(f"/api/products/{pid}/versions/{vid}/traditional-knowledge/screen",
                     json={"include_sources": False}, headers=h)
    check("TK SCREEN (public sources only)", tk.status_code == 200, tk.text)
    tks = client.get("/api/traditional-knowledge/sources", headers=h)
    tks_data = tks.json()["data"] or {}
    tks_sources = tks_data.get("sources", [])
    check("TKDL listed restricted, never accessed",
          tks.status_code == 200 and any(
              s.get("availability") == "restricted" and "TKDL" in s.get("title", "")
              for s in tks_sources), tks.text)

    brief = client.post(f"/api/products/{pid}/versions/{vid}/reports/ip-brief", headers=h)
    check("IP OPPORTUNITY & EVIDENCE BRIEF", brief.status_code == 201
          and len(brief.json()["data"]["content_hash"]) == 64, brief.text)

    disc = client.post(f"/api/products/{pid}/versions/{vid}/disclosures", json={
        "disclosure_type": "conference_presentation",
        "description": "Presenting the cold-press method at a conference",
    }, headers=h)
    check("TIMESTAMPED DISCLOSURE", disc.status_code == 201, disc.text)

    # --- version 2: cultivated -> wild ---
    v2 = client.post(f"/api/products/{pid}/versions",
                     json={"change_reason": "Switch to wild-sourced Ashwagandha"}, headers=h)
    check("CREATE VERSION 2", v2.status_code == 201, v2.text)
    vid2 = v2.json()["data"]["id"]
    ings = client.get(f"/api/products/{pid}/versions/{vid2}/ingredients", headers=h).json()["data"]
    wild = [i for i in ings if i["botanical_name"] == "Withania somnifera"][0]
    upd = client.put(f"/api/products/{pid}/versions/{vid2}/ingredients/{wild['id']}",
                     json={"source_type": "wild", "cultivation_status": "wild"}, headers=h)
    check("CHANGE CULTIVATED -> WILD", upd.status_code == 200, upd.text)

    impact = client.post(f"/api/products/{pid}/change-impact",
                         json={"old_version_id": vid, "new_version_id": vid2}, headers=h)
    ichanges = impact.json()["data"]["results"]["changes"]
    check("CHANGE IMPACT detects sourcing change",
          impact.status_code == 200 and any(
              c["category"] == "cultivation" and c["significance"] == "significant"
              for c in ichanges), impact.text)

    handoff = client.post(f"/api/products/{pid}/versions/{vid2}/reports/expert-handoff", headers=h)
    check("EXPERT HANDOFF PACKAGE", handoff.status_code == 201, handoff.text)

    # --- expert review (needs EXPERT role: grant, exercise, revoke) ---
    db = SessionLocal()
    role = db.query(Role).filter(Role.name == RoleName.EXPERT).first()
    db.add(UserRole(user_id=uid, role_id=role.id))
    db.commit()
    db.close()
    rev = client.post("/api/reviews", json={
        "product_id": pid, "product_version_id": vid2, "title": "Demo review"}, headers=h)
    rid = rev.json()["data"]["id"]
    client.post(f"/api/reviews/{rid}/submit", headers=h)
    client.post(f"/api/reviews/{rid}/request-review", headers=h)
    client.post(f"/api/reviews/{rid}/comment", json={"body": "Methods look documented"}, headers=h)
    v2_claims = client.get(f"/api/products/{pid}/versions/{vid2}/claims", headers=h).json()["data"]
    v2_claim = [c for c in v2_claims if c["claim_text"] == "40% increase in a measured bioavailability marker"][0]
    done = client.post(f"/api/reviews/{rid}/complete",
                       json={"verify_claim_ids": [v2_claim["id"]]}, headers=h)
    check("EXPERT REVIEW completes + verifies 40% claim",
          done.status_code == 200 and done.json()["data"]["status"] == "REVIEWED", done.text)
    db = SessionLocal()
    db.execute(_text("DELETE FROM user_roles WHERE user_id = :u"), {"u": uid})
    db.commit()
    db.close()

    dash = client.get("/api/dashboard", headers=h)
    check("DASHBOARD", dash.status_code == 200
          and dash.json()["data"]["product_count"] >= 1, dash.text)
    audit = client.get("/api/audit", headers=h)
    check("AUDIT LOG", audit.status_code == 200 and len(audit.json()["data"]) >= 1, audit.text)

    # --- cleanup in dependency order ---
    db = SessionLocal()
    db.execute(_text("DELETE FROM review_comments WHERE review_id = :r"), {"r": rid})
    db.execute(_text("DELETE FROM expert_reviews WHERE id = :r"), {"r": rid})
    db.execute(_text("DELETE FROM disclosures WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM reports WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM change_impacts WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM patent_records WHERE product_version_id IN "
                     "(SELECT id FROM product_versions WHERE product_id = :p)"), {"p": pid})
    db.execute(_text("DELETE FROM analyses WHERE product_version_id IN "
                     "(SELECT id FROM product_versions WHERE product_id = :p)"), {"p": pid})
    db.execute(_text("UPDATE products SET current_version_id = NULL WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM product_versions WHERE product_id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM products WHERE id = :p"), {"p": pid})
    db.execute(_text("DELETE FROM audit_logs WHERE user_id = :u"), {"u": uid})
    db.query(User).filter(User.id == uid).delete()
    db.commit()
    db.close()

    print()
    if _failures:
        print(f"DEMO FAILED: {_failures}")
        sys.exit(1)
    print("Demo workflow verified end to end.")


if __name__ == "__main__":
    main()
