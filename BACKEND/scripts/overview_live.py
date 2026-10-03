"""
Live acceptance for the Overall Product View (spec items 16-19).

Drives exactly the endpoints the /overview page calls against a running
server (uvicorn on 127.0.0.1:8000) on a fresh AshwaBio-X style passport:

    python scripts/overview_live.py

Sequence:
  1. Build a passport (ingredient with Indian source location, incomplete
     formulation, user-provided claim, India + Germany target markets).
  2. Read the overview with no analysis recorded at all.
  3. Run the patent, biodiversity/ABS and traditional-knowledge screenings,
     then read the overview again - demo-corpus records must never appear.
  4. Run the comprehensive analysis (real model) and read the overview again.
  5. Edit the claim so the recorded analysis goes stale, and confirm the
     overdue-hash warning, the exact sentence and the Re-run action.

Every check prints PASS/FAIL and the script exits non-zero if any check
failed. Exact sentences are imported from the service constants, so the
script never drifts from what the UI and chatbot are held to.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.overview_service import (  # noqa: E402
    ANALYSIS_OUTDATED_NOTICE,
    CLAIM_USER_PROVIDED_WARNING,
    CLASSIFICATION_GAP_REASON,
    DEMO_RECORD_LABEL,
    DISCLOSURE_ADVISORY,
    MARKET_EVIDENCE_NOTE,
    NO_DISCLOSURE_EVENT,
    NO_EVIDENCE_DOCS,
    NO_MARKET_EVIDENCE,
    NO_PATENT_RESULT,
    OVERVIEW_NOTICE,
    STATUS_ANALYSIS_NOT_RUN,
    STATUS_ANALYSIS_OUTDATED,
    TK_NO_SOURCE_NOTICE,
)

BASE = "http://127.0.0.1:8000"
PASSWORD = "TestPass1!"
uniq = int(time.time()) % 100000
EMAIL = f"ovw-live-{uniq}@test.example.com"
USERNAME = f"ovw-live-{uniq}"

ALLOWED_OVERALL = {
    "COMPLETE_FOR_REVIEW",
    "PARTIALLY_COMPLETE",
    "INSUFFICIENT_INFORMATION",
    "ANALYSIS_NOT_RUN",
    "ANALYSIS_OUTDATED",
    "REVIEW_REQUIRED",
}
ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "NOT_ASSESSED"}
ALLOWED_CLAIM = {
    "SUPPORTED_BY_ATTACHED_EVIDENCE",
    "USER_PROVIDED_ONLY",
    "EVIDENCE_MISSING",
    "EVIDENCE_REVIEW_REQUIRED",
    "SOURCE_BACKED",
    "NOT_ASSESSED",
}
ALLOWED_IP = {
    "NOT_ASSESSED",
    "SEARCH_NOT_RUN",
    "SEARCH_UNAVAILABLE",
    "NO_RELEVANT_RECORD_IDENTIFIED",
    "POTENTIALLY_RELEVANT",
    "FURTHER_REVIEW_RECOMMENDED",
    "VERIFIED_PUBLIC_RECORD",
}
ALLOWED_BIO = {
    "NOT_ASSESSED",
    "INFORMATION_MISSING",
    "POTENTIALLY_RELEVANT",
    "REVIEW_REQUIRED",
    "SOURCE_DOCUMENTATION_RECORDED",
}
CONTRACT_KEYS = [
    "product",
    "overall_status",
    "facts",
    "formulation",
    "ingredients",
    "claims",
    "evidence",
    "target_markets",
    "regulatory_classification",
    "ip_review",
    "biodiversity_abs_review",
    "traditional_knowledge_review",
    "disclosures",
    "analysis_history",
    "recommended_actions",
    "provenance",
    "disclaimers",
]
# Statuses and labels that would read as approval, clearance or a risk score.
FORBIDDEN = [
    "SAFE_TO_LAUNCH",
    "LEGALLY_COMPLIANT",
    "PATENT_SAFE",
    "NO_RISK",
    "risk_score",
    "Risk score",
    "risk score",
    "Live Demo",
    "illustrative demo",
]

results = []


def summarize():
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print()
    if passed == total:
        print(f"{total}/{total} checks PASSED against {BASE}.")
    else:
        print(f"{passed}/{total} checks passed - {total - passed} FAILED.")
    sys.exit(0 if passed == total else 1)


def check(label, ok, detail=""):
    results.append((label, bool(ok)))
    if ok:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} -> {detail}")


def die(label, detail=""):
    """Setup failure: nothing below can run without a token/product."""
    check(label, False, detail)
    summarize()


def req(method, path, body=None, token=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
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
    except OSError as e:
        # Timeouts and dropped sockets report as a failed check instead of
        # crashing the run - the check itself still has to pass honestly.
        return {"detail": f"transport error: {e}"}, 0


def strings_in(value):
    """Every string anywhere inside a payload (for forbidden-text scans)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings_in(key)
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def scan_forbidden(label, payload):
    blob = json.dumps(payload)
    hits = [word for word in FORBIDDEN if word in blob]
    check(label, not hits, f"forbidden text present: {hits}")


def field(block, key):
    for item in block.get("fields", []):
        if item.get("key") == key:
            return item
    return {}


# ======================================================================
# Setup: fresh passport
# ======================================================================

print("=== Setup: fresh passport ===")

resp, code = req("POST", "/api/auth/register", {
    "username": USERNAME,
    "email": EMAIL,
    "password": PASSWORD,
    "confirm_password": PASSWORD,
})
if code != 201 or resp.get("success") is not True:
    die("Register succeeds", resp)

resp, code = req("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
token = (resp.get("data") or {}).get("access_token") if code == 200 else None
if not token:
    die("Login succeeds", resp)

resp, code = req("POST", "/api/products", {
    "name": "AshwaBio-X",
    "description": "Overall Product View live acceptance",
    "category": "proprietary_ayurvedic",
}, token=token)
pid = (resp.get("data") or {}).get("id")
vid = (resp.get("data") or {}).get("current_version_id")
if code != 201 or not (pid and vid):
    die("Product created 201", resp)
base = f"/api/products/{pid}/versions"
print(f"    product id={pid}, version id={vid}")

resp, code = req("POST", f"{base}/{vid}/ingredients", {
    "common_name": "Ashwagandha",
    "botanical_name": "Withania somnifera",
    "plant_part": "root",
    "quantity": 100,
    "quantity_unit": "g",
    "source_type": "wild",
    "source_location": "Uttarakhand, India",
}, token=token)
if code != 201:
    die("Ingredient created 201", resp)

# Deliberately incomplete: solvent, pressure, duration and concentration are
# left unrecorded so the overview must report them as missing.
resp, code = req("PUT", f"{base}/{vid}/formulation", {
    "extraction_method": "cold-press",
    "temperature": 4,
    "temperature_unit": "C",
}, token=token)
if code != 200:
    die("Formulation created 200", resp)

resp, code = req("POST", f"{base}/{vid}/claims", {
    "claim_text": "Supports memory and cognition",
    "claim_type": "wellness",
}, token=token)
claim_id = (resp.get("data") or {}).get("id")
if code != 201 or not claim_id:
    die("Claim created 201", resp)

for country, region in (("India", "South Asia"), ("Germany", "European Union")):
    resp, code = req("POST", f"{base}/{vid}/target-markets", {
        "country": country,
        "region": region,
        "regulatory_status": "planned",
    }, token=token)
    if code != 201:
        die(f"Target market {country} created 201", resp)

# ======================================================================
# 1. Overview with no analysis, no screening - everything must be honest
# ======================================================================

print("\n=== 1. Overall Product View: passport only, no runs recorded ===")

resp, code = req("GET", f"{base}/{vid}/overview", token=token)
check("GET overview 200", code == 200, resp)
ov = resp.get("data") or {}

missing = [key for key in CONTRACT_KEYS if key not in ov]
check("Contract keys present (16 sections + provenance + disclaimers)", not missing, missing)
scan_forbidden("No demo/approval/risk text anywhere in the payload", ov)

product = ov.get("product", {})
check(
    "Product, version and full content hash reported",
    product.get("name") == "AshwaBio-X"
    and product.get("version_id") == vid
    and len(product.get("content_hash") or "") == 64,
    product,
)
check(
    "Missing update timestamp is declared, not invented",
    product.get("updated_at") is None and bool(product.get("updated_at_note")),
    product,
)
check("Owner shown as the creator", product.get("owner") == USERNAME, product)

overall = ov.get("overall_status", {})
check("Overall status in closed vocabulary", overall.get("status") in ALLOWED_OVERALL, overall)
check("Confidence in closed vocabulary", overall.get("confidence") in ALLOWED_CONFIDENCE, overall)
check("No analysis yet -> ANALYSIS_NOT_RUN", overall.get("status") == STATUS_ANALYSIS_NOT_RUN, overall)
check("Preliminary-decision-support notice exact", OVERVIEW_NOTICE in (ov.get("disclaimers") or []), ov.get("disclaimers"))

facts = ov.get("facts", {})
check("Facts carry per-value provenance", bool(facts.get("fields")) and all(f.get("provenance") for f in facts["fields"]), facts)

formulation = ov.get("formulation", {})
solvent = field(formulation, "solvent")
check(
    "Unrecorded formulation fields say Not provided with provenance",
    solvent.get("value") == "Not provided" and solvent.get("provenance") == "NOT_PROVIDED",
    solvent,
)
check("Formulation source summary present", bool(formulation.get("source_summary")), formulation)

ingredients = ov.get("ingredients", [])
check(
    "Ingredient recorded as USER_PROVIDED",
    len(ingredients) == 1 and ingredients[0].get("provenance") == "USER_PROVIDED",
    ingredients,
)

claims = ov.get("claims", [])
claim = claims[0] if claims else {}
check("Claim standing in closed vocabulary", claim.get("evidence_status") in ALLOWED_CLAIM, claim)
check("Claim is user-provided only", claim.get("evidence_status") == "USER_PROVIDED_ONLY", claim)
check("Claim marketing status exact", claim.get("marketing_status") == "DO NOT PRESENT AS VERIFIED", claim)
check("Claim warning sentence exact", claim.get("warning") == CLAIM_USER_PROVIDED_WARNING, claim)
check("Claim verification NOT_FOUND (spec token)", claim.get("independent_verification") == "NOT_FOUND", claim)
check("No evidence documents -> exact sentence", claim.get("evidence_linkage") == NO_EVIDENCE_DOCS, claim)
check("Claim has no linked analysis yet", claim.get("linked_analysis") is None, claim)
check("Claim markets follow the passport", len(claim.get("markets_affected") or []) == 2, claim.get("markets_affected"))
check("Evidence list empty and stated", (ov.get("evidence") or []) == [] and NO_EVIDENCE_DOCS in json.dumps(ov), ov.get("evidence"))

markets = ov.get("target_markets", {})
labels = {s.get("label") for s in markets.get("sections", [])}
check("Two markets recorded", markets.get("count") == 2, markets)
check("Section labels INDIA and GERMANY/EU", labels == {"INDIA", "GERMANY/EU"}, labels)
check(
    "Market rows never invent evidence",
    all(m.get("market_evidence_count") == 0 for m in markets.get("markets", []))
    and markets.get("markets", [{}])[0].get("market_evidence_note") == MARKET_EVIDENCE_NOTE,
    markets.get("markets"),
)
check(
    "Exact no-market-evidence sentence on every section",
    all(s.get("evidence_note") == NO_MARKET_EVIDENCE for s in markets.get("sections", [])),
    markets.get("sections"),
)
check(
    "Market sections separate sources from declarations",
    all(s.get("sources_used") == [] for s in markets.get("sections", [])),
    markets.get("sections"),
)

rc = ov.get("regulatory_classification", {})
check("Classification UNRESOLVED without an analysis", rc.get("status") == "UNRESOLVED", rc)
check("Classification confidence LOW", rc.get("confidence") == "LOW", rc)
check("Classification gap reason exact", rc.get("reason") == CLASSIFICATION_GAP_REASON, rc)
check("Pathways listed, not selected", bool(rc.get("possible_pathways")) and rc.get("source") == "NOT_ASSESSED", rc)
check("Intended use reported missing", "intended use" in (rc.get("missing_information") or []), rc.get("missing_information"))

ip = ov.get("ip_review", {})
check("IP search not run stated", ip.get("status") == "SEARCH_NOT_RUN", ip)
check("Exact no-patent-result sentence", ip.get("notice") == NO_PATENT_RESULT, ip)
check("No patent records before screening", ip.get("records") == [], ip.get("records"))
check("No feature disclaimer without a comparison", ip.get("features_disclaimer") is None, ip)

bio = ov.get("biodiversity_abs_review", {})
tk = ov.get("traditional_knowledge_review", {})
check("Biodiversity not assessed yet", bio.get("status") == "NOT_ASSESSED", bio)
check("Traditional knowledge not assessed yet", tk.get("status") == "NOT_ASSESSED", tk)

disclosures = ov.get("disclosures", {})
check("No disclosure event exact sentence", disclosures.get("notice") == NO_DISCLOSURE_EVENT, disclosures)
check("Disclosure advisory exact", disclosures.get("advisory") == DISCLOSURE_ADVISORY, disclosures)
check("Disclosure count zero", disclosures.get("event_count") == 0, disclosures)

check("No analysis history yet", ov.get("analysis_history") == [], ov.get("analysis_history"))

actions = ov.get("recommended_actions", [])
check("Recommended actions derived from gaps", len(actions) > 0, actions)
check(
    "Actions use HIGH/MEDIUM/LOW priorities only",
    all(a.get("priority") in {"HIGH", "MEDIUM", "LOW"} for a in actions),
    actions,
)
check("Run-analysis action offered", any(a.get("id") == "run_analysis" for a in actions), [a.get("id") for a in actions])

provenance = ov.get("provenance", {})
check(
    "Provenance map covers the data sections",
    all(provenance.get(key) for key in ("facts", "formulation", "ingredients", "claims", "target_markets")),
    provenance,
)
check("Missing information listed", bool(ov.get("missing_information")), ov.get("missing_information"))

# ======================================================================
# 2. Screenings: patent (demo corpus), biodiversity/ABS, traditional knowledge
# ======================================================================

print("\n=== 2. Screenings recorded against the passport ===")

resp, code = req("POST", f"{base}/{vid}/patents/search", token=token, timeout=120)
check("Patent screening 200", code == 200, resp)

resp, code = req("POST", f"{base}/{vid}/biodiversity/screen", token=token, timeout=120)
check("Biodiversity screening 200", code == 200, resp)

resp, code = req("POST", f"{base}/{vid}/traditional-knowledge/screen", token=token, timeout=120)
check("Traditional-knowledge screening 200", code == 200, resp)

resp, code = req("GET", f"{base}/{vid}/overview", token=token)
check("Overview after screenings 200", code == 200, resp)
ov = resp.get("data") or {}

ip = ov.get("ip_review", {})
check("Demo-corpus search reported SEARCH_UNAVAILABLE", ip.get("status") == "SEARCH_UNAVAILABLE", ip)
check("Exact no-patent-result sentence still shown", ip.get("notice") == NO_PATENT_RESULT, ip)
check("Synthetic records omitted, not listed", ip.get("records") == [] and (ip.get("synthetic_records_omitted") or 0) >= 1, ip)
check("Demo-corpus label exact", ip.get("demo_notice") == DEMO_RECORD_LABEL, ip.get("demo_notice"))
check("IP status in closed vocabulary", ip.get("status") in ALLOWED_IP, ip)

bio = ov.get("biodiversity_abs_review", {})
check("Biodiversity status in closed vocabulary", bio.get("status") in ALLOWED_BIO, bio)
if bio.get("status") == "POTENTIALLY_RELEVANT":
    check(
        "Biodiversity reason never asserts an obligation",
        "insufficient to determine whether any specific legal obligation" in (bio.get("reason") or ""),
        bio.get("reason"),
    )
    check("Biodiversity structurally missing fields listed", bool(bio.get("missing_fields")), bio.get("missing_fields"))

tk = ov.get("traditional_knowledge_review", {})
check("TK screening status recorded", tk.get("status") != "NOT_ASSESSED", tk)
check("TK restricted-sources notice exact", tk.get("notice") == TK_NO_SOURCE_NOTICE, tk.get("notice"))

check("Screenings appear in analysis history", len(ov.get("analysis_history") or []) >= 3, ov.get("analysis_history"))
scan_forbidden("Still no approval/risk text after screenings", ov)

# ======================================================================
# 3. Comprehensive analysis (real model)
# ======================================================================

print("\n=== 3. Comprehensive analysis (real model) ===")

resp, code = req("POST", f"{base}/{vid}/analyze", token=token, timeout=300)
check("Comprehensive analysis 200", code == 200, resp)

resp, code = req("GET", f"{base}/{vid}/overview", token=token)
check("Overview after analysis 200", code == 200, resp)
ov = resp.get("data") or {}

analysis = ov.get("analysis", {})
check("Analysis no longer NOT_RUN", analysis.get("status") != "NOT_RUN", analysis)
check("Analysis run id and timestamp recorded", bool(analysis.get("run_id")) and bool(analysis.get("timestamp")), analysis)
check("Overall status still in vocabulary", ov.get("overall_status", {}).get("status") in ALLOWED_OVERALL, ov.get("overall_status"))
check("Overall left ANALYSIS_NOT_RUN", ov.get("overall_status", {}).get("status") != STATUS_ANALYSIS_NOT_RUN, ov.get("overall_status"))
scan_forbidden("No approval/launch/risk text after analysis", ov)

rc = ov.get("regulatory_classification", {})
check("Classification now analysis-derived", rc.get("source") == "ANALYSIS_DERIVED", rc)
check("Classification run linked", bool(rc.get("analysis_run")), rc)

claim = (ov.get("claims") or [{}])[0]
check("Claim linked to the recorded analysis", bool((claim.get("linked_analysis") or {}).get("run_id")), claim.get("linked_analysis"))
check("Claim standing unchanged by the analysis (advisory only)", claim.get("evidence_status") == "USER_PROVIDED_ONLY", claim)
check("Claim marketing status still exact", claim.get("marketing_status") == "DO NOT PRESENT AS VERIFIED", claim)

check("Comprehensive run in history", any(e.get("analysis_type") in {"comprehensive", "claim_analysis", "product_classification"} for e in ov.get("analysis_history") or []), ov.get("analysis_history"))

# ======================================================================
# 4. Claim edit -> recorded analysis goes stale
# ======================================================================

print("\n=== 4. Claim edit makes the recorded analysis outdated ===")

resp, code = req("PUT", f"{base}/{vid}/claims/{claim_id}", {
    "claim_text": "Supports memory and cognition (revised wording)",
}, token=token)
check("Claim edit 200", code == 200, resp)

resp, code = req("GET", f"{base}/{vid}/overview", token=token)
check("Overview after claim edit 200", code == 200, resp)
ov = resp.get("data") or {}

overall = ov.get("overall_status", {})
check("Overall flips to ANALYSIS_OUTDATED", overall.get("status") == STATUS_ANALYSIS_OUTDATED, overall)
check("Overdue-hash warning sentence exact", overall.get("outdated_notice") == ANALYSIS_OUTDATED_NOTICE, overall.get("outdated_notice"))
check("Analysis block flagged outdated", ov.get("analysis", {}).get("outdated") is True, ov.get("analysis"))
check(
    "Re-run analysis action offered",
    any(a.get("id") == "rerun_analysis" and a.get("title") == "Re-run analysis" for a in ov.get("recommended_actions") or []),
    [a.get("id") for a in ov.get("recommended_actions") or []],
)
check(
    "Run history labels the stale run",
    any(e.get("outdated") and "OUTDATED" in (e.get("outdated_notice") or "") for e in ov.get("analysis_history") or []),
    ov.get("analysis_history"),
)
scan_forbidden("No approval/launch/risk text on the outdated view", ov)

resp, code = req("GET", f"{base}/{vid}", token=token)
version_hash = (resp.get("data") or {}).get("content_hash")
check("Overview hash equals the version's own hash", ov.get("product", {}).get("content_hash") == version_hash, ov.get("product"))

# ======================================================================
# Final output
# ======================================================================

print("\n=== Overall Product View (live output) ===")
p = ov["product"]
print(f"product              : {p['name']} - version {p['version']} (id {p['version_id']})")
print(f"content hash         : {p['content_hash'][:16]}... (full hash on hover in the UI)")
print(f"overall status       : {overall['status']} (confidence {overall['confidence']})")
print(f"analysis             : {ov['analysis']['status']} run={ov['analysis'].get('run_id')} outdated={ov['analysis'].get('outdated')}")
print(f"facts                : {len(ov['facts']['fields'])} fields, provenance {sorted({f['provenance'] for f in ov['facts']['fields']})}")
print(f"formulation          : solvent={field(ov['formulation'], 'solvent').get('value')} (missing fields reported, never invented)")
print(f"ingredients          : {len(ov['ingredients'])} ({ov['ingredients'][0]['provenance']})")
c0 = ov['claims'][0]
print(f"claims               : {len(ov['claims'])} - {c0['evidence_status']} / {c0['marketing_status']} / review {c0['review_status']}")
print(f"target markets       : {[m['country'] for m in ov['target_markets']['markets']]} sections={[s['label'] for s in ov['target_markets']['sections']]}")
print(f"classification       : {ov['regulatory_classification']['status']} (confidence {ov['regulatory_classification']['confidence']}, source {ov['regulatory_classification']['source']})")
print(f"ip / prior art       : {ov['ip_review']['status']} - {len(ov['ip_review']['records'])} verified public records ({ov['ip_review'].get('synthetic_records_omitted')} synthetic omitted)")
print(f"biodiversity / ABS   : {ov['biodiversity_abs_review']['status']}")
print(f"traditional knowledge: {ov['traditional_knowledge_review']['status']}")
print(f"disclosures          : {ov['disclosures']['event_count']} recorded - {ov['disclosures']['review_status']}")
print(f"analysis history     : {len(ov['analysis_history'])} run(s)")
print(f"recommended actions  : {len(ov['recommended_actions'])} {[a['priority'] for a in ov['recommended_actions']]}")
print(f"missing information  : {len(ov['missing_information'])} item(s)")

summarize()
