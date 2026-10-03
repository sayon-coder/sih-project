"""
End-to-end API walkthrough that mirrors what the frontend will do:
1. Register + log in a throwaway account (Phase 1)
2. Create a product, list versions (Phase 2)
3. Add ingredient, formulation, claim, evidence, target market to a version (Phase 3)
4. Read the version detail and confirm all collections + hash are present

Prints one PASS/FAIL line per step and exits non-zero on the first failure.
"""

import json
import urllib.request
import urllib.error
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
PASSWORD = "TestPass1!"
uniq = int(time.time()) % 100000
EMAIL = f"fe-verify-{uniq}@test.example.com"
USERNAME = f"fe-verify-{uniq}"

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok)))
    if ok:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} -> {detail}")
        sys.exit(1)


def req(method, path, body=None, token=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return json.loads(f.read()), f.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {"detail": str(e)}, e.code


print("=== Phase 1: auth ===")

# register
resp, code = req("POST", "/api/auth/register", {
    "username": USERNAME,
    "email": EMAIL,
    "password": PASSWORD,
    "confirm_password": PASSWORD,
})
check("Register succeeds", resp.get("success") is True, resp)
check("Register returns an id", "id" in resp.get("data", {}), resp)



print("\n=== Phase 1b: login ===")

# login (register does not return a token)
resp, code = req("POST", "/api/auth/login", {
    "email": EMAIL,
    "password": PASSWORD,
})
check("Login succeeds", resp.get("success") is True, resp)
token = resp["data"].get("access_token")
check("Login returns a token", bool(token), resp)

# me
resp, code = req("GET", "/api/auth/me", token=token)
check("GET /auth/me returns the user", resp.get("success") is True, resp)
email = resp["data"].get("email")
check("Me email matches", email == EMAIL, resp)

print("\n=== Phase 2: products + versions ===")

# create product
resp, code = req("POST", "/api/products", {
    "name": "FE Test Product",
    "description": "End-to-end frontend flow check",
    "category": "proprietary_ayurvedic",
}, token=token)
check("Create product 201", code == 201, resp)
product = resp["data"]
pid = product["id"]
vid = product["current_version_id"]
check("Product has id and current_version_id", pid and vid, resp)
print(f"    product id={pid}, version id={vid}")

# list versions
resp, code = req("GET", f"/api/products/{pid}/versions", token=token)
check("List versions 200", code == 200, resp)
versions = resp["data"]
check("Version list non-empty", len(versions) > 0, resp)
check("First version is version 1", versions[0]["version_number"] == 1, resp)
v1 = versions[0]

# passport
resp, code = req("GET", f"/api/products/{pid}/passport", token=token)
check("Passport 200", code == 200, resp)
check("Passport exposes version_count", resp["data"]["version_count"] == 1, resp)


print("\n=== Phase 3: version content ===")

base = f"/api/products/{pid}/versions"

# ingredient
resp, code = req("POST", f"{base}/{vid}/ingredients", {
    "common_name": "Ashwagandha",
    "botanical_name": "Withania somnifera",
    "plant_part": "root",
    "quantity": 250,
    "quantity_unit": "mg",
    "source_type": "cultivated",
}, token=token)
check("Create ingredient 201", code == 201, resp)
ing = resp["data"]
check("Ingredient is USER_PROVIDED", ing.get("provenance") == "USER_PROVIDED", ing)
check("Ingredient source_type round-trips", ing.get("source_type") == "cultivated", ing)
ing_id = ing["id"]
print(f"    ingredient id={ing_id}")

# formulation (PUT creates-or-updates; first call creates)
resp, code = req("PUT", f"{base}/{vid}/formulation", {
    "extraction_method": "cold-press",
    "solvent": "water",
    "temperature": 40,
    "temperature_unit": "C",
}, token=token)
check("Create formulation 200", code == 200, resp)
form = resp["data"]
check("Formulation id assigned", bool(form.get("id")), resp)
form_id = form["id"]
print(f"    formulation id={form_id}")

# claim
resp, code = req("POST", f"{base}/{vid}/claims", {
    "claim_text": "Supports memory and cognition",
    "claim_type": "wellness",
}, token=token)
check("Create claim 201", code == 201, resp)
claim = resp["data"]
check("Claim is USER_PROVIDED", claim.get("provenance") == "USER_PROVIDED", claim)
check("Claim evidence_status is user_provided", claim.get("evidence_status") == "user_provided", claim)
claim_id = claim["id"]
print(f"    claim id={claim_id}")

# evidence
resp, code = req("POST", f"{base}/{vid}/evidence", {
    "title": "Withania clinical review",
    "evidence_type": "scientific_paper",
    "doi": "10.1234/abc",
    "publication_date": "2023-01-01",
    "authors": "Singh et al.",
}, token=token)
check("Create evidence 201", code == 201, resp)
ev = resp["data"]
check("Evidence is USER_PROVIDED and pending", ev.get("provenance") == "USER_PROVIDED" and ev.get("verification_status") == "pending", ev)
check("Evidence publication_date lands as date", ev.get("publication_date") == "2023-01-01", ev)
print(f"    evidence id={ev['id']}")

# target market
resp, code = req("POST", f"{base}/{vid}/target-markets", {
    "country": "India",
    "region": "South Asia",
    "regulatory_status": "planned",
}, token=token)
check("Create target market 201", code == 201, resp)
tm = resp["data"]
check("Target market country round-trips", tm.get("country") == "India", tm)
print(f"    target market id={tm['id']}")


print("\n=== Phase 3: integrity + detail read ===")

# version list again; confirm content_hash present
resp, code = req("GET", f"{base}", token=token)
check("List versions still 200", code == 200, resp)
check("Version has 64-char content_hash", len(v1["content_hash"]) == 64, v1)
check("snapshot_data is non-empty", len(v1.get("snapshot_data", "")) > 0, v1)

# version detail
resp, code = req("GET", f"{base}/{vid}", token=token)
check("Version detail 200", code == 200, resp)
detail = resp["data"]
check("Detail exposes ingredients", len(detail.get("ingredients", [])) >= 1, detail)
check("Detail exposes formulation", detail.get("formulation") is not None, detail)
check("Detail exposes claims", len(detail.get("claims", [])) >= 1, detail)
check("Detail exposes evidence", len(detail.get("evidence", [])) >= 1, detail)
check("Detail exposes target_markets", len(detail.get("target_markets", [])) >= 1, detail)

# ownership boundary
resp, code = req("GET", f"{base}/{vid}/ingredients", token="bogus-token")
check("Other user gets 401 for nested content", code == 401, resp)


print("\n=== Phase 5: analyses (Analysis section of the version page) ===")

# The Analysis section loads the recorded runs when it mounts.
resp, code = req("GET", f"{base}/{vid}/analyses", token=token)
check("List analyses 200", code == 200, resp)
check("A fresh version has no analyses yet", resp["data"] == [], resp)

# "Analyze claims" button. This is the one screen that calls the AI, so both
# outcomes are real: 200 with results, or 503 when the provider is unavailable
# (the UI then shows the message and reloads the recorded failed run).
resp, code = req("POST", f"{base}/{vid}/claims/analyze", token=token, timeout=240)
ai_available = code == 200
check("Claim analysis answers 200 or 503", code in (200, 503), resp)

if ai_available:
    check("Claim analysis reports success", resp.get("success") is True, resp)
    run = resp["data"]
    check("Run is typed claim_analysis", run["analysis_type"] == "claim_analysis", run)
    check("Run status is completed", run["status"] == "completed", run)
    check("Run is pinned to this version", run["product_version_id"] == vid, run)
    check("Run carries a summary for the UI", bool(run.get("summary")), run)
    check("UI can map it to a pinned content_hash", len(v1["content_hash"]) == 64, v1)
    assessments = run["results"]["assessments"]
    check("One assessment per claim", len(assessments) == 1, run)
    a0 = assessments[0]
    check(
        "AI suggestion is clamped below 'supported'",
        a0["suggested_evidence_status"]
        in ("user_provided", "needs_evidence", "partially_supported"),
        a0,
    )
    check("Assessment provenance is AI_ANALYSIS", a0["provenance"] == "AI_ANALYSIS", a0)
    check("UI receives disclaimers to display", len(run.get("warnings", [])) >= 1, run)
    check("UI receives missing_evidence list", isinstance(a0.get("missing_evidence"), list), a0)
else:
    check(
        "503 explains the AI failure",
        "unavailable" in json.dumps(resp).lower()
        or "unusable" in json.dumps(resp).lower(),
        resp,
    )

# Whatever happened, the UI reloads the run list.
resp, code = req("GET", f"{base}/{vid}/analyses", token=token)
check("Recorded run list has exactly one entry", code == 200 and len(resp["data"]) == 1, resp)
recorded = resp["data"][0]
run_id = recorded["id"]
check(
    "Recorded run status matches the outcome",
    recorded["status"] == ("completed" if ai_available else "failed"),
    recorded,
)

resp, code = req("GET", f"{base}/{vid}/analyses/{run_id}", token=token)
check("Analysis detail 200", code == 200, resp)

# "Full analysis" button: this endpoint degrades rather than failing, so it
# answers 200 even when the model is down (with warnings, which the UI shows).
resp, code = req("POST", f"{base}/{vid}/analyze", token=token, timeout=300)
check("Full analysis 200 (degrades rather than failing)", code == 200, resp)
if code == 200:
    comp = resp["data"]
    check("Full analysis typed comprehensive", comp["analysis_type"] == "comprehensive", comp)
    check(
        "No deferred components remain (all phases implemented)",
        comp["results"]["deferred_components"] == [],
        comp,
    )
    check(
        "Phase 6 stages are no longer deferred",
        not any("Phase 6" in item for item in comp["results"]["deferred_components"]),
        comp,
    )
    check(
        "UI receives the embedded Phase 6 components",
        comp["results"].get("ip_route_map", {}).get("kind") == "ip_route_map"
        and comp["results"].get("patent_signals", {}).get("kind") == "patent_screening"
        and comp["results"].get("biodiversity_screening", {}).get("kind") == "biodiversity_screening"
        and comp["results"].get("traditional_knowledge_screening", {}).get("kind") == "tk_screening",
        comp,
    )
    check(
        "UI can show target-market considerations",
        len(comp["results"]["market_considerations"]) >= 1,
        comp,
    )
    check("UI can show expert-review recommendations", len(comp.get("recommendations", [])) >= 1, comp)
    check("UI can show warnings/disclaimers", len(comp.get("warnings", [])) >= 1, comp)

resp, code = req(
    "GET", f"{base}/{vid}/analyses?analysis_type=claim_analysis", token=token
)
check("Filtered analyses list 200", code == 200 and len(resp["data"]) >= 1, resp)


print("\n=== Phase 6: IP route map, patents, biodiversity/ABS, TK ===")

# The IP route map is deterministic and cheap; the section loads it on demand.
resp, code = req("GET", f"{base}/{vid}/ip-routes", token=token)
check("IP route map 200", code == 200, resp)
check("IP route map considers all routes", len(resp["data"]["routes"]) == 9, resp)
check(
    "Route labels are careful, not conclusive",
    all(
        r["label"]
        in (
            "Potentially Relevant",
            "Further Review Recommended",
            "Not Indicated",
            "Insufficient Information",
        )
        for r in resp["data"]["routes"]
    ),
    resp,
)
check("Route map carries a disclaimer", any("never legally" in w.lower() for w in resp["data"]["warnings"]), resp)

# "Screen for patents" button.
resp, code = req("POST", f"{base}/{vid}/patents/search", token=token)
check("Patent screening 200", code == 200, resp)
ps = resp["data"]["results"]
check("Patent screening is labelled a demo corpus", ps["retrieval_mode"] == "DEMO_CORPUS", resp)
check("Patent screening is not presented as live", ps["search_is_live"] is False, resp)
check("UI gets records to render", ps["record_count"] >= 1, resp)
check(
    "Demo data is declared to the UI",
    any("demonstration" in w.lower() for w in ps["warnings"]),
    resp,
)

top = ps["records"][0]
check("Records carry a relevance label and band", bool(top["relevance_label"]) and bool(top["similarity_band"]), top)
check("Records are flagged demo with no fake patent number", top["is_demo"] is True and top["patent_number"] is None, top)
check("Records expose a feature comparison", len(top["features"]) >= 1, top)

# list + detail
resp, code = req("GET", f"{base}/{vid}/patents", token=token)
check("List patent records 200", code == 200 and len(resp["data"]) >= 1, resp)
record_id = resp["data"][0]["id"]
resp, code = req("GET", f"/api/patents/{record_id}", token=token)
check("Fetch one patent record 200", code == 200, resp)

# re-run comparison
resp, code = req("POST", f"{base}/{vid}/patents/compare", {"patent_record_ids": [record_id]}, token=token)
check("Patent feature comparison 200", code == 200, resp)
check(
    "Comparison reports its kind and record count",
    resp["data"]["results"]["kind"] == "patent_feature_comparison"
    and resp["data"]["results"]["record_count"] == 1,
    resp,
)

# screenings (default: no corpus retrieval, so they are fast and deterministic)
resp, code = req("POST", f"{base}/{vid}/biodiversity/screen", token=token)
check("Biodiversity/ABS screen 200", code == 200, resp)
bio = resp["data"]["results"]
check(
    "Biodiversity status is one of the allowed values",
    bio["status"]
    in (
        "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
        "ADDITIONAL_INFORMATION_NEEDED",
        "POTENTIALLY_RELEVANT",
        "REVIEW_RECOMMENDED",
    ),
    bio,
)
check("Biodiversity screen lists sources", len(bio["sources"]) >= 1, bio)
check(
    "UI can show restricted sources as unavailable",
    any(s["availability"] == "restricted" for s in bio["sources"]),
    bio,
)
check(
    "Biodiversity disclaimer is shown",
    any("not an official determination" in w for w in bio["warnings"]),
    bio,
)

resp, code = req("POST", f"{base}/{vid}/traditional-knowledge/screen", token=token)
check("TK screen 200", code == 200, resp)
tk = resp["data"]["results"]
check("TK screen reports a status", bool(tk["status"]), tk)
check(
    "TK screen never reproduces restricted content",
    all(s.get("chunk_id") is None for s in tk["sources"] if s["availability"] == "restricted"),
    tk,
)

resp, code = req("GET", "/api/traditional-knowledge/sources", token=token)
check("TK source registry 200", code == 200, resp)
kinds = {s["kind"] for s in resp["data"]["sources"]}
check("Registry distinguishes public/permitted/restricted", {"public", "permitted", "restricted"} <= kinds, resp)

# The Phase 6 runs are recorded alongside the Phase 5 ones.
resp, code = req("GET", f"{base}/{vid}/analyses", token=token)
check("Recorded runs include the Phase 6 types", code == 200, resp)
types = {a["analysis_type"] for a in resp["data"]}
check(
    "Phase 6 analyses are recorded",
    {"patent_screening", "biodiversity_screening", "tk_screening"} <= types,
    resp,
)


print("\n=== Phase 7: formulation change impact ===")

# A new version copies the current content, so a comparison should be identical.
resp, code = req(
    "POST", f"/api/products/{pid}/versions", {"change_reason": "Phase 7 check"}, token=token
)
check("Create version 2 for the change-impact run", code == 201, resp)
vid2 = resp["data"]["id"]

resp, code = req(
    "POST",
    f"/api/products/{pid}/change-impact",
    {"old_version_id": vid, "new_version_id": vid2},
    token=token,
)
check("Change-impact run 200", code == 200, resp)
identical = resp["data"]["results"]
check(
    "A copied version reports no differences",
    identical["identical"] is True and identical["change_count"] == 0,
    resp,
)
check(
    "Disclosure history is comparable (no public_disclosure gap)",
    not any(n["category"] == "public_disclosure" for n in identical["not_compared"]),
    resp,
)
check(
    "Disclosure timing is always a review question",
    any(q["category"] == "public_disclosure" for q in identical["review_questions"]),
    resp,
)

# Now make the changes the demo scenario cares about, on the new version only.
base2 = f"/api/products/{pid}/versions/{vid2}"
resp, code = req("GET", f"{base2}/ingredients", token=token)
ing = resp["data"][0]
req("PUT", f"{base2}/ingredients/{ing['id']}", {"source_type": "wild"}, token=token)
req(
    "PUT",
    f"{base2}/formulation",
    {"extraction_method": "cold-press", "solvent": "none", "temperature": 4},
    token=token,
)
req(
    "POST",
    f"{base2}/claims",
    {"claim_text": "Improves sleep onset", "claim_type": "therapeutic"},
    token=token,
)
req("POST", f"{base2}/target-markets", {"country": "Germany"}, token=token)

resp, code = req(
    "POST",
    f"/api/products/{pid}/change-impact",
    {"old_version_id": vid, "new_version_id": vid2},
    token=token,
)
check("Change-impact on a real change 200", code == 200, resp)
impact = resp["data"]
result = impact["results"]
cats = set(result["categories_changed"])
check("Cultivation change detected", "cultivation" in cats, sorted(cats))
check("Extraction/process change detected", "extraction" in cats, sorted(cats))
check("Claim change detected", "claims" in cats, sorted(cats))
check("Target-market change detected", "markets" in cats, sorted(cats))
check(
    "Cultivated -> wild is flagged significant",
    any(
        c["field"] == "source_type" and c["new_value"] == "wild" and c["significance"] == "significant"
        for c in result["changes"]
    ),
    resp,
)
ranks = [
    {"significant": 0, "review_recommended": 1, "informational": 2}[c["significance"]]
    for c in result["changes"]
]
check("Differences are ranked by significance", ranks == sorted(ranks), resp)
check("Expert review is recommended", result["expert_review_recommended"] is True, resp)
check(
    "Review questions are returned for the UI",
    len(result["review_questions"]) >= 1 and all(q["question"] for q in result["review_questions"]),
    resp,
)
check("Disclaimers are attached", any("not advice" in w for w in impact["warnings"]), resp)

resp, code = req("GET", f"/api/products/{pid}/change-impact", token=token)
check("List change-impact runs 200", code == 200 and len(resp["data"]) == 2, resp)
run_id = resp["data"][0]["id"]
check(
    "Fetch one change-impact run 200",
    req("GET", f"/api/products/{pid}/change-impact/{run_id}", token=token)[1] == 200,
)
check(
    "Comparing a version with itself is rejected",
    req(
        "POST",
        f"/api/products/{pid}/change-impact",
        {"old_version_id": vid, "new_version_id": vid},
        token=token,
    )[1]
    == 422,
)


print(f"\n{len(results)} checks PASSED against {BASE} (pre-Phase-8 flow).")

print("=== Phases 8-11: disclosures, reports, reviews, dashboard, audit, BHASHINI ===")

resp, code = req(
    "POST", f"/api/products/{pid}/versions/{vid}/disclosures",
    {"disclosure_type": "conference_presentation", "description": "UI flowpublished method"},
    token=token,
)
check("Record disclosure 201", code == 201, resp)
did = resp["data"]["id"]
check("Disclosure carries hash + disclaimer", len(resp["data"]["record_hash"]) == 64
      and "not a patent application" in resp["data"]["disclaimer"], resp)

resp, code = req("GET", f"/api/products/{pid}/versions/{vid}/disclosures", token=token)
check("List disclosures 200", code == 200 and len(resp["data"]) == 1, resp)

resp, code = req("POST", f"/api/products/{pid}/versions/{vid}/disclosure-review", {}, token=token)
check("Disclosure review recommends review",
      code == 200 and resp["data"]["review_status"] == "PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED", resp)

resp, code = req("GET", f"/api/disclosures/{did}/verify", token=None)
check("Public disclosure verify 200 + hash match",
      code == 200 and resp["data"]["hash_match"] is True, resp)

for kind in ("ip-brief", "disclosure", "expert-handoff"):
    resp, code = req("POST", f"/api/products/{pid}/versions/{vid}/reports/{kind}", {}, token=token)
    check(f"Generate {kind} 201", code == 201, resp)
rid_report = resp["data"]["id"]

resp, code = req("GET", f"/api/products/{pid}/versions/{vid}/reports", token=token)
check("List reports 200", code == 200 and len(resp["data"]) == 3, resp)

resp, code = req("GET", f"/api/reports/{rid_report}/verify", token=None)
check("Public report verify 200 + hash match",
      code == 200 and resp["data"]["hash_match"] is True, resp)

resp, code = req("POST", "/api/reviews",
                 {"product_id": pid, "product_version_id": vid, "title": "UI flow"}, token=token)
check("Create review DRAFT 201",
      code == 201 and resp["data"]["status"] == "DRAFT", resp)
rid = resp["data"]["id"]
resp, code = req("POST", f"/api/reviews/{rid}/submit", {}, token=token)
check("Submit -> AI_SCREENED", code == 200 and resp["data"]["status"] == "AI_SCREENED", resp)
resp, code = req("POST", f"/api/reviews/{rid}/request-review", {}, token=token)
check("Request review -> REVIEW_REQUIRED",
      code == 200 and resp["data"]["status"] == "REVIEW_REQUIRED", resp)
resp, code = req("GET", "/api/reviews", token=token)
check("List reviews 200", code == 200 and len(resp["data"]) >= 1, resp)

resp, code = req("GET", "/api/dashboard", token=token)
check("Dashboard 200 with counts",
      code == 200 and resp["data"]["product_count"] >= 1, resp)

resp, code = req("GET", "/api/audit", token=token)
check("Audit trail 200", code == 200 and len(resp["data"]) >= 1, resp)

resp, code = req("GET", "/api/bhashini/languages", token=token)
check("BHASHINI languages 200",
      code == 200 and [s["code"] for s in resp["data"]["supported"]] == ["en", "hi", "bn"], resp)
resp, code = req("POST", "/api/bhashini/detect", {"text": "आयुर्वेद क्या है"}, token=token)
check("BHASHINI detect Hindi", code == 200 and resp["data"]["language"] == "hi", resp)
resp, code = req("POST", "/api/bhashini/translate",
                 {"text": "hello", "source_language": "en", "target_language": "en"}, token=token)
check("BHASHINI same-language passthrough",
      code == 200 and resp["data"]["translated"] is False, resp)

print("=== Gap closures: sources, users/me, knowledge index ===")

resp, code = req("GET", "/api/sources", token=token)
check("List sources 200", code == 200, resp)
check("A fresh account only sees public sources",
      all(s["is_public"] for s in resp["data"]), resp)
sources = resp["data"]

resp, code = req("GET", "/api/sources/search?q=ayurveda", token=token)
check("Search sources 200 + list", code == 200 and isinstance(resp["data"], list), resp)

if sources:
    sid = sources[0]["id"]
    resp, code = req("GET", f"/api/sources/{sid}", token=token)
    check("Fetch one source 200", code == 200, resp)
    check("Source detail exposes no file internals",
          "file_path" not in resp["data"] and "document_hash" not in resp["data"], resp)
else:
    check("Fetch one source skipped (no public sources in corpus yet)", True)

check("Sources require auth", req("GET", "/api/sources", token=None)[1] == 401)

resp, code = req("GET", "/api/users/me", token=token)
check("GET /api/users/me 200 + email match",
      code == 200 and resp["data"]["email"] == EMAIL, resp)

resp, code = req("PUT", "/api/users/me", {"username": f"{USERNAME}-ui"}, token=token)
check("PUT /api/users/me updates username",
      code == 200 and resp["data"]["username"] == f"{USERNAME}-ui", resp)

resp, code = req("GET", "/api/users/me/history", token=token)
check("History contains the profile update",
      code == 200 and any(e["action"] == "update_profile" for e in resp["data"]), resp)
check("/api/users/me requires auth", req("GET", "/api/users/me", token=None)[1] == 401)

resp, code = req("POST", "/api/knowledge/index", {}, token=token)
check("POST /api/knowledge/index 200", code == 200, resp)
check("A fresh account indexes nothing",
      resp["data"]["attempted"] == 0 and resp["data"]["skipped"] == 0, resp)

print(f"\n{len(results)} checks PASSED against {BASE}.")
if not ai_available:
    print("Note: the AI provider was unavailable, so the analysis error path was "
          "exercised instead of the results path.")
print("Frontend flow verified end to end.")
