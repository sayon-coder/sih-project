# IP-SAKTI Sahayak - Development Log

---

## Entry: 2026-09-26 (Phases 8b-13)

### Phases: 8b Reports, 9 Expert Review, 10 Dashboard/Audit/Admin, 11 BHASHINI, 12 Frontend, 13 Integration

### Task
Finish all remaining phases after the Phase 7 handoff: PDF reports with QR
verification, the expert review state machine, dashboard/audit/admin, the
BHASHINI language layer, frontend wiring for the new workflows, and final
integration testing, security review, documentation and the Ashwagandha demo.

### What was implemented
1. **Phase 8b - reports (`app/models/report_models.py`, migration 008,
   `app/reports/builders.py`, `app/services/report_service.py`,
   `app/routers/reports.py`):** `reports` table with SHA-256 `content_hash`
   and `verification_id`; deterministic ReportLab builders for the IP
   Opportunity & Evidence Brief, Invention Disclosure Record and Expert
   Handoff Package (QR + verify URL + all disclaimers in every PDF);
   `POST .../reports/ip-brief|disclosure|expert-handoff`, listing, owner-only
   PDF download, public `GET /api/reports/{id}/verify`. `deferred_components`
   is now empty; `tests/test_analysis.py` updated accordingly.
2. **Phase 9 - expert review (`app/models/review_models.py`, migration 009,
   `app/services/review_service.py`, `app/routers/reviews.py`):** full state
   machine with 409 on illegal transitions and 403 on reviewer-only actions;
   deterministic AI-screen checklist on submit; expert comments open
   EXPERT_REVIEW; completion promotes listed claims/evidence to
   EXPERT_VERIFIED (the only path); EXPERT/ADMIN reviewer pool may open any
   review (fixed after tests exposed the ownership gap).
3. **Phase 10 - dashboard/audit/admin (`app/routers/dashboard.py`,
   `audit.py`, `admin.py`, `require_admin` guard):** owner-scoped aggregates,
   own-trail audit reads, ADMIN-only users/sources/RAG-status/audit endpoints.
4. **Phase 11 - BHASHINI (`app/bhashini/` + `app/routers/bhashini.py`):**
   script-based detection, glossary (18 terms), identifier masking,
   honest fallback (original + warning, never invented); assistant chat runs
   retrieval/reasoning on the canonical query and maps the answer back.
5. **Phase 12 - frontend (`FRONTEND/src/App.jsx`):** API methods plus
   DisclosuresSection, ReportsSection, /reviews, /dashboard, chat language
   selects; `vite build` clean; `verify_frontend_flow.py` extended to 127/127.
6. **Phase 13 - integration:** `scripts/verify_demo_flow.py` (full
   Ashwagandha scenario, 26 checks live); security pass (no hardcoded
   secrets, no raw SQL, upload validation, safe errors); README rewritten for
   phases 8-13; requirements + `.env.example` completed.

### Bugs discovered / fixed
- 008/009 downgrades: `ENUM.drop()` needs a bind; used `op.execute DROP TYPE`
  per repo pattern. Also fixed a duplicated enum label in 009 before applying.
- Assistant chat returned 500 when embeddings were missing; `hybrid_retrieve`
  now falls back to keyword-only search with a warning (real bug, plus test).
- Missing-token auth returned 403 (FastAPI default); `HTTPBearer(auto_error=
  False)` + explicit 401 in `verify_token` fixed the 5 failing auth tests.
- Demo script issues (all script-side): formulation temperature must be
  numeric; screening payloads nest under `data.results`; TK registry is a
  dict; v2 claims have new ids after cloning.
- `verify_frontend_flow.py`: updated stale deferred/not_compared expectations;
  added UTF-8 stdout handling.

### Tests Executed
- Full pytest suite: 203/203 pass (was 198 + 5 env failures before the 401 fix)
- `verify_migrations.py`: 5/5 at head 009 (live DB upgraded stepwise to 009)
- `verify_frontend_flow.py`: 127/127 live
- `verify_demo_flow.py`: 26/26 live (exit 0)
- `vite build`: 0 errors

### Remaining issues / debt (carried over, unchanged)
- First AI run downloads the embedding model; live patent corpus still demo;
  no result caching; test UI is minimal; Pydantic ConfigDict migration pending.

### Next Step
Hand over to the team: run `alembic upgrade head`, `pytest tests/ -q`, and the
verify scripts above. Configure BHASHINI + GROQ keys for live AI/translation.

---
# IP-SAKTI Sahayak - Development Log

---

## Entry: 2026-09-26 (Phase 8a)

### Phase: 8a - Disclosure tracking, disclosure review, change-impact disclosure comparison

### Task
Implement the disclosure half of Phase 8: immutable public-disclosure events
pinned to product versions, an advisory disclosure review, SHA-256 integrity
with a public verification endpoint, and wire disclosure history into the
Phase 7 change-impact simulator (which previously reported public disclosure
as not comparable). ReportLab PDFs remain for Phase 8b.

### What was implemented
1. **Disclosure model (`app/models/disclosure_models.py`):** `Disclosure`
   with `disclosure_type` enum (conference/publication/website/investor/
   advertising/commercial_launch/other), declarant + institution, SHA-256
   `record_hash`, unique `verification_id`; shared disclaimer constants.
2. **Migration 007 (`alembic/versions/007_disclosures.py`):** `disclosures`
   table + `disclosuretype` enum. Downgrade follows the repo pattern
   (`op.execute DROP TYPE`, after fixing an `ENUM.drop(bind)` failure).
3. **Service (`app/services/disclosure_service.py`):** create/list/version
   counts + types, deterministic advisory review (per-type considerations and
   questions, `PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED` / `NO_EVENTS_RECORDED`),
   hash recomputation for verification. Ownership via `get_accessible_*`.
4. **Router (`app/routers/disclosures.py`):** version-scoped
   `GET/POST .../disclosures` + `POST .../disclosure-review`; global
   `POST /api/disclosures`, owner-only `GET /api/disclosures/{id}`, and
   **public** (no auth) `GET /api/disclosures/{id}/verify` for QR checks.
5. **Change-impact integration:** new `_compare_disclosures` in
   `app/analysis/change_impact.py` (new event on either side is significant,
   with an expert-review reason); service passes recorded event types;
   the hardcoded `public_disclosure` not_compared entry is removed.
6. **Tests:** `tests/test_phase8_disclosures.py` (17 tests: recording, hash,
   disclaimer, auth boundaries, global endpoints, public verify, review
   vocabulary, version scoping, advisory-only) and 2 updated Phase 7 tests.

### Files Created
- `BACKEND/app/models/disclosure_models.py`
- `BACKEND/alembic/versions/007_disclosures.py`
- `BACKEND/app/services/disclosure_service.py`
- `BACKEND/app/routers/disclosures.py`
- `BACKEND/tests/test_phase8_disclosures.py`
- `BACKEND/scripts/verify_phase8a.py`

### Files Modified
- `BACKEND/app/models/__init__.py`
- `BACKEND/app/routers/__init__.py`
- `BACKEND/app/main.py` (routers registered, health phase 8a)
- `BACKEND/app/analysis/change_impact.py`
- `BACKEND/app/services/change_impact_service.py`
- `BACKEND/tests/test_phase7.py` (not_compared expectation updated + disclosure test)
- `BACKEND/scripts/verify_migrations.py` (EXPECTED_TABLES + disclosures)
- `PROJECT_STATUS.md`, `TODO.md`, `DEVELOPMENT_LOG.md`

### Tests Executed
- `pytest tests/test_phase8_disclosures.py`: 17/17 pass
- `pytest tests/test_phase7.py`: 20/21 pass (1 pre-existing env failure:
  `test_requires_authentication` expects 401, FastAPI HTTPBearer returns 403)
- `scripts/verify_phase8a.py`: 13/13 live PostgreSQL checks pass
- `scripts/verify_migrations.py`: 5/5 at head 007 (live DB upgraded 006 -> 007)

### Bugs discovered / fixed
- 007 downgrade used `postgresql.ENUM(...).drop()` which needs a bind in this
  SQLAlchemy version; replaced with `op.execute("DROP TYPE IF EXISTS ...")`
  per the repo pattern.
- verify script cleanup hit FK order (`products.current_version_id`,
  `audit_logs`); fixed deletion order.

### Remaining issues
- ReportLab PDFs (8b) not started: ip-brief, disclosure record, expert handoff.
- QR code is a stored `verification_id`; rendering the QR image is 8b work.

### Next Step
Phase 8b: `app/reports/` PDF builders + `POST .../reports/*` endpoints.

---
# IP-SAKTI Sahayak - Development Log

---

## Entry: 2026-09-26 00:56 IST

### Phase: 7 - Formulation Change Impact Simulator

### Task: Compare two versions of a product and return meaningful differences plus review questions

### Starting Point Found

Phase 6 left all the material a comparison needs: version-scoped ingredients,
formulation, claims, evidence and markets, plus the Phase 6 engines for patent
signals and biodiversity/TK status. There was no way to ask "what changed between
v1 and v2, and what does that change touch?", and the master prompt's
``change_impacts`` table did not exist.

### What Was Implemented

**Design decision - deterministic, and honest about what it cannot compare.** The
simulator is a named field comparison between two stored versions. A model is not
asked to summarise or judge, because the value here is completeness and accuracy
of the diff, not prose. Two categories the master prompt lists cannot be compared
yet - public disclosure (a Phase 8 feature) and product classification (only
available if a comprehensive analysis was recorded) - so the report names them in
an explicit ``not_compared`` list with the reason, instead of silently omitting
them.

**New files**

- `app/models/change_impact_models.py` - `ChangeImpact`, pinned to **both**
  versions. A dedicated table (not ``analyses``) because a run is about a pair of
  versions, not one.
- `alembic/versions/006_change_impacts.py` - creates `change_impacts`; reuses the
  existing `analysisstatus` enum.
- `app/analysis/change_impact_schemas.py` - `FieldChange`, `ImpactReviewQuestion`,
  `NotCompared`, `ChangeImpactResult` and the significance vocabulary
  (`informational` / `review_recommended` / `significant`).
- `app/analysis/change_impact.py` - the simulator: ingredients, botanical species,
  plant parts, quantities, origin, cultivation/wild, formulation, extraction,
  claims, evidence, target markets, patent signals, biodiversity/TK and
  classification, plus the review-question bank.
- `app/services/change_impact_service.py` - runs and persists comparisons.
- `app/routers/change_impact.py` - `POST/GET /api/products/{id}/change-impact`
  and `GET .../change-impact/{impact_id}`.
- `app/services/version_content.py` - a small shared loader, now used by both the
  Phase 6 and Phase 7 services so a comparison and a screening always see the same
  content.
- `tests/test_phase7.py` (20 tests) and `scripts/verify_phase7.py` (48 live checks).

**Changed files**

- `app/analysis/prompts.py` - added `CHANGE_IMPACT_DISCLAIMER`.
- `app/models/product_models.py`, `app/models/__init__.py` - the `change_impacts`
  relationship on `Product` and the new export.
- `app/services/ip_service.py` - `_content` now delegates to the shared loader.
- `app/routers/__init__.py`, `app/main.py` - register the router; health reports
  `phase: "7"`.
- `FRONTEND/src/App.jsx` - API client methods and a "Formulation change impact
  (Phase 7)" card on the versions page (from/to pickers, recorded-run picker,
  differences grouped by category with significance badges, review questions and
  the not-compared list).
- `scripts/verify_migrations.py` - expects 19 tables (was 18).
- `scripts/verify_frontend_flow.py` - the Phase 7 section (90 -> 108 checks).
- `scripts/verify_phase5.py`, `scripts/verify_phase6.py`, `scripts/verify_phase7.py`
  - read the migration head dynamically and treat "phase N or later" as healthy,
  so a later phase no longer breaks an earlier script.

### The changes it detects

The demo scenario's central change - cultivated -> wild Ashwagandha, a
solvent-extraction -> cold-press process change, a new therapeutic claim and a new
target market - produces 18 differences across 8 categories, five of them
significant, and the report explains why expert review is recommended:

```
claims: claim (Improves sleep onset)            none -> therapeutic            significant
cultivation: source_type (Ashwagandha)          cultivated -> wild             significant
extraction: extraction_method (formulation)     solvent extraction -> cold-press significant
extraction: solvent (formulation)               ethanol -> water                significant
markets: target_market (Germany)                none -> Germany                 significant
biodiversity_tk: biodiversity/ABS status        POTENTIALLY_RELEVANT -> REVIEW_RECOMMENDED
patent_signals: extraction_method/solvent/temperature/technical_effect changed
```

### Design Decisions Worth Recording

1. **Runs are pinned to both versions and are immutable.** Re-running writes a
   new row, exactly as analyses do, so a historical comparison is never rewritten.
2. **Significance, then category, then field ordering.** The most consequential
   differences lead the report; the test suite asserts the ordering.
3. **A change flows through to the Phase 6 engines.** A botanical or process
   change automatically moves the patent signal and the biodiversity/TK status in
   the same report, using the same engines the dedicated screens use.
4. **Two questions are always asked**, even for an identical comparison: whether
   anything has been or will be publicly disclosed (timing can matter), and which
   significant changes need expert review.
5. **The report never concludes.** Every difference carries a cautious note, and
   the disclaimers travel with the run.

### Tests Executed

- `pytest tests/ -q` -> **150 passed** (0 failures; 20 new Phase 7 tests)
- `scripts/verify_phase7.py` -> **48/48** against the live PostgreSQL database
- `scripts/verify_migrations.py` -> **5/5** (head `006`; 19 tables)
- Regressions (live): `verify_phase2.py` 27/27, `verify_phase3.py` 38/38,
  `verify_phase4.py` 9/9, `verify_phase5.py` 38/38, `verify_phase6.py` 57/57
- `scripts/verify_frontend_flow.py` -> **108/108** against a running server
- `npx vite build` -> clean (24 modules, ~333 kB JS)
- Browser check on `/products/16/versions`: the change-impact card runs a
  comparison and renders the ranked differences, review questions and
  not-compared list.

### Issues Found and Fixed

1. **A cosmetic report bug:** an added target market rendered as
   `markets: target_market (Germany) - none -> none`, because the value carried
   the (absent) region. Now falls back to the country.
2. **The older verification scripts hard-coded the migration head and phase.**
   `verify_phase5.py` and `verify_phase6.py` broke the moment this phase landed.
   All of them now read the head from the migration scripts and accept "phase N or
   later".
3. **Frontend layout:** the versions page gained a second card, and
   `.page-center` is a flex **row**, so the two cards sat side by side. Added a
   `.page-stack` (column) wrapper for pages that hold more than one card.

### Remaining Issues

- Classification is only compared when each version has a recorded comprehensive
  analysis; otherwise the report says so. A lightweight deterministic
  classification signal could remove that dependency.
- Public-disclosure comparison stays unavailable until Phase 8 creates the
  disclosures table.
- The browser check and the flow script leave throwaway accounts/products in the
  live database (`buffi6@example.com` / `buffipass123` and `fe-verify-*`).

### Next Step

Phase 8 - reports, invention disclosure records, SHA-256/QR verification and the
public-disclosure review that Phase 7 currently reports as not comparable.

---

## Entry: 2026-09-25 23:47 IST

### Phase: 6 - IP route map, patent screening with feature comparison, biodiversity/ABS and TK screening

### Task: Make the stages that `POST .../analyze` reported as deferred real, and remove
### them from `deferred_components`

### Starting Point Found

Phase 5 finished with `deferred_components` naming two Phase 6 stages outright:

* "IP route map and patent screening (Phase 6)"
* "Biodiversity / ABS and traditional-knowledge screening (Phase 6)"

The `analysistype` enum already contained `IP_ROUTE_MAP`, `PATENT_SCREENING`,
`BIODIVERSITY_SCREENING` and `TK_SCREENING` (they were created with the enum in
migration 002), so no enum work was needed - but there were no tables, no
service, no routes and no analyzers behind those labels.

A second, unrelated blocker was found on the very first run: the backend would
not start at all because `.env` now contains an `HF_TOKEN` key that
`app.config.Settings` did not declare. Pydantic-settings rejects unexpected keys
with `extra_forbidden`, so **every** entry point (`uvicorn`, `pytest`, every
verification script) failed at import. This was fixed first, because nothing
could be verified until the app would start.

### What Was Implemented

**Design decision - deterministic, not AI, for the screening stages.** The master
prompt warns that an IP route must not be presented as legally applicable merely
because a model suggests it, and forbids fabricating patent results. So Phase 6
derives everything from the recorded product data plus a frozen, clearly-labelled
demonstration corpus. No model is asked to invent patent content, and there is no
path by which a fabricated patent number or source can reach a response.

**New files**

- `app/models/patent_models.py` - `PatentRecord` (version-pinned candidate
  record; `record_source`, `is_demo`, `corpus_version`, `relevance_label`,
  `similarity`, `similarity_band`, `uncertainty`, `provenance`) and
  `PatentFeature` (one compared feature with a `match`/`different`/`unknown`
  verdict).
- `alembic/versions/005_patent_records.py` - creates `patent_records` and
  `patent_features` (both `ON DELETE CASCADE` from `product_versions`).
- `app/data/__init__.py`, `app/data/patent_demo_corpus.py` - the frozen
  demonstration corpus (`demo-patents-2026.09`): six illustrative records with
  `DEMO-...` ids, illustrative assignees, no real patent numbers, and an explicit
  `DEMO_CORPUS_NOTE` attached to every screening response.
- `app/data/traditional_knowledge_sources.py` - the source registry that makes
  the public / permitted / restricted distinction concrete, with the TKDL
  recorded as restricted: not accessed, not searched, not reproduced.
- `app/analysis/ip_schemas.py` - the Phase 6 result schemas.
- `app/analysis/ip_routes.py` - the deterministic IP route map (nine routes,
  each with a careful label, the signals that triggered it, and review
  questions).
- `app/analysis/patent_screening.py` - technical-feature extraction (master
  prompt section 18 vocabulary), feature comparison and similarity banding.
- `app/analysis/screening.py` - biodiversity/ABS and traditional-knowledge
  screening, each returning one of the four allowed statuses.
- `app/services/ip_service.py` - `IPService`, which runs the workflows and
  persists their results.
- `app/routers/ip.py` - the eight Phase 6 endpoints.
- `tests/test_phase6.py` (25 tests) and `scripts/verify_phase6.py` (57 live
  checks).

**Changed files**

- `app/analysis/prompts.py` - added the IP route, patent, biodiversity and
  traditional-knowledge disclaimers.
- `app/analysis/schemas.py` / `app/services/analysis_service.py` -
  `DEFERRED_COMPONENTS` now names only the Phase 8 public-disclosure review, and
  a comprehensive analysis embeds `ip_route_map`, `patent_signals`,
  `biodiversity_screening` and `traditional_knowledge_screening`.
- `app/models/product_models.py`, `app/models/__init__.py` - the new
  relationship and exports.
- `app/routers/__init__.py`, `app/main.py` - register the router; health now
  reports `phase: "6"`.
- `app/config.py` / `.env.example` - declare the optional `hf_token` setting.
- `FRONTEND/src/App.jsx` - API client methods and the "IP screening (Phase 6)"
  section on the version page (route map, patent screening with a feature table,
  re-run comparison, biodiversity/ABS and TK screening, TK source registry, and
  the embedded components inside the comprehensive analysis view).
- `scripts/verify_migrations.py` - expects 18 tables (was 16).
- `scripts/verify_phase5.py` - reads the migration head dynamically and treats
  "phase 5 or later" as healthy, so it does not rot as later phases land.
- `scripts/verify_frontend_flow.py` - the Phase 6 section (50 -> 90 checks).
- `tests/test_analysis.py` - the comprehensive-analysis assertion now requires
  the Phase 6 stages to be present and no longer deferred.

**Endpoints added** (all scoped to an owned product version)

```
GET  /api/products/{pid}/versions/{vid}/ip-routes
POST /api/products/{pid}/versions/{vid}/patents/search
GET  /api/products/{pid}/versions/{vid}/patents
POST /api/products/{pid}/versions/{vid}/patents/compare
GET  /api/patents/{patent_id}
POST /api/products/{pid}/versions/{vid}/biodiversity/screen
POST /api/products/{pid}/versions/{vid}/traditional-knowledge/screen
GET  /api/traditional-knowledge/sources
```

### Design Decisions Worth Recording

1. **Patent screening is always labelled a demonstration corpus.** There is no
   live patent source, so `retrieval_mode` is `DEMO_CORPUS`, `search_is_live` is
   `false`, every record is `is_demo=true` with `DEMO-...` ids and no real patent
   number, and the response carries the demo-corpus note. The screen never claims
   a live search.
2. **Corpus-source attachment is opt-in.** A screening is deterministic and does
   not need the embedding model; `?include_sources=true` additionally searches the
   accessible corpus for real supporting passages, and a retrieval failure (for
   example an uncached model) degrades to "no corpus sources" with an explicit
   warning instead of failing the screening.
3. **Restricted sources are never retrieved.** The TKDL is listed by the registry
   as restricted and unavailable; it is never searched, and no restricted content
   is reproduced. Only a genuinely retrieved passage becomes a source.
4. **Version-pinned.** Candidate records reference the exact version that was
   screened, and each run is a normal `analyses` row, so a later version cannot
   inherit or rewrite an earlier screening.
5. **Advisory-only.** No screening mutates claims, evidence, ingredients or the
   formulation - asserted in both the tests and the live script.
6. **Provenance.** Screening output is machine-generated and is stamped
   `AI_ANALYSIS` (the platform's single "not expert-verified" bucket). Nothing in
   Phase 6 can reach `EXPERT_VERIFIED`; only the Phase 9 workflow can.

### Tests Executed

- `pytest tests/ -q` -> **130 passed** (0 failures; 25 new Phase 6 tests)
- `scripts/verify_migrations.py` -> **5/5** (downgrade base + upgrade head in one
  rolled-back transaction; head `005`; 18 tables)
- `scripts/verify_phase6.py` -> **57/57** against the live PostgreSQL database
- Regressions: `verify_phase2.py` 27/27, `verify_phase3.py` 38/38,
  `verify_phase4.py` 9/9, `verify_phase5.py` 38/38 (live)
- `scripts/verify_frontend_flow.py` -> **90/90** against a running server
- `npx vite build` -> clean (24 modules, ~326 kB JS)
- Browser check of the new UI on `/products/16/versions/30`: the IP route map,
  patent screening (4 records, feature table with match/different/unknown),
  biodiversity/ABS screen and TK screen all render; only the two expected
  session-probe 401s appear in the console.

### Issues Found and Fixed

1. **Backend would not start: `hf_token` not permitted.** `Settings` had no
   `hf_token` field, so the `HF_TOKEN` in `.env` raised `extra_forbidden` on
   every import. Added the optional field and documented it in `.env.example`.
   (This also means the token is now a first-class, typed setting.)
2. **`verify_phase5.py` hard-coded revision `004` and the phase-5 health
   string.** Both moved with this phase. It now reads the head revision from the
   migration scripts and accepts "phase 5 or later".
3. **`verify_migrations.py` expected 16 tables.** Updated to 18.
4. **Frontend: `Products` delete handler called an undeclared `setError`.** A
   failed delete threw a `ReferenceError` instead of showing the message. Added
   the missing state and rendered it (and dropped the dead `<span id="err-..">`).

### Remaining Issues

- The demonstration patent corpus is illustrative. A real source (for example a
  live public-records feed) would replace `app/data/patent_demo_corpus.py` and
  flip `retrieval_mode` to `LIVE_SOURCE`; the comparison, labelling and safety
  layers would not change.
- Screening results are not cached: each screening writes a new `analyses` row,
  as in Phase 5.
- The browser check and the flow script both leave throwaway accounts/products in
  the live database (`buffi6@example.com` / `buffipass123` and `fe-verify-*`).
  They can be deleted with `scripts/clean_db.py` or by hand.

### Next Step

Phase 7 - the formulation change-impact simulator (`POST /api/products/{id}/change-impact`),
comparing two versions and surfacing review questions.

---

## Entry: 2026-09-24 15:18 IST

### Phase: 12 (frontend) - fixing the login / register flow

### Task: Make registration and login actually work from the test UI

### Starting Point Found

The test UI could not get past its first screen. Registering reported
`res.json is not a function` in the browser, and the server logged
`POST /api/auth/register` and `POST /api/auth/login` as **422 Unprocessable
Content**. The failures came from four separate defects that were stacked on top
of each other, so each one had to be removed before the next became visible:

1. **`fetch()` promises were passed to `parseResponse` instead of `Response`
   objects.** `parseResponse(res)` did `await res.json()`, but every caller
   handed it `fetch(...)` - an unresolved `Promise`, which has no `.json`
   method. This produced the reported `res.json is not a function`. It affected
   `register`, `login`, `me` **and every `authFetch` call**, so the entire UI was
   unusable; login was simply the first screen that hit it.
2. **Auth bodies were sent as form data.** `register`/`login` posted
   `new URLSearchParams(body)` with `content-type: application/x-www-form-urlencoded`,
   but the endpoints take Pydantic models (`UserCreate`, `UserLogin`) and
   therefore require a JSON body - hence the 422s.
3. **The register payload used the wrong field name.** The form held
   `cpassword` while the schema requires `confirm_password`, so a JSON register
   call would still have been rejected with 422.
4. **The session-restore probe was a credential-less login.** `AuthProvider`
   called `api.login({ email: "", password: "" })` on mount "to check the
   session", which is why the server also logged a login 422 on every page load.
   It could never restore anything: an empty login is invalid by construction, and
   the access token was only ever kept in memory.

A fifth, unrelated defect surfaced while testing: nested `<Routes>` were mounted
under the outer `<Route path="/">`. React Router warned that the parent would stop
matching on deeper URLs - and it did: a direct visit to `/products`, `/knowledge`
or `/chat` rendered a blank page.

### What Was Implemented

**`FRONTEND/src/App.jsx`:**

- `parseResponse` now `await`s its argument, so it accepts either a `fetch()`
  promise or a resolved `Response`, and it checks that the value really is a
  response before reading it. It also parses the body defensively (a
  non-JSON error body no longer throws a parse error instead of the real one).
- New `detailOf()` helper: FastAPI's validation errors arrive as a list of
  `{loc, msg}` objects. They are now collapsed into one readable line such as
  `confirm_password: Field required` instead of `[object Object]`.
- New `postJson()` helper; `register` and `login` now send JSON, and `register`
  maps the form state onto the schema's `confirm_password` field explicitly.
- New `api.refresh()` calling `POST /api/auth/refresh`; `AuthProvider` uses it on
  mount to restore a session from the httpOnly refresh cookie that login sets,
  and only adopts the token after `/auth/me` confirms it. A page reload now keeps
  the user signed in.
- `logout` switched from `GET` to `POST /api/auth/logout` (the route is POST-only,
  so logging out previously returned 405).
- The register form validates the 8-character minimum client-side, so the
  requirement is visible before the request is sent.
- Outer route changed to `path="/*"` so deep links render.
- `Button` now forwards `type`, so `type="button"` buttons such as *Cancel* no
  longer submit the form they sit in.

### Tests Executed

- `npx vite build`: clean, 0 errors (24 modules, 316.35 kB JS)
- Manual browser round trip against the live backend (`127.0.0.1:5173` -> `:8000`):
  - `POST /api/auth/register` -> **201**, UI reported "Account created" and
    redirected to `/login`
  - `POST /api/auth/login` -> **200**, `GET /api/auth/me` -> **200**, home page
    showed `Signed in as bufficheck@example.com`
  - full page reload -> `POST /api/auth/refresh` -> **200**, session restored
    without a new login
  - `/products` and `/knowledge` deep links render and their authenticated API
    calls return 200 (`GET /api/products`, `GET /api/knowledge/documents`,
    `GET /api/knowledge/status`); no `res.json is not a function` and no React
    Router warning in the console

### Design Decisions

1. **Fix the shared helper, not the two call sites.** The promise/`Response` bug
   was in the one function every request goes through, so the fix restores the
   whole app rather than only the login screen.
2. **Restore the session through the refresh endpoint instead of keeping the
   token in `localStorage`.** The backend already issues an httpOnly refresh
   cookie scoped to `/api/auth`; using it keeps the access token out of
   JavaScript-accessible storage.
3. **Keep the browser-visible error text faithful.** Validation errors are
   rendered with the offending field name, because a 422 shown as a generic
   failure hides exactly the information needed to fix the request.

### Files Modified

- `FRONTEND/src/App.jsx`
- `PROJECT_STATUS.md`
- `TODO.md`
- `DEVELOPMENT_LOG.md`
- `BACKEND/README.md`

### Next Step:

Phase 6: IP route map, patent screening, biodiversity / ABS and TK screening.

---

## Entry: 2026-09-23 01:20 IST

### Phase: 5 (frontend) - connecting the analysis features to the test UI

### Task: Wire the Phase 5 analysis endpoints into the frontend and verify the wiring

### Starting Point Found

Phase 5's backend was complete and verified, but the frontend had **no analysis
integration at all**: the `api` client stopped at the Phase 4 assistant calls, and
the version detail page ended at target markets. Every Phase 5 feature was
reachable only through Swagger or a script. The Phase 12 test UI existed to make
manual checking possible, so an unconnected feature was effectively unchecked.

### What Was Implemented

**`FRONTEND/src/App.jsx`:**

- API client methods: `analyzeClaims`, `analyzeProduct`, `analyses` (with an
  optional `analysis_type` filter) and `analysisDetail`.
- An **Analysis section** on the version detail page, deliberately placed last so
the reviewer reads the content the analysis is based on first.
- Two run buttons: "Analyze claims" and "Full analysis (classification + claims)".
- A recorded-run picker (id, type, status, timestamp) so historical runs stay
  reviewable after a reload - analyses load on mount.
- Claim assessment cards showing the declared status next to the AI-suggested one,
  plus risk, review status, provenance, rationale and missing evidence.
- Citations rendered with their real source metadata and quoted passage.
- A distinct notice for `expert_verified_locked` claims, since those are the ones
  the AI refused to touch.
- Comprehensive extras: preliminary classification, target-market considerations,
  missing information, deferred later-phase components, recommendations and the
  warnings/disclaimers list.
- The chat message list now displays source provenance, which the Phase 5 API
  change added to the assistant response.
- New CSS for assessments, citations and the three notice styles.

### Design Decisions

1. **The UI states that analysis is advisory, next to the buttons.** The heading
   names the `content_hash` the run is pinned to, so it is visible that a result
   belongs to a specific version rather than to the product.

2. **Both outcomes are handled, not just the happy path.** A real run costs a
   model call, so a `503` (provider unavailable, a failed run recorded server-side)
   is displayed as an error *and* triggers a reload, which surfaces the recorded
   `failed` run in the picker. Without that, a failed run would be invisible.

3. **"Analyze claims" is disabled when there are no claims.** The backend returns a
   valid no-op analysis, but running it from the UI would be meaningless work.

4. **The run list is a picker, not a log.** Analyses are immutable per the backend
   design, so reviewing a past run is a read, and a select control is enough.

### Files Modified:

- `FRONTEND/src/App.jsx`
- `scripts/verify_frontend_flow.py` (Phase 5 section added; request helper now takes a timeout)
- `PROJECT_STATUS.md`
- `TODO.md`

### Tests Executed:

- `vite build`: clean (24 modules, 0 errors)
- `scripts/verify_frontend_flow.py`: **50/50** against a live server
- `pytest tests/`: 105/105 (unchanged; no backend code touched)

### Environment Finding Worth Recording

The first live analysis call did **not** return quickly: it triggered a HuggingFace
download of `BAAI/bge-m3` because the embedding model was not cached on this
machine. Retrieval is always the first expensive step of an analysis, so a cold
checkout pays that cost once. This is why the live run was subsequently verified
with the provider deliberately unavailable: the fail-fast ordering means a missing
`GROQ_API_KEY` is reported in milliseconds instead of after a multi-gigabyte
download, which is exactly the behaviour the UI's error path depends on. The
results path is covered by `scripts/verify_phase5.py` (37/37) with the model mocked.

### Next Step:

Phase 6: IP route map, patent screening, biodiversity/ABS/TK screening - which will
replace the `deferred_components` the analysis screen currently lists.

---

## Entry: 2026-09-23 00:10 IST

### Phase: 5 - IP-SAKTI Assistant (claim-to-evidence analysis, product analysis)

### Task: Implement the analysis workflows that consume the Phase 4 RAG stack

### Starting Point Found

Phase 4 gave the platform hybrid retrieval, citation validation and a Groq LLM
provider, but the only consumer was the chat endpoint. The `analyses` table and the
`Analysis` model had existed since Phase 2 and **nothing ever wrote to them**, and
the `POST .../claims/analyze` endpoint promised in the master prompt's Phase 3 API
surface did not exist. `PROJECT_STATUS.md` recorded it as deliberately deferred to
Phase 5.

### What Was Implemented

**Schema:**

- `CLAIM_ANALYSIS` added to the `analysistype` enum (migration `004`). Downgrade is
a documented no-op because PostgreSQL cannot remove an enum label; migration 002's
downgrade drops the whole type, so the chain still round-trips cleanly.

**New package `app/analysis/`:**

- `schemas.py` - separate LLM-output models (small, easy for a model to satisfy)
  and public result models (enriched server-side).
- `prompts.py` - the claim-review and classification system prompts plus the
  disclaimers, so the safety wording lives in exactly one reviewable place.
- `claim_analyzer.py` - the claim-to-evidence pipeline.
- `classifier.py` - preliminary product classification.

**Endpoints** (nested under an owned product version):

- `POST .../versions/{id}/claims/analyze`
- `POST .../versions/{id}/analyze`
- `GET  .../versions/{id}/analyses` (optional `analysis_type` filter)
- `GET  .../versions/{id}/analyses/{analysis_id}`

**Assistant:** the chat response now reports `product_id`, `product_version_id`
and `provenance` (`PUBLIC_SOURCE` / `USER_PROVIDED`), matching the response shape
in the master prompt.

### Design Decisions

1. **The AI can never promote a claim.** `clamp_ai_evidence_status()` caps an
   AI-suggested status at `partially_supported`; `supported` and `expert_verified`
   stay reachable only through human evidence review and the expert workflow. The
   model asking for `supported` is silently reduced to `needs_evidence` - a
   malformed or overreaching answer can only make the platform *less* confident.

2. **`EXPERT_VERIFIED` claims are locked.** They are returned with
   `expert_verified_locked: true`, their current status preserved, and a rationale
   stating the AI does not assess expert-verified information. The model's opinion
   of them is discarded entirely.

3. **The model may only cite what it was given.** A claim's citations are resolved
   by re-using the Phase 4 `validate_citations()` against that claim's retrieved
   passages, and metadata (title, source type, jurisdiction, page) is taken from
   the database, never from the model. An id the model invented is dropped and a
   warning says so.

4. **Analysis is advisory.** Running an analysis writes one new `analyses` row and
   mutates nothing else. That row is pinned to the `product_version_id` it reviewed
   and the audit entry records the version's `content_hash`, so a historical result
   can never be silently rewritten by a later version.

5. **An AI outage is a controlled failure.** If the provider is unreachable or the
   JSON cannot be validated, a `FAILED` analysis row is persisted for auditability
   and the caller gets a `503` explaining that a failed run was recorded. Nothing
   is fabricated. Correspondingly, the LLM provider is resolved *before* retrieval:
   there is no point paying for embeddings when the model is already known to be
   unavailable.

6. **Phase boundaries are stated, not hidden.** `POST .../analyze` lists the stages
   it does not yet perform (IP route map and patent screening, biodiversity/ABS and
   TK screening, public-disclosure review) in `deferred_components`, because the
   master prompt forbids presenting an unimplemented feature as working.

7. **Classification validates against our own vocabulary.** The model's category is
   checked against `ProductCategory`; an unrecognised category raises rather than
   silently entering the database. A classification failure degrades the
   comprehensive analysis (with a warning) instead of aborting the whole run.

### Files Created:

- `alembic/versions/004_claim_analysis_type.py`
- `app/analysis/__init__.py`
- `app/analysis/schemas.py`
- `app/analysis/prompts.py`
- `app/analysis/claim_analyzer.py`
- `app/analysis/classifier.py`
- `app/services/analysis_service.py`
- `app/routers/analysis.py`
- `tests/test_analysis.py`
- `scripts/verify_phase5.py`

### Files Modified:

- `app/models/analysis_models.py` (added `CLAIM_ANALYSIS`)
- `app/services/provenance.py` (`AI_MAX_EVIDENCE_STATUSES`, `clamp_ai_evidence_status`, `AI_ANALYSIS_PROVENANCE`)
- `app/services/__init__.py`
- `app/routers/__init__.py`
- `app/routers/assistant.py` (product context echo + source provenance)
- `app/main.py` (router registration, health phase 5)
- `scripts/verify_migrations.py` (head revision now read from the scripts; Phase 4 tables included in the expected set)
- `PROJECT_STATUS.md`
- `TODO.md`
- `DEVELOPMENT_LOG.md`

### Tests Executed:

- `pytest tests/`: **105/105 passed** (16 new in `tests/test_analysis.py`)
- `scripts/verify_phase5.py`: **37/37** checks passed against live PostgreSQL
- `scripts/verify_migrations.py`: full downgrade + upgrade chain verified transactionally at head `004`
- `scripts/verify_phase2.py`: 27/27, `scripts/verify_phase3.py`: 38/38, `scripts/verify_phase4.py`: 9/9 (no regressions)

### Bug Found During Verification

The first run of `tests/test_analysis.py` hung. The LLM-outage test patched the
provider but not retrieval, so the real embedding model was loaded and the process
stalled. The fix was not just in the test: `analyze_claims_content()` now resolves
the LLM provider *before* retrieving passages, so an unavailable provider fails fast
instead of after expensive embedding work. This is a real latency/cost improvement,
not a test workaround.

### Next Step:

Phase 6: IP route map, patent screening, patent feature comparison and
biodiversity/ABS/TK screening - which is also what will fill in the
`deferred_components` that `POST .../analyze` currently reports as missing.

---

## Entry: 2026-09-22 15:50 IST

### Phase: 3 - Ingredients, Formulation, Claims, Evidence, Provenance

### Task: Implement version content CRUD with provenance tracking and hash refresh

### Starting Point Found

The database tables and Pydantic schemas for ingredients, formulations, claims,
evidence and target markets already existed from Phase 2, but **nothing wrote to
them**. There were no routers, no services and no tests. Phase 3 had to build the
write/read paths and the integrity rules around them.

### What Was Implemented

**Nested content routes** under `/api/products/{product_id}/versions/{version_id}`:

- `GET/POST/PUT/DELETE .../ingredients[/{id}]`
- `GET/PUT .../formulation` (one per version; PUT merges fields)
- `GET/POST/PUT/DELETE .../claims[/{id}]`
- `GET/POST/GET .../evidence[/{id}]` plus `PUT .../evidence/{id}`
- `GET/POST/PUT/DELETE .../target-markets[/{id}]`

### Design Decisions

1. **One place for authorization.** `get_accessible_version()` checks the product
   first, then constrains the version query to that product. A version id from
   someone else's product is therefore unreachable, and every child lookup is
   additionally scoped by `product_version_id`, so an id from a sibling version
   also returns 404.

2. **The server owns provenance.** No request schema accepts `provenance`; new
   rows are stamped `USER_PROVIDED` by `apply_user_provenance()`. This is the
   claim-to-evidence firewall: a user typing "increases bioavailability by 40%"
   produces a `USER_PROVIDED` claim, never a verified one.

3. **Verified data is protected.** `ensure_mutable()` raises 409 for any row whose
   provenance is `EXPERT_VERIFIED`, so the future expert workflow (Phase 9) owns
   those records. Tested by promoting a row directly in the DB, then asserting the
   API refuses to edit or delete it.

4. **Evidence status is a conclusion, not an assertion.** A user may create a
   claim with status `user_provided` or `needs_evidence` only; anything else
   (e.g. `supported`) is rejected with 422. Likewise, evidence may be reset to
   `pending` but never promoted to `verified` through a user endpoint.

5. **Every edit refreshes integrity fields.** Each mutation commits, then calls
   `refresh_version_snapshot()`, then writes an audit entry that records the
   resulting `content_hash`. Because the hash covers content only, an inherited
   or cloned version has the same hash until its content genuinely differs - the
   property Phase 7's change-impact comparison relies on.

6. **Versions remain independent.** Editing version 2 does not change version
   1's stored hash; both the pytest suite and the real-database script assert it.

### Files Created

- `app/services/provenance.py` - provenance values, `USER_PROVIDED` stamping, `EXPERT_VERIFIED` / evidence-status guards
- `app/services/version_content_service.py` - CRUD for all five content types, snapshot refresh + audit on every write
- `app/routers/version_content.py` - the nested REST surface
- `tests/test_version_content.py` - 21 tests (CRUD, hash refresh, firewall, isolation, nested authorization, audit)
- `scripts/verify_phase3.py` - 38-check end-to-end run against the real PostgreSQL database, self-cleaning

### Files Modified

- `app/utils/authorization.py` + `app/utils/__init__.py` - added `get_accessible_version()`
- `app/schemas/product_schemas.py` - `ClaimCreate` gains `evidence_status`/`evidence_notes`; evidence `publication_date` is a real `date`
- `app/routers/__init__.py`, `app/main.py` - register the new router
- `app/services/__init__.py` - export the new services
- `PROJECT_STATUS.md`, `TODO.md`, `README.md` - Phase 3 status and endpoints

### Tests Executed

- `pytest tests/ -q` -> **67 passed** (was 46; +21 Phase 3 tests)
- `scripts/verify_phase3.py` -> **38/38 checks passed** against the real PostgreSQL database, then cleaned up its temporary users and product

### Bugs Discovered

None in the application code. One bug was found and fixed in the verification
script itself: it compared version 1's hash against a value captured before
several later version-1 edits, which produced a false failure. The check now
captures the hash immediately before editing version 2.

### Deliberately Deferred

- `POST .../claims/analyze` (in the master prompt's Phase 3 list) needs the AI/RAG stack - Phase 5.
- `evidence.document_hash` stays null until files are actually ingested - Phase 8.

### Next Step

Phase 4 - RAG ingestion: pgvector, document/chunk models, source management,
embeddings, hybrid retrieval and citation validation.

---

## Entry: 2026-09-22 16:20 IST

### Phase: 1-3 + frontend integration

### Task: Add a minimal React frontend to exercise the API end to end

### Starting Point Found

A React + Vite skeleton already existed at `IP-SHAKTI/FRONTEND` (template code),
and the backend already exposed all Phase 1-3 routes at `/api`. Nothing wired
them together yet.

### What Was Done

1. **Auth API paths corrected to `/api/auth/...`.** The template used `/auth/...`.
2. **API base set to the same origin (`""`)** so dev and build both proxy to the
   backend without CORS bits.
3. **Template UI replaced** with a minimal, self-contained app that covers the
   exact flow the API needs for testing:
   - Register / log in (Phase 1)
   - Product list, new product, version list, new version (Phase 2)
   - Version detail with inline forms for **ingredients, formulation, claims,
     evidence, target markets** (Phase 3)
4. **End-to-end verification** via `scripts/verify_frontend_flow.py`: register,
   log in, create a product, list versions, add ingredient + formulation + claim +
   evidence + target market, read the version detail (all collections + 64-char
   hash present), and confirm the ownership boundary (401 on a bogus token).
   Result: **36/36 checks pass** against the live backend.
5. **Temporary account cleaned up** (5 abandoned verify-user rows removed).

### Files Created / Modified

- `IP-SHAKTI/FRONTEND/src/App.jsx` - rewritten: auth provider, login, register,
  products list, new product form, versions list, new version form, version
  detail with all Phase 3 inline editors
- `IP-SHAKTI/FRONTEND/src/main.jsx` - unchanged (kept)
- `IP-SHAKTI/FRONTEND/src/App.css`, `index.css` - left as-is (not used by the
  new inline-style layout)
- `IP-SHAKTI/PROJECT_STATUS.md` - frontend now `IN_PROGRESS` under Phase 12
- `IP-SHAKTI/DEVELOPMENT_LOG.md` - new entry + Phase 3 entry timestamp updated
- `IP-SHAKTI/TODO.md` - Phase 12 partially checked
- `IP-SHAKTI/BACKEND/scripts/verify_frontend_flow.py` - new end-to-end walkthrough

### Notes

- The frontend uses inline styles only, so it stays a single file for now.
- `document.documentElement.clientWidth` etc. are not used; the layout is a simple
  flex column with a nav rail and a max-width main.
- The frontend is intentionally minimal: enough to test the API, not a product
  UI. Phase 12 will revisit it as a real app.

### Next Step

Phase 4 - RAG ingestion: pgvector, document/chunk models, source management,
embeddings, hybrid retrieval and citation validation.

---

## Entry: 2026-09-22 15:25 IST

### Phase: 2 - Product Passport and Versioning

### Task: Verify Phase 2, close its gaps, and mark it VERIFIED

### Starting Point Found

The Phase 2 code was written on 2026-09-21 but never verified:

- `PROJECT_STATUS.md` said `PHASE 2 - IN_PROGRESS`, `TODO.md` had every Phase 2 box unchecked
- `DEVELOPMENT_LOG.md` had **no Phase 2 entry at all**
- `PHASE2_SUMMARY.md` claimed "content hashing for integrity" and "immutable snapshots", but `snapshot_data` and `content_hash` were never written by any code path
- No tests existed for version isolation, ownership boundaries, or content hashes

### Bugs Discovered and Fixed

1. **Missing ownership checks (IDOR).** `GET/PUT/DELETE /api/products/{id}`, the passport, and every version route only required a valid token. Any logged-in user could read, modify or delete another user's product.
   *Fix:* `app/utils/authorization.py` with `get_accessible_product()` (owner or ADMIN, otherwise 404 so ids are not leaked). Every product route now goes through it.

2. **Snapshot/content-hash fields were never populated.** The documented integrity feature did not exist.
   *Fix:* `app/services/version_snapshot.py` builds a canonical JSON snapshot of a version's content and hashes the content with SHA-256. `refresh_version_snapshot()` is called on create, clone and metadata update, and is available to Phase 3 content endpoints.

3. **`Base.metadata.create_all()` ran on every app startup.** This bypassed Alembic (schema drift) and, because `TestClient` triggers startup, every pytest run connected to the remote Supabase database and created tables there. It also made the suite ~2.4x slower.
   *Fix:* removed from `app/main.py`; Alembic alone owns the schema. Test suite time dropped from 127s to 53s and tests no longer touch the real database.

4. **`PUT /api/products/{id}/versions/{version_id}` was missing** although the master prompt requires it.
   *Fix:* implemented as a metadata-only update (change reason); content stays immutable from that route.

5. **`GET /versions` and `GET /versions/{id}` returned empty/foreign data for unknown products.**
   *Fix:* `get_version()` now takes an optional product scope and raises 404; `get_versions()` verifies the product first.

6. **`ProductVersionDetail` used mutable list defaults (`= []`)** - a classic Pydantic footgun that shares one list between instances.
   *Fix:* `Field(default_factory=list)`.

### Features Added

- `POST /api/products/{id}/versions/{version_id}/clone` - deep-copies ingredients, formulation, claims, evidence and target markets into a new version
- New versions inherit the current version's content by default (`start_empty: true` for a blank version), which is what makes the "change cultivated -> wild, create version 2" demo flow usable
- `PUT /api/products/{id}/passport` - passport-level metadata update
- ADMIN users can list all products; everyone else only sees their own

### Files Created

- `app/utils/authorization.py` - ownership/RBAC helpers
- `app/services/version_snapshot.py` - canonical snapshot + SHA-256 content hash
- `tests/test_product_versions.py` - 22 tests (hashes, isolation, ownership, clone, metadata update)
- `scripts/verify_phase2.py` - end-to-end smoke test against the real database, self-cleaning
- `scripts/verify_migrations.py` - migration chain check inside a rolled-back transaction
- `docker-compose.yml` - PostgreSQL 16 + pgvector on port 5433 for local development

### Files Modified

- `app/services/product_service.py` - rewrite: ownership checks, transactional product+version creation, real snapshots, version update/clone, content copying
- `app/routers/products.py` - rewrite: ownership enforcement, new endpoints, removed raw `HTTPException` duplication into services
- `app/schemas/product_schemas.py` - `ProductVersionCreate` (copy/empty), `ProductVersionUpdate`, `default_factory` fix
- `app/main.py` - removed `create_all` startup hook, replaced deprecated `on_event`, documented that Alembic owns the schema
- `app/utils/__init__.py`, `app/services/__init__.py` - exports
- `tests/conftest.py` - second-user fixtures for authorization tests
- `alembic/env.py` - supports an externally supplied connection (used for transactional verification)
- `README.md` - product/version endpoints, enum value format, migration safety, verification scripts
- `.env.example` - dropped a stray `[TEMPLATE]` first line

### ⚠️ Incident: schema dropped by an unsafe verification script

**What happened:** the first version of `scripts/verify_migrations.py` tried to isolate
the migration into a throwaway PostgreSQL schema using
`?options=-csearch_path=<schema>`. The Supabase connection pooler ignores that
startup parameter, so `alembic upgrade head` ran against `public` and the
following `alembic downgrade base` **dropped the 12 application tables from the
`public` schema**.

**Impact:** schema objects were lost; the only data lost was one previously
registered user account (all temporary verification rows had already been
deleted). The legacy `Clients` table was untouched. The `products`/`versions`
tables never held real data.

**Recovery:** `alembic upgrade head` recreated all 12 tables, `seed_roles.py`
re-seeded the 4 roles, and `verify_phase2.py` confirmed 27/27 checks pass again.
The incident also served as a genuine fresh-database initialisation test.

**Prevention:** the script was rewritten to run `downgrade base` and
`upgrade head` on ONE connection inside an explicit transaction, then ROLL BACK.
PostgreSQL has transactional DDL, so the database is provably unchanged
afterwards (the script asserts the table set is identical before and after).
It never uses the scratch-schema trick again, and the README warns that a bare
`alembic downgrade` commits destructive changes.

### Tests Executed

| Command | Result |
|---------|--------|
| `pytest tests/ -q` | **46 passed** (11 auth + 13 product + 22 version/authorization) |
| `python scripts/verify_phase2.py` | **27/27 checks passed** against `aws-0-ap-northeast-2.pooler.supabase.com` |
| `python scripts/verify_migrations.py` | downgrade base + upgrade head verified, rollback restored 14/14 tables |
| `alembic current` | `002 (head)` |

### Bugs Discovered (not yet fixed)

- API enum values are lowercase (`proprietary_ayurvedic`) while the PostgreSQL enum labels are uppercase (`PROPRIETARY_AYURVEDIC`). This is consistent (Pydantic validates and serialises values) but surprising; documented in the README.

### Remaining Issues

- Legacy pre-Phase-1 modules at the BACKEND root are still present (dead code)
- Version content is still mutable after an analysis completes (enforcement planned with the analysis phase)

### Next Step

Phase 3 - Ingredients, Formulation, Claims, Evidence, Provenance.

---

## Entry: 2026-09-21 21:10 IST

### Phase: 1 - Backend Foundation, Authentication, RBAC

### Task: Complete Phase 1 Implementation

### Files Created:
- `app/__init__.py` - App package init
- `app/main.py` - FastAPI application entry point
- `app/config.py` - Centralized configuration management
- `app/database.py` - Database connection and session management
- `app/models/__init__.py` - Models package
- `app/models/models.py` - SQLAlchemy models (User, Role, UserRole, AuditLog)
- `app/schemas/__init__.py` - Schemas package
- `app/schemas/schemas.py` - Pydantic schemas for all entities
- `app/routers/__init__.py` - Routers package
- `app/routers/auth.py` - Authentication endpoints
- `app/services/__init__.py` - Services package
- `app/services/auth_service.py` - Authentication business logic
- `app/services/audit_service.py` - Audit logging service
- `app/utils/__init__.py` - Utils package
- `app/utils/security.py` - Password hashing with bcrypt
- `app/utils/jwt_handler.py` - JWT token creation and validation
- `tests/__init__.py` - Tests package
- `tests/conftest.py` - Test configuration and fixtures
- `tests/test_auth.py` - Authentication endpoint tests
- `alembic/env.py` - Alembic environment configuration
- `alembic/script.py.mako` - Migration template
- `alembic/versions/001_initial_migration.py` - Initial database migration
- `scripts/seed_roles.py` - Script to seed default roles
- `.env.example` - Environment variables template
- `README.md` - Project documentation

### Files Modified:
- `requirements.txt` - Added all required dependencies
- `.env` - Updated with proper environment variable names

### What Was Implemented:

**1. Modular Project Structure:**
```
backend/
├── app/
│   ├── main.py          # FastAPI app
│   ├── config.py        # Configuration
│   ├── database.py      # DB connection
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── routers/         # API routes
│   ├── services/        # Business logic
│   └── utils/           # Utilities
├── alembic/             # Migrations
├── tests/               # Test files
└── scripts/             # Utility scripts
```

**2. Database Models:**
- User model with id, username, email, password_hash, is_active, timestamps
- Role model with enum (ADMIN, RESEARCHER, EXPERT, VIEWER)
- UserRole junction table for many-to-many relationship
- AuditLog model for tracking all user actions

**3. Pydantic Schemas:**
- APIResponse: Standardized response format for all endpoints
- UserCreate, UserLogin, UserResponse: User schemas
- Token, TokenPayload: JWT token schemas
- RoleBase, RoleCreate, RoleResponse: Role schemas
- AuditLogBase, AuditLogResponse: Audit log schemas

**4. Authentication Endpoints:**
- POST /api/auth/register - User registration with validation
- POST /api/auth/login - Login with JWT tokens
- POST /api/auth/refresh - Token refresh
- GET /api/auth/me - Get current user (protected)
- POST /api/auth/logout - Logout user

**5. Security Features:**
- bcrypt password hashing
- JWT access and refresh tokens
- Token expiration and validation
- Bearer token authentication

**6. RBAC Foundation:**
- 4 default roles: ADMIN, RESEARCHER, EXPERT, VIEWER
- Role assignment service
- Role checking methods

**7. Audit Logging:**
- Automatic logging of user actions
- IP address and user agent tracking
- Query methods for user and resource logs

**8. Alembic Migrations:**
- Initial migration for users, roles, user_roles, audit_logs tables
- Proper indexes and foreign keys

**9. Tests:**
- Test fixtures for database, client, user, roles
- Tests for registration (success, duplicate, password mismatch)
- Tests for login (success, invalid credentials)
- Tests for protected routes (valid token, no token, invalid token)
- Tests for logout

**10. Configuration:**
- Centralized settings using pydantic-settings
- Environment variable validation
- .env.example template

### Tests Status:
Tests created but not executed due to Python environment issue on system.
User needs to run: `pytest tests/ -v`

### Known Issues:
- Python not configured in system PATH
- Tests need to be executed by user

### Next Steps:
1. User should install dependencies: `pip install -r requirements.txt`
2. Run migrations: `alembic upgrade head`
3. Seed roles: `python scripts/seed_roles.py`
4. Run tests: `pytest tests/ -v`
5. Start server: `uvicorn app.main:app --reload`
6. Test API endpoints manually
7. Mark Phase 1 as VERIFIED
8. Begin Phase 2: Product Passport

---

## Entry: 2026-09-21 21:00 IST

### Phase: 0 - Repository Inspection

### Task: Inspect existing repository structure

### Files Inspected:
- `IP-SHAKTI/BACKEND/main.py` - FastAPI app with basic auth endpoints
- `IP-SHAKTI/BACKEND/models.py` - Basic Pydantic schemas
- `IP-SHAKTI/BACKEND/requirements.txt` - Dependencies
- `IP-SHAKTI/BACKEND/.env` - Environment configuration
- `IP-SHAKTI/BACKEND/databases/db.py` - SQLAlchemy setup
- `IP-SHAKTI/BACKEND/databases/dbmodels.py` - User model (Clients table)
- `IP-SHAKTI/BACKEND/hash/Hashing.py` - bcrypt password hashing
- `IP-SHAKTI/BACKEND/auth/authentication.py` - JWT token creation/validation

### What Was Found:

**Existing Implementation:**
- FastAPI backend with basic authentication
- PostgreSQL database (Supabase) configured
- SQLAlchemy ORM with declarative base
- User model: Clients (id, Username, Email, Password)
- JWT access/refresh token system
- bcrypt password hashing
- Basic Pydantic schemas for login/registration

**Endpoints Implemented:**
- POST /auth/register - User registration (Form-based)
- POST /auth/login - User login with JWT tokens
- POST /auth/refresh - Token refresh
- GET /auth/me - Protected route
- POST /auth/forgot-password - Placeholder
- POST /auth/reset-password - Placeholder
- GET /auth/logout - Cookie deletion

**Dependencies Installed:**
- fastapi[standard]
- uvicorn[standard]
- sqlalchemy
- pydantic
- pyjwt
- bcrypt
- python-dotenv
- psycopg2-binary

**Missing for Phase 1:**
- Alembic migrations
- Standardized API response format
- RBAC (roles/permissions)
- Audit logging
- Comprehensive tests
- Proper error handling
- .env.example
- Pydantic schema validation improvements
- Project state files

### What Was Implemented This Session:
- Created AGENTS.md
- Created PROJECT_STATUS.md
- Created DEVELOPMENT_LOG.md (this file)
- Created TODO.md

### Tests Executed:
None yet

### Bugs Discovered:
None yet

### Next Steps:
Begin Phase 1 implementation:
1. Add Alembic for migrations
2. Create standardized API response format
3. Enhance database models (add roles, audit logs)
4. Add RBAC foundation
5. Create tests
6. Verify all functionality

---

## 2026-09-22 18:30 IST - Phase 4: RAG Ingestion, pgvector, Hybrid Retrieval, Citations, Custom User Data & Frontend Integration

**Status:** VERIFIED

### What Was Implemented:
1. **Database & Migrations:**
   - Enabled `pgvector` PostgreSQL extension via Alembic migration `003_rag_pgvector.py`
   - Created `source_documents` table with SHA-256 deduplication and uploader scoping
   - Created `source_chunks` table with 1024-dim dense embedding support and PostgreSQL `tsvector` FTS index
   - Created `chat_sessions` and `chat_messages` tables for persistent conversation histories
   - Created dialect-aware column types (`EmbeddingType`, `TSVectorType`) ensuring 100% SQLite test compatibility alongside full PostgreSQL vector functionality

2. **Embedding & LLM Abstractions:**
   - Implemented `EmbeddingProvider` abstract base with `BGEM3Provider` (`BAAI/bge-m3`, 1024 dense dimensions)
   - Implemented `LLMProvider` abstract base with `GroqProvider` (`llama-3.3-70b-versatile` with JSON schema enforcement)
   - Configured Groq API key and settings in centralized `config.py` and `.env`

3. **RAG Pipeline (`app/rag/`):**
   - Document parsing: PyMuPDF for page-aware PDF text extraction; plain text parser
   - Chunking: 800-token chunks with 120-token overlap and sentence boundary preservation
   - Ingestion: End-to-end pipeline with SHA-256 deduplication, chunking, embedding, and tsvector generation
   - Hybrid retrieval: Parallel vector search (`pgvector` cosine distance) and keyword search (PostgreSQL `ts_rank_cd`), fused via Reciprocal Rank Fusion (RRF)
   - Reranking: Cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) with graceful RRF fallback
   - Citation validation: Strict validation requiring every cited `chunk_id` to exist in the retrieved candidate set
   - Hallucination prevention: Returns controlled `"Insufficient evidence in the current verified corpus."` response whenever evidence is missing

4. **User-Uploaded Custom Data ("Add your own data"):**
   - Users can upload private documents (PDF/TXT)
   - The RAG chatbot searches both the verified public regulatory corpus and the user's private documents
   - Admin users can mark documents as public to expand the system corpus

5. **APIs & Routers:**
   - Knowledge Base (`/api/knowledge`): document upload, listing, detail, deletion, re-indexing, and corpus status
   - RAG Assistant (`/api/assistant`): chat endpoint with citation tracking, conversation sessions CRUD, optional Product Passport context injection

6. **Frontend Integration:**
   - Added Knowledge Base page (`/knowledge`) with corpus statistics, upload form, and document management
   - Added RAG Assistant Chat page (`/chat`) with session management, citation cards (with exact quoted passages), insufficient-evidence notices, and product context selector
   - Configured Vite proxy and verified production build with zero errors

### Files Created:
- `alembic/versions/003_rag_pgvector.py`
- `app/models/rag_models.py`
- `app/embeddings/__init__.py`
- `app/embeddings/base.py`
- `app/embeddings/bge_m3_provider.py`
- `app/embeddings/provider.py`
- `app/llm/__init__.py`
- `app/llm/base.py`
- `app/llm/groq_provider.py`
- `app/llm/provider.py`
- `app/llm/schemas.py`
- `app/rag/__init__.py`
- `app/rag/schemas.py`
- `app/rag/parser.py`
- `app/rag/chunking.py`
- `app/rag/ingestion.py`
- `app/rag/vector_search.py`
- `app/rag/keyword_search.py`
- `app/rag/reranker.py`
- `app/rag/retrieval.py`
- `app/rag/citation.py`
- `app/rag/generation.py`
- `app/routers/knowledge.py`
- `app/routers/assistant.py`
- `scripts/ingest_corpus.py`
- `scripts/verify_phase4.py`
- `tests/test_rag.py`

### Files Modified:
- `app/config.py`
- `app/main.py`
- `app/models/__init__.py`
- `app/routers/__init__.py`
- `app/utils/__init__.py`
- `app/utils/authorization.py`
- `requirements.txt`
- `.env`
- `.env.example`
- `FRONTEND/vite.config.js`
- `FRONTEND/src/App.jsx`
- `PROJECT_STATUS.md`
- `TODO.md`
- `DEVELOPMENT_LOG.md`

### Tests Executed:
- `pytest tests/`: 89/89 passed (0 failures)
- `scripts/verify_phase4.py`: 9/9 live PostgreSQL + pgvector checks passed
- `npm run build` in `FRONTEND`: built cleanly with 0 errors

### Next Step:
Phase 5: IP-SAKTI Assistant (expanded analysis workflows, claims analysis `POST /claims/analyze`, structured recommendations).

> Superseded by the 2026-09-23 Phase 5 entry above.

---

## 2026-09-26 — Frontend Design Pass: Knowledge Base page, shell layout, ghosted-heading fix

### Changes
- `FRONTEND/src/index.css` (root cause fix):
  - `color-scheme` pinned to `light`; heading/text tokens retinted to the cream palette (`--text-h: #1C2420`, `--text: #5B6670`).
  - Dark-scheme variable overrides are now opt-in via `:root[data-theme="dark"]` instead of
    `@media (prefers-color-scheme: dark)` — OS dark mode no longer repaints h1/h2 near-white
    over the light cards (the "invisible/ghosted heading" bug reported on /knowledge, /reviews).
  - `#root` 1126px centred cage, `text-align: center` and inline border removed at source.
- `FRONTEND/src/App.jsx`:
  - Knowledge Base page rebuilt: page header (brass eyebrow + serif h1), 5-tile stat row,
    custom dashed file-picker control, responsive 2-column upload form, document rows with
    title on its own line + chip row (`source · jurisdiction · visibility · status · chunks`),
    right-aligned Re-index/Delete actions.
  - Text rectification: "official_guidance" → "Official Guidance" (Badge now prettifies
    enum values), status chips read "Indexed · 10 chunks", dates render "25 Sep 2026",
    button labels de-jargonised ("Upload & index document" / "Uploading & indexing…").
  - Global premium styling in app stylesheet: warm-white cards with serif titles, pill buttons
    (deep-green primary, outlined danger), uppercase micro-labels on form fields, pill badges,
    hover-lifted list rows, tabular stat numerals.
  - App shell: collapsible left sidebar (Products, Knowledge Base, RAG Assistant, Reviews,
    Dashboard, Live Demo) with hover-lift links, brand + collapse toggle, and a profile block
    at the base holding the sign-out action; top tab bar removed. Home header shows the
    registration username (not email) with a looser type rhythm.
  - Home `.hm` full-bleed breakout (`width: 100vw; margin-left: calc(50% - 50vw)`) removed —
    it painted over the new sidebar and caused horizontal scroll after the shell went full-width.

### Verification
- `vite build`: ✓ built cleanly (360 ms).
- UTF-8 integrity of `App.jsx` and `index.css` re-checked after every write (previous sessions
  had ANSI-encoding corruption from PowerShell round-trips).
- No backend code touched; phase verification status unchanged (all phases remain VERIFIED).


## 2026-09-26 (later) - Premium pass: Chat, Reviews, Dashboard, Demo pages + text rectification

### Changes
- Reviews (/reviews): page header (brass eyebrow, serif h1, sub), .rv-form grid of labeled
  fields replacing the bare native selects, review queue rendered as hover-lifted clickable row
  cards (#id chip + status badge + product/version meta), selected-review card title prettified
  (Review #1 - Submitted), comment cards, pill comment input, actions row. Removed "(Phase 9)"
  jargon from visible copy. Shared prettify() helper added and reused by Badge.
- Dashboard (/dashboard): removed "(Phase 10)" jargon; page header; pipe-separated count lines
  converted to a 6-tile stat grid (Product passports, Tracked versions, Reviews awaiting action,
  Analyses run, Claims needing evidence, Patent records); recent disclosures/activity lists
  converted to row cards with badges, prettified action/resource labels, guarded timestamps.
- Demo (/demo): intro card content moved into a shared page header; three numbered cards and
  their order preserved; "Judge Walkthrough" phrasing dropped from visible copy.
- Chat (/chat): Button component now forwards the style prop (the New Chat button silently lost
  width:100% before); layout moved to .chat-grid with responsive stack; session list restyled
  (deep-green active pill, hover lift, contrast-safe delete buttons); context labels/selects
  de-cramped to shared .field styles; thread, empty state, bubbles, notice, citations, typing
  indicator and input row moved from teal-era inline colors to the cream + deep-green palette;
  citation source_type enums prettified (official_guidance -> Official Guidance); jargon reduced
  (Verified Sources & Citations -> Sources & citations, "(Verified RAG)" dropped from author
  label, loading/notice copy rewritten in plain language).
- Demo components: FormulationRiskDashboard - card padding dedup, redundant inner h2 removed,
  fields converted to shared .field styling, banner border 2px->1px, disclaimer contrast
  #9ca3af -> #6B7280, risk label colors darkened to AA-passing shades (#dc2626->#b91c1c,
  #d97706->#b45309, #16a34a->#15803d). ProtectionTimeline - palette-matched borders/circles,
  darker column headers, serif closing statement, ghost pill replay button, same color
  darkening. IPRiskMap - cream map container and tooltip, palette colors, removed the
  non-functional "View on Google Patents" tooltip line (it implied a link that does not exist;
  node data is illustrative).
- Shared CSS: .pg-head/.pg-eyebrow/.pg-h1/.pg-sub page headers, .dash-stats, .row-item/.row-id/
  .row-meta rows, .rv-* review styles, .input-line pill input, .chat-* suite, .demo-fields
  reset; <=1000px rules stack the chat grid, review form and dashboard stats.

### Verification
- vite build: built cleanly (594 modules, 379 ms).
- Strict UTF-8 decode of App.jsx, FormulationRiskDashboard.jsx, ProtectionTimeline.jsx,
  IPRiskMap.jsx - all OK after writes.
- No backend code touched; all phases remain VERIFIED.

---

## 2026-09-26 — Gap closures: three missing endpoint groups + Protection Timeline moved to landing

### Backend — master-prompt section 7 endpoints that were missing
- Added `app/routers/sources.py`: `GET /api/sources`, `GET /api/sources/search`,
  `GET /api/sources/{id}` — authenticated, read-only; visibility = public documents
  plus caller's own (ADMIN sees all); responses never expose `file_path` /
  `document_hash`; `/search` declared before `/{source_id}` so the literal path
  matches first; invisible documents return 404 (no existence leak).
- Added `app/routers/users.py`: `GET /api/users/me`, `PUT /api/users/me`
  (username/email only — roles, password and `is_active` are not writable;
  email conflict -> 409; changes audit-logged as `update_profile`),
  `GET /api/users/me/history?limit=` (caller's own audit entries via
  `AuditService.get_user_logs`, never other users' entries).
- Extended `app/routers/knowledge.py` with `POST /api/knowledge/index`: re-runs
  ingestion for PENDING/FAILED documents (own uploads; ADMIN = whole corpus);
  records without a file on disk counted as `skipped`, never silently ignored;
  response reports `attempted` / `indexed` / `failed` / `skipped` honestly.
- Registered both routers in `app/routers/__init__.py` and `app/main.py`
  (OpenAPI 74 -> 80 paths).
- Tests first: new `tests/test_gap_endpoints.py` — 23 tests covering visibility
  rules, 401s, privilege-safety, email conflict, history scoping, and index
  scoping/counts. Full suite: **226 passed** in 131.8s (was 203).
- Live E2E: `scripts/verify_frontend_flow.py` extended by 12 gap-closure checks
  — **139 passed** against the live server + Supabase (was 127).
- Backend server restarted once: the running process predated the new routes
  (no `--reload`), and it later died on a transient DNS blip to the Supabase
  host (`getaddrinfo failed`) — network issue, not code; restarted cleanly.
- README: added Knowledge base, Sources and Users endpoint sections (knowledge
  endpoints were previously undocumented).

### Frontend — Protection Timeline moved from /demo to the landing page
- Removed card "2 · Before / After Protection Timeline" from `DemoShowcase`;
  card 3 renumbered to "2 · Live IP Risk Map"; page intro now says two
  visuals; home quick-action text changed to "Risk dashboard and IP risk map."
- `ProtectionTimeline` import moved App.jsx -> Landing.jsx; new section
  `#timeline` inserted directly below "How it works" (kicker "Protection
  timeline", serif h2 "Four minutes of foresight, or eighteen months of work
  lost."); the component itself is unchanged — subtitle, columns, closing line
  and Replay Animation button all intact.
- vite build: clean (594 modules, 535 ms).

### API keys / voice — findings (asked user for keys)
- Master prompt requires `LLM_API_KEY` (GROQ — already set in `.env` and
  working), `BHASHINI_API_KEY` / `BHASHINI_BASE_URL` (slots present, empty —
  client degrades honestly), and marks voice (`speech_to_text` /
  `text_to_speech`) **optional** ("Text first. Voice is optional.").
- The word "Sarvam" appears nowhere in the master prompt or codebase (only an
  incidental corpus word "Sarvamaya"). No voice/speech endpoints exist in the
  backend yet — voice would be new work on top of the keys.

## 2026-09-26 (evening) - API keys wired: GROQ primary -> Sarvam fallback for normal chat

### What was asked
- User provided fresh keys: GROQ (primary) and Sarvam (fallback for normal
  chatbot responses). Bhashini key still pending - reserved for voice
  (speech-to-speech, text-to-speech, speech-to-text), built once it arrives.

### LLM fallback - real wiring (not a mock)
- `app/llm/sarvam_provider.py` (new): `SarvamProvider` on the official
  `sarvamai` SDK (Chat Completions V1), model `sarvam-105b-conversations`
  (configurable via `SARVAM_MODEL`), JSON mode (`response_format=json_object`),
  thinking off (`reasoning_effort=None`), temperature 0.1, max_tokens 4096.
- `app/llm/fallback.py` (new): `FallbackLLMProvider(primary, fallback)` - tries
  the primary, and on any exception retries once against the fallback; if both
  fail it raises one honest error naming the fallback while chaining the
  primary cause. `supports_structured_output()` delegates to the primary.
- `app/llm/provider.py`: factory stays `lru_cache`d; the primary built from
  `LLM_PROVIDER` is wrapped in `FallbackLLMProvider -> SarvamProvider` only
  when `SARVAM_API_KEY` is non-empty (whitespace-only counts as unset), so
  behaviour without the key is unchanged.
- `app/config.py`: new `sarvam_api_key` / `sarvam_model` settings. `.env`
  gained `SARVAM_API_KEY` / `SARVAM_MODEL`; the key stays in `.env`, protected
  by the new `BACKEND/.gitignore` - never committed, never printed.
- `requirements.txt`: added `sarvamai>=0.1.34` (already installed);
  `.env.example` documents both new variables.

### Tests (before marking anything verified)
- New `tests/test_llm_fallback.py` - 10 tests: primary-first behaviour,
  fallback on primary failure, honest both-fail error with chained cause,
  structured-output delegation, Sarvam request shape (model, messages, JSON
  mode, reasoning off) via an injected fake client (no network), error
  propagation, and factory wrap / no-wrap / whitespace-only cases
  (`lru_cache` cleared around each).
- Full suite: **236 passed** in 137.7s (was 226).

### Live probes (real APIs, temp scripts - not committed)
- Probe 1 - primary path: factory provider (GROQ wrapped with Sarvam)
  answered live with `{"ok":true}`.
- Probe 2 - fallback path: primary swapped for an exploding stub, the same
  wrapper answered live via Sarvam with `{"ok": true}` (log line "Primary LLM
  failed (simulated primary outage); trying sarvam provider" confirms the
  switch happened).
- Earlier smoke scripts still green: `scripts/sarvam_smoke.py` (reply from
  `sarvam-105b-conversations`) and `scripts/groq_smoke.py` (HTTP 200).

### Live end-to-end
- Backend restarted so the new `.env` and code load (the old process
  predated both).
- `POST /api/assistant/chat` over HTTP as a fresh user: 200, non-empty LLM
  answer, session 19 / message 49, honest insufficient-evidence +
  disclaimer warnings (the temp user has no documents - correct behaviour).

### Docs
- README: new "Provider fallback" paragraph under the LLM notes and a
  fallback line in the Assistant section; `.env.example` covers
  `SARVAM_API_KEY` / `SARVAM_MODEL`.

### Still open
- Bhashini key pending -> voice endpoints not built yet (per user: build
  later, after the key arrives).

## 2026-09-26 (night) - Chat page: full-bleed layout + text rectification

### User request (with screenshot of /chat showing large empty margins)
- Fill the empty space by extending the page in every direction.
- Rename the chat heading "RAG assistant" -> "Talk to your personal AI assistance"
  (kept "New conversation" for the empty/new-chat state).
- Rename the sidebar tab label "RAG Assistant" -> "Chatbot".

### Changes (FRONTEND/src/App.jsx only; no backend impact)
- The app shell now adds `main-wide` on `/chat` only (via `useLocation`),
  dropping the shared 1280px cap and using 20/24px padding - every other page
  keeps its centred 1280px layout untouched.
- `.chat-grid` now stretches to `calc(100vh - 40px)` with `align-items:
  stretch` (was `align-items: start`), sidebar column widened 260px -> 300px.
- Left column (`chat-side`) became a flex column: the Conversations card
  grows and its session list scrolls internally; Context Options sits pinned
  below; the column itself scrolls on short viewports.
- Main column (`chat-main`) is flex: the card fills the column and the
  message thread got `flex: 1; min-height: 0`, replacing the old
  `min-height: 360px / max-height: 520px` cap - the thread now fills the
  screen; input row pinned at the bottom (`flex-shrink: 0`).
- Readability guard for the now-wide thread: message bubbles cap at
  `min(85%, 760px)` instead of 85% of an unbounded width.
- Stacked layout (<=1000px) drops the viewport lock (`height: auto`).

### Verification
- `npm run build`: green, 594 modules, 715ms (JSX + CSS compile clean).
- Visual check pending user screenshot (browser tool still disconnected);
  hard-refresh required.


---

## 2026-09-26 - Chat: PDF attachments, Groq/Sarvam toggle, voice, text cleanup

**Requested:** attach research PDFs in the chat and answer from them; remove
the chat heading/subtitle and the "You" / "IP-SAKTI Sahayak" bubble labels;
a toggle to switch answers between the Sarvam and Groq keys (default Groq,
animated); a voice button (speech in -> text, and every reply also spoken).

### Backend

- **New table `chat_attachments`** (model `ChatAttachment` in
  `app/models/rag_models.py`, Alembic migration `010_chat_attachments.py`
  `009 -> 010`, applied to the configured database). Stores the extracted text
  of an uploaded PDF with its owner, optionally bound to a chat session.
- **`POST /api/assistant/attachments`** (`app/routers/assistant.py`): accepts
  multipart `file` + optional `session_id`; validates extension, magic bytes
  (`%PDF`), empty files and the configured size limit (413); extracts text via
  the same PyMuPDF `parse_document` the knowledge base uses (temp file,
  always cleaned up); rejects corrupt/password-protected PDFs (400) and
  text-less scans with an honest "OCR is not available yet" message (400);
  caps stored text at `CHAT_ATTACHMENT_MAX_CHARS = 300_000` (`truncated` flag
  in the response).
- **Chat integration**: `ChatRequest` gains `attachment_ids` and
  `provider` (`Literal["groq","sarvam"]`, so junk values get 422). After the
  session is resolved, `_resolve_chat_attachments` verifies ownership (404),
  binds attachments to the session (400 if they belong to a different
  conversation) and reloads everything already bound to the session - so
  follow-up questions reuse the document without re-uploading.
  `_build_document_context` concatenates the documents capped at
  `CHAT_DOC_CONTEXT_CHARS = 100_000` characters and returns an honest
  truncation warning that is appended to the response warnings. Attached
  documents add `USER_PROVIDED` to `provenance`.
- **`app/rag/generation.py`**: `build_context_prompt` / `generate_rag_answer`
  take an optional `document_context`. The early "insufficient evidence" exit
  now fires only when there is neither corpus evidence nor an attachment; the
  attached document is injected as trusted context with explicit instructions
  (answer from it, keep citations empty, never invent chunk ids); an
  attachment-only answer skips corpus citation validation (nothing to validate
  against) and drops any hallucinated citations with a warning instead of
  hard-failing the answer.
- **Provider toggle**: `get_llm_provider_for(choice)` in
  `app/llm/provider.py` - `None`/`groq` returns the default chain (GROQ
  primary, Sarvam fallback), `sarvam` returns a strict `SarvamProvider` (an
  explicit selection must answer with the selected key, no silent failover),
  unknown choices raise. The chat router only consults it when
  `provider == "sarvam"`, preserving the existing default-path wiring/tests.
  `ChatResponse` echoes `provider`.

### Frontend (`FRONTEND/src/App.jsx`, one UTF-8-safe scripted pass, 13 edits)

- Removed the card heading "Talk to your personal AI assistance", its
  subtitle, and the "You" / "IP-SAKTI Sahayak" role labels above bubbles.
- **Toolbar**: animated `Groq | Sarvam` pill toggle (sliding knob,
  spring easing, selection persisted in `localStorage
  ipsakti_llm_provider`, default Groq) plus a spoken-replies speaker button
  (on by default).
- **PDF attach**: paperclip button (hidden file input, `accept=.pdf`) ->
  `POST /api/assistant/attachments` with `session_id` when active; filename
  chips with character counts, remove buttons, and a "Parsing PDF..." chip
  while uploading; chips are sent as `attachment_ids` and cleared on send,
  on new chat and on session switch. Errors surface through the existing
  error line (non-PDF, corrupt, text-less scan).
- **Voice** (browser built-in engines - works today without the pending
  Bhashini key): microphone button uses the Web Speech API
  (`SpeechRecognition`) in the active input language (`en`->`en-IN`,
  `hi`->`hi-IN`, `bn`->`bn-IN`) with interim transcripts filling the input,
  a pulsing listening state, and honest messages for unsupported browsers or
  blocked microphones; every assistant reply is spoken via
  `speechSynthesis` (matching voice when available) while the speaker
  button is on, and speech is cancelled when muting, switching to the mic,
  or starting a new reply.

### Verification

- `pytest -q`: **262 passed** (was 236; +21 in the new
  `tests/test_chat_attachments.py` covering extraction/validation/ownership/
  session reuse/provenance/provider routing/generation-with-document/context
  cap, +4 `TestGetLLMProviderFor` cases in `tests/test_llm_fallback.py`).
- `npm run build`: green (594 modules).
- Live HTTP against the restarted server (`live_chat_pdf_toggle.py`):
  **17/17 checks passed** - upload 201 (234 chars extracted), non-PDF 400,
  chat answered from the attached study ("The QUANTUM-73 marker reading was
  3.2 percent curcumin content."), `USER_PROVIDED` provenance, session
  follow-up answered from the bound document without re-attaching, strict
  `provider=sarvam` answered live through the Sarvam API, invalid provider
  422.
- Voice note: STT/TTS run entirely in the browser (Chrome Web Speech API +
  `speechSynthesis`), so no key was needed; when the Bhashini key arrives,
  server-side speech endpoints can be added alongside without changing this
  UI.

---

## 2026-09-27 - RAG over-abstention fix: selective/partial answering (master-prompt items 16-17)

**Requested:** multi-part questions were rejected wholesale ("Insufficient
evidence in the current verified corpus") even when some sub-parts were fully
supported. Fix: every sub-part supported by the uploaded PDF or the verified
corpus is answered; only unsupported sub-parts abstain.

### Root causes (proven against the live database)

1. `plainto_tsquery` AND-semantics: a typical query matched **0** chunks by
   ts_rank vs **618** when OR-ed (`ILIKE 'ashwagandha'` = 86 rows).
2. Dead vector arm: `sentence-transformers` was not installed - every
   retrieval logged "Embedding unavailable, using keyword search only".
3. `generate_rag_answer` early-exited on `[]` chunks with the global
   insufficient-evidence message (whole-question rejection).
4. One global `insufficient_evidence` flag + citation-validation hard-fail:
   a single bad citation failed the entire response.
5. Chat attachments were prompt-only (never indexed), so uploads could not
   be retrieved or cited per-section; ingestion hard-failed without
   embeddings.

### What was implemented

- **Retrieval:** `keyword_search.py` rewritten to OR tsquery (+ SQLite ILIKE
  fallback); `retrieval.py` expansion + per-query arm logging;
  `query_expansion.py` synonym groups; `parser.py` repeated header/footer
  strip; `chunking.py` section-carrying chunks; `ingestion.py` shared
  `store_parsed_chunks`, non-fatal embeddings, per-chunk `content_hash` /
  provenance / section / page metadata, empty chunks skipped.
- **`app/rag/partial_answer.py` (new - the core):** `should_decompose` /
  `decompose_query` (>=2 question marks or >=3 task verbs; JSON with
  fence-stripping, 8-section cap, fallback to the whole query);
  `retrieve_for_subquestion` (per-subquestion hybrid retrieval; attachment
  filter guard re-merges upload chunks); enforcement gates - zero-evidence
  abstention, jurisdiction-conclusion gate (e.g. Germany without German
  sources), banned-legal-conclusion stripping, per-section citation
  validation (invalid citations dropped with a warning, never a whole-
  response failure), claims classification (USER_PROVIDED /
  VERIFIED_EVIDENCE, `independent_verification`, `review_required`);
  per-section evidence metrics, statuses (SUPPORTED / PARTIALLY_SUPPORTED /
  INSUFFICIENT_EVIDENCE / PROCESSING_ERROR / EXPERT_REVIEW_REQUIRED),
  provenance labels, next_action; `compute_overall_status`,
  `render_answer`, `no_evidence_result` (no LLM call on zero evidence),
  `processing_error_result`.
- **Prompt-size budget (`PARTIAL_PROMPT_MAX_CHARS` = 16k):** the live Groq
  tier rejects requests above ~8k tokens (HTTP 413) and the Sarvam fallback
  has a 32k window; the unbounded 7-section prompt measured **47,766 /
  55,577 tokens** and failed both providers. Shared context truncates first,
  then each section admits its passages in rank order within its slice
  (top passage always kept).
- **`_ANSWERED_STATUSES` now includes PARTIALLY_SUPPORTED:** it was missing,
  so a response whose only answered sections were PARTIAL aggregated to
  INSUFFICIENT_EVIDENCE (over-abstention at the response level) and skipped
  the jurisdiction / banned-conclusion gates for those sections.
- **`app/routers/assistant.py`:** selective routing
  (`should_decompose` -> `answer_partial`); ChatResponse += `overall_status`,
  `sections`, `disclaimer`, `debug` (DEBUG=true only); attachment indexing
  (`ChatAttachment.document_id` FK, migration
  `011_chat_attachment_document_id.py` applied to the live DB, head=011);
  content-hash dedupe; top-level provenance normalized to the spec
  vocabulary (`VERIFIED_PUBLIC_SOURCE` replaces the legacy `PUBLIC_SOURCE`).
- **`app/rag/generation.py`:** a model that returns zero citations while
  chunks exist keeps the answer with an honest warning (abstain only when
  there is NO source - spec item 12).
- **`app/main.py`:** `logging.basicConfig(INFO)` - the per-query diagnostics
  (decomposition, retrieval arms, expansion, per-section retrieval,
  selective-answer summary) never reached the server log before because the
  root logger stayed at WARNING.

### Semantic arm reactivated (optional enhancement - done)

- `pip install sentence-transformers 6.1.0` (torch 2.10 was already
  present); models pre-warmed into the shared HF cache (bge-m3 dim=1024,
  norm=1.0000; cross-encoder ms-marco-MiniLM-L-6-v2).
- Live server log now shows `Retrieval arms: vector=20, keyword=20`,
  `Hybrid retrieval: 6 final chunks (from 39 candidates)`,
  `Cross-encoder reranker loaded`, `embeddings=yes` on new uploads, and
  **zero** "Embedding unavailable" / "Reranker unavailable" lines.

### Tests

- New `tests/test_partial_answering.py`: **24 tests** covering all 16
  spec-16 areas (extraction stats / page citability / extraction errors,
  decomposition, selective answering, claims, mixed sections, citation
  validation, malformed output -> PROCESSING_ERROR, banned conclusions ->
  EXPERT_REVIEW, jurisdiction gates, filter guard, prompt injection,
  expansion, keyword OR + filters + privacy, debug gating, exact disclaimer,
  prompt-budget regression, all-PARTIAL aggregation regression).
- Full suite: **286 passed** (was 262), incl. the
  `generation.py` zero-citations regression fix.

### Exact spec-17 scenario (live, real LLM) - 16/16 checks passed

Register -> upload the demo study PDF (1 page, 414 chars, 4 chunks,
`embeddings=yes`) -> send the 7-part question (cold-press Ashwagandha at 4 C,
40% bioavailability marker, cultivated Uttarakhand, sell India + Germany,
conference disclosure, cultivated->wild + wellness->insomnia claim change):

- `overall_status = PARTIALLY_SUPPORTED`, `insufficient_evidence = False`
  (4 SUPPORTED + 1 PARTIALLY_SUPPORTED + 2 INSUFFICIENT_EVIDENCE, each
  abstention carrying a reason and a next_action).
- 8 validated citations; upload citations carry `page=1`; the 40% claim
  labelled `USER_PROVIDED` / `USER_PROVIDED_ONLY` / `NOT_FOUND` /
  `review_required=true`.
- provenance `['USER_PROVIDED', 'VERIFIED_PUBLIC_SOURCE']`; disclaimer exact;
  no banned legal conclusions; `debug` absent (DEBUG unset).

### Issues found during verification (and fixed)

- First live run failed honestly (PROCESSING_ERROR): Groq 413 (47,766 > 8k
  TPM) and Sarvam 422 (55,577 > 32k) -> prompt budget implemented.
- Second live run: overall INSUFFICIENT_EVIDENCE despite 4 answered sections
  -> `_ANSWERED_STATUSES` fix above.
- One Windows-only incident: uvicorn's proactor accept died with WinError 64
  (known Windows asyncio flakiness, no application traceback); server
  restarted cleanly.

### Remaining issues / debt

- Bhashini key still pending (browser voice works).
- The legacy chat path still has no prompt-size cap for very large
  attachments (the partial path is budgeted; legacy degrades honestly).
- Visual verification of `/chat` rests on user screenshots (browser tool
  unavailable this session).

## 2026-09-27 (later) - Frontend premium pass: cleanup, README, auth UX, auto-refresh, Products/Versions/VersionDetail redesign

### Repo hygiene & docs
- Deleted 25 regenerable folders only (21 `__pycache__`, `BACKEND/.pytest_cache`,
  `sih/.vite`, `sih/.freebuff`, `FRONTEND/dist`); no source touched. Post-cleanup:
  health 200, targeted 33 passed, full suite **295 passed** (baseline 286).
- New root `IP-SHAKTI/README.md` (14 sections: architecture, `.env` table, start
  steps, verification, API/routes, troubleshooting, security); `FRONTEND/README.md`
  rewritten (was Vite boilerplate); pointer added atop `BACKEND/README.md`.

### Auth UX & session continuity
- `/login` Show/Hide password toggle (mirrors register's `PasswordField`).
- "Replay Animation" button removed from `ProtectionTimeline.jsx`.
- **Token auto-refresh**: `authedFetch()` now reacts to 401 ->
  `ensureFreshToken()` (deduped in-flight) -> retry once; multipart uploads
  converted without `Content-Type` (keeps FormData boundary); `downloadReport`
  returns raw `Response`; refresh failure by non-network error -> `sessionExpired()`
  -> existing `ProtectedRoute` redirect. "Token has expired" no longer surfaces
  while the 7-day cookie is valid. Verified live through proxy: login 200 ->
  valid 200 -> invalid 401 -> cookie refresh 200 (new token) -> retry 200 ->
  refresh w/o cookie 401.
- Products tab infinite "Loading..." fixed (missing `finally { setLoading(false) }`).

### Page redesigns (all verified: Vite transform 200, ESLint 12 = baseline 14-2
### for the dead `copy` state removed from NewVersionForm, 0 new errors)
- `/products/new` - `NP_CSS`, pg-head + two-column grid (form + "What happens
  next" steps); backend category enum values unchanged, labels prettified.
- `/products/:id/versions` - `VR_CSS`; header fetches the real product name via
  new `api.product()` helper; flat version rows (serif number, formatted date,
  monospace SHA-256 prefix, order-independent "Latest" pill); create-version form
  moved to a styled side panel; `ChangeImpactCard` untouched.
- `/products/:id/versions/:versionId` - `VD_CSS`; pg-head (eyebrow, product-name
  h1, change reason, "Created" date + full SHA-256 pill, All-versions button);
  premium not-found state; all 9 `Section`s (Ingredients, Formulation, Claims,
  Evidence, Target markets, Analysis, IP screening, Public disclosures, Reports)
  restyled via scoped CSS (uppercase eyebrow titles, dashed add-form panels,
  flat hairline rows, uppercase KV keys) - markup/logic untouched.
- `/products` - `PL_CSS`; pg-head with primary "New product" CTA, rows with
  serif monogram, description clamp, category badge, version count, created date.

### Full route audit (13 routes)
`/` Landing (`lp-*` serif hero, Reveal) - premium; `/login` `/register` auth-lp -
premium; `/home` hm-* - premium; `/products` redesigned; `/products/new` - done;
versions list - done; version detail - done; `/knowledge` kb-* - premium;
`/chat` chat-* (pill LLM toggle, warm tokens) - consistent, no change needed;
`/reviews` `/dashboard` `/demo` pg-head - premium; sidebar/Layout - premium.
No un-styled pages remain.

### Live field-contract checks (proxy 5173/api)
`GET /products/{id}` -> `name` (header h1); versions list + version detail ->
`version_number`, `created_at` (ISO-Z -> local date), `content_hash` (64 chars),
`change_reason`; detail carries `ingredients`/`claims` keys (`formulation` null
until recorded - handled). Temp verify users this session: `fixcheck_*`,
`tokfix_*`, `vrfix_*` (product id 66), `vdfix_*` - harmless DB artifacts.

### Pending
- `spec17_live.py` acceptance re-run against the selective-answering build.
- `scripts/verify_frontend_flow.py` regression.
- Backend restart required after any backend edit (uvicorn runs without `--reload`).

## 2026-09-27 (evening) - Version-detail page: Formulation placement + save bug + global success toasts

### 1. Formulation moved to the top of `/products/:id/versions/:versionId`
- The Formulation section (process description, extraction, temperature…) was the
  2nd of 9 sections and visually landed mid-page. It is now the **first section**
  of the version card; Ingredients/Claims/Evidence/Markets/Analysis follow.
- Summary (`dl.kv`) cleaned: empty rows and raw internals (`id`,
  `product_version_id`) hidden; `created_at`/`updated_at` rendered as
  "27 Sep 2026, 13:14 IST"; multi-line descriptions keep line breaks.

### 2. "Formulation not saving" - root-caused and fixed (frontend only)
Live contract proof (temp user `fmfix_*`, product 69/version 125):
- `PUT#1` saves fine (API was never broken) -> id 78.
- `PUT#2` with blank description (exactly what the old form sent after its
  post-save reset) -> **previous text wiped**. The old editor cleared itself on
  save and always re-sent every field, so the next save blanked anything not
  retyped -> user saw "not getting saved / can't tell if saved".
- `PUT#3` seeded payload -> description + new value both preserved.
Fix in `UpsertFormulationForm`:
- Editor **seeds from the saved formulation** (new `formulation` prop from the
  version detail) so it always shows current values;
- Values are **kept after save** (no self-clearing); numbers stay raw strings
  while typing (decimals like 36.5 now typeable) and convert only on submit;
- Backend untouched (schema is all-optional, merge semantics unchanged).

### 3. Global success toasts (green notification)
- New `ToastContext`/`ToastProvider` mounted above the router: fixed top-right
  card (brand green #1E3A2F, light-green check badge), slide-in, **auto-dismiss
  after 3 s**, manual ✕ with exit animation, max 3 stacked, `role="status"`.
- Wired to every mutation surface: formulation save; ingredient/claim/market add
  + remove; evidence attach; disclosure record; report generate; product create/
  delete; version create; review create/update; knowledge upload/delete/reindex;
  chat PDF attach/remove and conversation delete.

### Verification
- Vite transform 200; ESLint **12 = baseline** (0 new); no backend changes
  (uvicorn untouched); live PUT/GET contract sequence above passed.

---

## 2026-09-27 (night) - Product Passport analysis spec: reported bugs 1-12 fixed

Twelve reported bugs in the Product Passport analysis surface (claim
provenance, formulation shape, classification, IP routes, corpus labelling,
source metadata, summary card, explanations, change impact, disclosure text,
reports). Each was root-caused against the live DB first, then fixed in the
narrowest layer that was actually wrong - working modules were not rewritten.

### Root causes and fixes

| Bug | Root cause | Fix |
|-----|-----------|-----|
| 1 - saved claim missing from analysis | Pipeline was correct: analysis #172 ran 07:47 UTC, claim 104 was added 08:13 UTC; the UI showed the older **recorded run** as if it were current | Analysis runs now persist the `content_hash` they analysed (`analysis_service._persist` + `serialize`); frontend shows a staleness badge/notice when `analysis.content_hash` != the version's current hash. `NO_CLAIMS_RECORDED` scoped + explained per version (`claim_analyzer`) |
| 2 - West Bengal shown as target market | Display-only: `region` (ingredient source location) rendered next to market badges, reading like a market | Frontend: explicit "Source location: …" label, `region` rendered as a distinct badge; markets come only from `TargetMarket` rows (backend was already correct - covered by test) |
| 3 - formulation fields inferred / empty strings persisted | Formulation PATCH accepted `""` into numeric/optional fields and left missing parameters blank with no statement of absence | `FormulationBase` `field_validator(mode="before")` coerces `"" -> None` for every field; service-level defense in `upsert_formulation`; frontend sends `null` for empty strings; `MISSING_PARAMETERS_NOTE` ("Solvent, pressure, duration, concentration and standardisation are not yet provided.") auto-filled into `other_parameters` when a process is recorded and all four are null (self-clears when a parameter arrives, user notes never overwritten); Temperature unit input with the spec's exact labels |
| 4 - main conclusion said `possible_medicinal` while incomplete | No deterministic gate between the model's category and the headline | `evaluate_classification_gaps` gate: status **UNRESOLVED** until intended use + dosage form + complete ingredients + claims are recorded, `confidence=LOW`, `possible_categories` = the three spec pathways, `missing_information` = the spec's five requirements in order (`UNRESOLVED_MISSING_INFORMATION`), `review_required=true`; recomputed to PRELIMINARY when information arrives; frontend never headlines the category while UNRESOLVED |
| 5 - routes not evidence-based | Route strings were free-form and did not separate signal / why / missing / next / limitation | `_route()` factory with `STATUS_TO_LABEL`; every route carries `status/label/why_flagged/missing_information/next_action/limitation` with spec-exact texts (patent "A technical extraction process was recorded.", biodiversity ABS six gaps, etc.); frontend renders all five fields |
| 6 - demo records not labelled | Demo corpus records carried no visible provenance | `record_verification_fields()` helper + `DEMO_RECORD_LABEL` ("DEMO CORPUS — SYNTHETIC RECORDS — NOT LIVE PATENT DATA") / `VERIFIED_RECORD_LABEL`; `_corpus_flags()` sets `corpus_type`/`live_search_performed`/`records_verified` on screening + comparison; frontend shows corpus badges and a per-record banner; verified records insertable without touching analysis code |
| 7 - "AVAILABLE IN" labels + raw jurisdiction codes | Ambiguous concatenated labels; registry entries without metadata; citations surfaced `IN`/`INT` codes; demo **patent records** also carried raw `jurisdiction: "IN"` | Registry entries carry `source_type` (controlled vocab) / human `jurisdiction` / `authority` / `access_status` / `verification_status` / `source_url` / `retrieved_at`; `TKDL_RESTRICTED_LABEL` ("TKDL: RESTRICTED — NOT ACCESSED OR REPRODUCED"); `human_jurisdiction()` applied at the citation choke point **and** at patent-record build + serialization; frontend shows the metadata fields instead of "AVAILABLE IN" |
| 8 - no overview of the analysis | Findings only appeared deep inside sections | `AnalysisSummary` + `_build_analysis_summary` (deterministic, demo values PARTIALLY_SUPPORTED / INCOMPLETE / REQUIRED / DEMO_CORPUS / POTENTIALLY_RELEVANT / UNRESOLVED / RECOMMENDED); frontend `AnalysisSummaryCard` at the top |
| 9 - no "Why this result?" | Results showed a status without its reasoning | `SignalExplanation` (`signal/why/missing/limit`) attached to claim, patent, biodiversity and TK results; frontend `WhyThisResult` `<details>` expandable (biodiversity why/limit use the spec's exact texts) |
| 10 - change impact weak after V2 edits | No per-area impact derivation | `change_impact`: `affected_areas` (exactly the seven spec areas in spec order for the acceptance scenario), `reassessment_recommended`, `missing_information`, `review_questions`; `_compare_biodiversity_tk` runs both screens inline; frontend `ChangeImpactCard` renders the new sections; no automatic-approval statement anywhere (test-enforced) |
| 11 - disclosure text used deadlines/banned phrases | Old copy prescribed timing | `PUBLIC_DISCLOSURE_DISCLAIMER` with the spec's exact sentence, returned in `warnings` for both review branches (a dangling `)c disclosure."` syntax error from an earlier partial edit was fixed); no deadlines - test-enforced |
| 12 - reports did not use actual content | Report context lacked claims/markets/formulation/provenance/corpus/uncertainty | `report_service._base_ctx` gains `market_lines` / `formulation_lines` / `evidence_lines`; `_comp_details` adds standing + citation + corpus lines; `builders` gain `_content_sections` + `_evidence_detail_sections`; all three PDFs (IP brief, disclosure record, expert handoff) render them |

- Frontend: `App.jsx` - staleness badge, `AnalysisSummaryCard`, `WhyThisResult`,
  claim standing badges, UNRESOLVED classification display, five-field route
  cards, corpus badges + record labels, source metadata in `ScreeningView`,
  formulation Temperature-unit input + null payload, source-location labels,
  `ChangeImpactCard` sections, matching CSS.
- Classifier: `UNRESOLVED_MISSING_INFORMATION` (five requirements, exact order)
  is used while unresolved; a resolved run reports only genuinely-absent gaps.

### Verification (all commands from `BACKEND/`)
- `python -m pytest tests/test_acceptance_spec.py -q -p no:warnings` -> **34 passed**
  (new file: acceptance scenario steps 1-14 - AshwaBio-X V1: ingredient, exact
  formulation shape, 40% + wellness claims, India market, full analysis; V2
  seeded from V1 with wild / "Treats insomnia" / capsule / Germany; comparison
  expectations; plus dedicated tests for bugs 2, 11, 12).
- `python -m pytest tests/ -q --tb=short -p no:warnings` -> **329 passed** in 371.69s
  (295 baseline + 34 new; 0 failures).
- ESLint `frontend`: **12 problems = baseline** (all pre-existing, untouched code).
- uvicorn restarted without `--reload` (backend was edited).
- `python scripts/verify_frontend_flow.py` -> **139 checks PASSED** against the live server.
- `spec17_live.py` (real LLM) -> **35/35 checks passed**.
- `python -c "from app.main import app"` -> imports OK (after the disclosure-models syntax fix).

### Remaining limitations
- No desktop browser is connected to the harness, so the UI itself was not
  reproduced live; frontend changes are covered by ESLint + the API contracts
  the tests pin.
- Bhashini API key not provided - server-side translation stays in its honest
  fallback mode.

---

## 2026-09-27 (late night) - Chatbot jurisdiction scope: market-entry evidence, citations and UI - VERIFIED

### Problem (reported)
The chatbot answered "Can I launch my product to market?" for **AshwaBio-X V1
(target markets: India + Germany)** by citing **U.S. 21 CFR CGMP** and other
out-of-jurisdiction material. The answer had no market structure, no evidence
status, no claim provenance and no indication of which sources were filtered.

### Root cause (three layers, all confirmed with live-DB evidence)
1. **Corpus metadata:** all 108 public corpus documents carried
   `jurisdiction='India'`, including nine U.S. documents (21 CFR Parts
   210/211/4/600/606/610, FDA guidance, Federal Regulations), one China policy
   document, PIC/S and WIPO instruments - so every jurisdiction gate saw U.S.
   law as "India".
2. **Pipeline:** the chat flow never derived a jurisdiction scope from the
   selected Product Passport target markets; `MetadataFilter` came only from the
   request and the snapshot was JSON-dumped into the prompt without being used
   for retrieval.
3. **Gates:** jurisdiction checks keyed off the question text only; a
   jurisdiction-neutral launch question took the single-shot path where nothing
   enforced scope at all.

### Fix (narrow layers; retrieval, citation validation and abstention untouched)
- **New `app/rag/jurisdiction_scope.py`** - single source of truth:
  market -> allowed jurisdictions (India; Germany -> Germany + European Union;
  United States -> United States), `apply_jurisdiction_scope` (keeps untagged
  private uploads and neutral "International" background, logs every exclusion),
  `JurisdictionScopeTracker` (wraps `hybrid_retrieve`: over-retrieve 18, filter,
  trim to `rag_rerank_top_k`=6 - `retrieval.py` untouched), `build_scope_block`
  (the `=== MARKET CONTEXT ===` prompt block with rules 1-8, section names
  derived from the selected markets, the ~10-part launch structure opening with
  "Launch readiness: Cannot be determined from the current information."),
  `is_launch_question`, `compute_evidence_status` (INSUFFICIENT /
  PARTIALLY_SUPPORTED / SUFFICIENT + CANNOT_BE_DETERMINED + spec reason),
  exact rule-6 sentences, launch-gap sentence, the 7-item ordered
  `missing_information_for`, `claim_standing` (USER_PROVIDED_ONLY / NOT_FOUND /
  REVIEW_REQUIRED), and `strip_unselected_us_references` (removes U.S.-law
  sentences when the U.S. is not selected, with a logged warning).
- **`app/rag/generation.py` + `app/rag/partial_answer.py`** - the scope block is
  threaded into both the single-shot and selective prompts (same rules for both
  paths).
- **`app/routers/assistant.py`** - scope derived from the selected version's
  snapshot before filters; both retrieval paths go through the tracker;
  enforcement stage (U.S.-reference sanitizer, per-section "No verified <market>-
  specific source..." fallback, market-specific gap warnings); 14 new
  `ChatResponse` fields (`market_context`, `jurisdiction_filter`,
  `unselected_jurisdiction_sources_excluded`, `private_search_requested/
  performed`, `private_sources_found`, `public_sources_found`,
  `jurisdiction_warning`, `evidence_status`, `evidence_gap_warnings`,
  `why_this_answer`, `claim_reviews`, ...); `filters_applied` extended with
  market-derived entries; `getattr(get_settings(), "rag_rerank_top_k", 6)` so
  partial settings stubs (tests) keep working.
- **Corpus correction `scripts/fix_corpus_jurisdictions.py`** (idempotent,
  `--apply`) - 12 mislabelled documents rewritten: 9 -> United States, 1 ->
  China, 2 -> International. Distribution now: India 96 / United States 9 /
  untagged 7 / International 2 / China 1.
- **Frontend `FRONTEND/src/App.jsx`** - assistant messages capture the new
  fields; `ChatMarketPanel` renders **MARKET CONTEXT / SOURCE SCOPE / EVIDENCE
  STATUS / JURISDICTION WARNING**, the market-specific evidence-gap warnings and
  a collapsible **"Why this answer?"** (selected markets, per-jurisdiction
  source counts, excluded jurisdictions, missing information, recorded claim
  reviews) + CSS.

### Verification (commands from `BACKEND/`)
- `python -m pytest tests/test_chat_jurisdiction.py -q -p no:warnings` ->
  **16 passed** (spec TEST 1-10 + sanitizer, multi-part path, sarvam parity,
  claim-values scan).
- `python -m pytest tests/ -q --tb=short -p no:warnings` -> **345 passed** in
  457.12s (329 baseline + 16 new; 0 failures).
- ESLint `src/App.jsx`: **12 problems = baseline** (all pre-existing).
- `python scripts/verify_frontend_flow.py` -> **139 checks PASSED** after the
  uvicorn restart.
- `spec18_live.py` (real LLM, exact question "What do you think, can I launch
  my product to market?" against a freshly built AshwaBio-X V1: India + Germany,
  40% claim) -> **11/11 checks PASS**: answer opens with "Launch readiness:
  Cannot be determined from the current information.", no "21 CFR" anywhere,
  no U.S. citation, `unselected_jurisdiction_sources_excluded = [China, United
  States]` (server log: `Jurisdiction scope [India, Germany, European Union]:
  excluded 8 candidate chunk(s) from China, United States`), exact jurisdiction
  warning, evidence `INSUFFICIENT` + `CANNOT_BE_DETERMINED` + spec reason, claim
  review `USER_PROVIDED_ONLY/NOT_FOUND/REVIEW_REQUIRED`, all 7 missing items,
  per-market gap warnings, professional-review recommendation.
- uvicorn restarted without `--reload` (backend was edited).

### Remaining limitations
- The market-context panel fields are returned only by `POST /api/assistant/chat`;
  the persisted history serializer (`GET .../conversations/{id}`) still returns
  citations + flags only, so the panel does not reappear when an old session is
  reloaded from history. Persisting them needs a `chat_messages` metadata column
  (migration) - proposed follow-up.
- `sources_used` counts retrieved in-scope chunks, not topical relevance: a
  live answer may state "no verified India-specific source" for market entry
  while 2 India documents were retrieved (and not cited). Counts and the
  model's per-statement judgement are labelled separately for this reason.
- The corpus still contains **zero Germany/EU documents** - Germany gaps are
  therefore correct until verified sources are ingested; the fix corrects
  metadata and scope, it does not invent sources.
- Bhashini key not provided -> TEST 10 asserts the honest
  `SERVICE_UNAVAILABLE_WARNING` fallback with citations/jurisdictions unchanged.
- No desktop browser connected -> UI panel verified by ESLint + API contracts
  only; the user's own browser run is the visual check.
- No formatter/type-checker is configured for the backend (no ruff/black/
  mypy config); verification is the import check + the 345-test suite.

## 2026-09-27 (session 4) - Chatbot Product Passport access: no more "I cannot access your product" - VERIFIED

### Problem (reported)
With Context Options set to **AshwaBio-X / Version 1** (private search
checked), the question *"can you access my product that i have created"*
was answered *"I do not have the ability to access external product files or
databases; I can only work with the information you provide in the
conversation."* - i.e. the model denied access to the selected Product
Passport and to the knowledge-base chunks even though both were supplied.

### Root cause (two layers, both confirmed)
1. **Prompt:** the passport reached the model under a bare
   `=== PRODUCT CONTEXT ===` header with no instruction saying it *is* usable,
   while the SYSTEM_PROMPT said "Answer ONLY using the provided context
   passages" (passages = chunks) and had a rule telling the model to state
   what it cannot access - so it disclaimed access to everything that was not
   a numbered passage.
2. **Gating:** both generation paths aborted before calling the LLM when the
   corpus matched nothing (`not chunks and not document_context`), even with
   a passport selected; in the selective path, Gate 1 abstained any section
   with zero chunks and no attachment without ever reading the model's
   passport-grounded answer (`used_product_context` was passed to provenance
   but not checked by the gate).

### Fix (prompt + gates; abstention guarantees preserved)
- **`app/rag/generation.py`** - SYSTEM_PROMPT gains a "WHAT YOU ALREADY HAVE
  ACCESS TO" inventory (retrieved passages, PRODUCT CONTEXT passport,
  attached document); rule 1 broadened to all context; rule 3 allows
  passport/attachment attribution without chunk citation; new rule 8: never
  say you cannot access the product/files/database when PRODUCT CONTEXT is
  present. `build_context_prompt` PRODUCT CONTEXT header now states "It IS
  available to you..." and how to attribute it ("Product Passport
  (user-provided)"); the passages header notes they come from this system's
  knowledge base. `generate_rag_answer` gains `launch_question: bool = False`;
  the early exit now only fires when `not chunks and not document_context and
  (not product_context or launch_question)`.
- **`app/rag/partial_answer.py`** - PARTIAL_SYSTEM_PROMPT rule 4 extended
  with the same never-disclaim clause; `build_partial_prompt` PRODUCT CONTEXT
  block mirrors the "It IS available to you..." instruction; full abstention
  now requires `not product_context or launch_question`; **Gate 1** skips its
  abstain-out when `used_product_context` is set (provenance stays
  USER_PROVIDED, the jurisdiction gate still blocks jurisdiction-specific
  conclusions, banned-conclusion stripping still applies).
- **`app/routers/assistant.py`** - passes `launch_question=launch_question`
  into `generate_rag_answer` (computed at line 340, before generation).

### Design decision: launch questions keep the deterministic path
The first Gate 1/early-exit change was too broad: spec TEST 4/5 assert
`fake.calls == 0` (the model is *never asked* to fill a market-entry gap when
nothing in-scope was retrieved). Launch readiness can never be proven from a
passport, so `launch_question` now exempts launch questions from both the
passport early-exit bypass and the selective-path bypass - a passport
question reaches the model, a launch question with no retrieved source does
not.

### Tests
- New `tests/test_chat_product_context.py` (**12 tests**): system-prompt
  inventory/disclaimer assertions, prompt-block instructions, passport-only
  single-path generation, selective-path endpoint answer containing the
  passport (single generation prompt, not the decompose prompt), abstention
  preserved with no passport/attachment/chunks, Boom-LLM never called in that
  case, and launch-with-passport still skipping the model.
- `python -m pytest tests/ -q --tb=line -p no:warnings` -> **357 passed** in
  720.54s (345 baseline + 12 new; 0 failures, 0 regressions in
  `test_chat_jurisdiction.py` / `test_partial_answering.py`).

### Live verification (real LLM, uvicorn restarted without `--reload`)
`C:\Users\USER\AppData\Local\Temp\opencode\passport_access_live.py` builds a
fresh AshwaBio-X V1 (Uttarakhand root 100 g, cold press 4 C, 40% claim,
India + Germany) and asks the exact reported question plus a knowledge
question - **8/8 checks PASS**:
- *"can you access my product that i have created"* -> "Yes. I have access to
  the Product Passport version you provided (Product Passport (user-provided)
  for AshwaBio-X, version 1). I can use the details you shared..." - no denial
  phrases, no 21 CFR, `insufficient_evidence=False`, `overall_status=SUPPORTED`,
  `market_context=["India","Germany/EU"]`, `jurisdiction_filter=[India,
  Germany, European Union]`.
- *"what ingredients are in my product?"* -> names the passport facts exactly
  (Withania somnifera root, powder, 100 g, Uttarakhand) - nothing invented,
  honest warnings retained ("No verified Germany-specific source was
  retrieved...").

### Remaining limitations
- Warnings still include "produced from retrieved sources, but no verifiable
  citations were attached" for passport-grounded answers (single-path text) -
  honest but slightly misworded when the ground is the passport, not sources;
  proposed follow-up.
- History reload does not restore `market_context` (needs `chat_messages`
  metadata migration) - unchanged from session 3.
- Bhashini key and desktop browser still not provided (same as session 3).

---

## Entry: 2026-09-28 (session 5) - Overall Product View (spec items 16-19)

### Task
Replace the "Live Demo" section with a production-quality Overall Product
View backed by real stored data and a new aggregate API (spec items 16-19).
No synthetic records, no hard-coded risk values, no approval language, no
second interpretation in the chatbot; version-scoped with content hashes and
a deterministic overall-status vocabulary.

### What was implemented
1. **Backend contract (`app/services/overview_service.py`,
   `app/routers/overview.py`, mounted in `main.py`):** `GET
   /api/products/{product_id}/versions/{version_id}/overview` returns the
   16-section stored-data JSON (product, overall_status, facts, formulation,
   ingredients, claims, evidence, target_markets, regulatory_classification,
   ip_review, biodiversity_abs_review, traditional_knowledge_review,
   disclosures, analysis_history, recommended_actions, missing_information,
   provenance, disclaimers). Every value carries provenance where practical;
   missing values render as "Not provided" / "Not recorded" with
   `NOT_PROVIDED` provenance - never invented. Overall status uses the
   deterministic precedence ANALYSIS_NOT_RUN > ANALYSIS_OUTDATED >
   INSUFFICIENT_INFORMATION > REVIEW_REQUIRED > PARTIALLY_COMPLETE >
   COMPLETE_FOR_REVIEW with confidence NOT_ASSESSED/LOW/LOW/MEDIUM/MEDIUM/HIGH
   and only those six statuses. Exact spec sentences live as module
   constants (`OVERVIEW_NOTICE`, `ANALYSIS_OUTDATED_NOTICE`,
   `NO_MARKET_EVIDENCE`, `NO_PATENT_RESULT`, `CLAIM_USER_PROVIDED_WARNING`,
   `NO_EVIDENCE_DOCS`, `NO_DISCLOSURE_EVENT`, `TK_NO_SOURCE_NOTICE`,
   `CLASSIFICATION_GAP_REASON`, `DEMO_RECORD_LABEL`, priorities "Higher/
   Moderate/Lower review priority"). IP review never lists demo records:
   `records=[]` with `synthetic_records_omitted`, `demo_notice` and status
   SEARCH_UNAVAILABLE (SEARCH_NOT_RUN when no screening, NO_RELEVANT_RECORD_
   IDENTIFIED etc. otherwise). Recommended actions are derived only from
   actual gaps (including `run_analysis` / `rerun_analysis` with the exact
   overdue sentence) with HIGH/MEDIUM/LOW priorities.
2. **Chatbot integration (`app/routers/assistant.py`):** `_get_product_context`
   attaches `overview_context_for_chat(overview)` - the assistant renders the
   same object the page shows, so the two cannot disagree; no U.S. sources
   are introduced for India/Germany scopes.
3. **Frontend (`FRONTEND/src/App.jsx`):** `api.productOverview`; routes
   `/overview`, `/overview/:id/:versionId`; `/demo` redirects to
   `/overview`; sidebar entry "Overall Product View"; home card and
   `Landing.jsx` links renamed. New `OverallProductView` component: version
   header (product, version, content hash with the full hash on hover,
   created/updated, analysis status/run/timestamp) + "All versions" control;
   preliminary-decision-support notices; overall-status card with the
   overdue-hash alert and a "Re-run analysis" button that calls the real
   `api.analyzeProduct` then refreshes; 13 sections in spec order (Product
   Facts, Formulation and Process with per-field provenance and "Edit
   Product Passport", Ingredients and Source, Claims and Evidence, Target
   Markets split INDIA / GERMANY-EU, Regulatory Classification, IP and
   Prior-Art Review, Biodiversity/ABS, Traditional-Knowledge, Disclosure
   Review, Analysis History with OUTDATED labels, Recommended Actions) plus
   a Provenance footer. State is derived from keyed payloads
   (`{key, payload}` / `{key, message}` + `retryToken`) so there is no
   synchronous setState in effects and a version switch reloads everything
   without mixing versions; status chips via `OV_TONE`/`ovTone`.
4. **Demo components removed:** `FormulationRiskDashboard.jsx` and
   `IPRiskMap.jsx` deleted, `DemoShowcase` replaced; grep confirms zero
   "Live Demo" / "illustrative demo" / `FormulationRiskDashboard` /
   `IPRiskMap` references in `src`.
5. **Tests (`tests/test_overview.py`, 29):** contract keys, status and
   confidence vocabularies, precedence, provenance coverage, exact
   sentences, claims standing + marketing warning, market sections with the
   exact no-evidence sentence, classification from analysis vs UNRESOLVED,
   IP not-run and demo-corpus paths (synthetic omitted), bio/TK states,
   disclosure notice, outdated detection (hash mismatch), version isolation,
   chatbot prompt consistency (same data, no second interpretation), and
   the AshwaBio-X V1 §19 acceptance scenario.
6. **Live acceptance (`scripts/overview_live.py`, new):** builds a fresh
   AshwaBio-X style passport (Ashwagandha root 100 g, source location
   "Uttarakhand, India", cold press 4 °C with solvent/pressure/duration
   deliberately unrecorded, user-provided wellness claim, India + Germany
   target markets), then: (1) reads the overview with no runs recorded -
   honesty checks on every section; (2) runs the patent, biodiversity and
   TK screenings - demo records must be omitted with the exact DEMO CORPUS
   notice; (3) runs the real comprehensive analysis - classification becomes
   ANALYSIS_DERIVED and the claim links to the run without its standing
   changing; (4) edits the claim - overall flips to ANALYSIS_OUTDATED with
   the exact overdue sentence and the `rerun_analysis` action, and the
   overview hash still equals the version's own hash. Exact sentences are
   imported from the service constants so the script cannot drift.

### Verification (commands, results)
- `python -X utf8 -m pytest tests/ -q --tb=short -p no:warnings` ->
  **386 passed** (357 baseline + 29; ~414 s).
- `python scripts/verify_frontend_flow.py` -> **139/139 checks PASSED**
  against the restarted uvicorn.
- `python scripts/overview_live.py` -> **84/84 checks PASSED**. Final
  live output: AshwaBio-X version 1 (id 143), hash d66fa71ab2cd2476...,
  overall ANALYSIS_OUTDATED (confidence LOW), analysis completed run=211
  outdated=True, 14 fact fields (NOT_PROVIDED/SYSTEM_DERIVED/USER_PROVIDED),
  solvent "Not provided", claim USER_PROVIDED_ONLY / DO NOT PRESENT AS
  VERIFIED / REVIEW_REQUIRED, markets ['India','Germany'] sections
  ['INDIA','GERMANY/EU'], classification UNRESOLVED (LOW,
  ANALYSIS_DERIVED), ip SEARCH_UNAVAILABLE (0 verified, 4 synthetic
  omitted), biodiversity REVIEW_REQUIRED, TK ADDITIONAL_INFORMATION_NEEDED,
  disclosures 0 / NO_EVENTS_RECORDED, 4 analysis runs, 10 actions
  (4 HIGH, 6 MEDIUM), 7 missing-information items.
- `npm run lint` -> **12 problems = baseline** (3 new
  `react-hooks/set-state-in-effect` errors were introduced and fixed by the
  key-derivation refactor).
- `npx vite build` -> succeeds (462.58 kB bundle).
- Desktop browser unavailable, so UI verification is lint + build + API
  contract; a hard reload (Ctrl+Shift+R) is needed to pick up the new bundle.

### Environment incident (not code)
- The remote Supabase pooler intermittently dropped connections during
  live runs: two `psycopg.OperationalError: server closed the connection
  unexpectedly` failures (one 500 on target-market creation, one wedged
  pool where DB routes timed out while `/openapi.json` still served), and a
  direct probe measured 9 s to establish a fresh session. uvicorn was
  restarted to clear the stale pool and all subsequent runs passed.
  `overview_live.py` catches transport errors and reports them as FAILs
  instead of crashing. Suggested follow-up: `pool_pre_ping=True` in
  `app/databases.py` (not applied - stable module, out of scope).

### Remaining limitations
- No live patent-search API: the corpus is DEMO_CORPUS, so the overview
  reports SEARCH_UNAVAILABLE and omits synthetic records rather than
  listing them (spec-honest, but no real prior-art picture).
- No market-evidence links (Germany/EU corpus empty): market sections show
  the exact "No verified market-specific evidence is available for this
  section." sentence.
- Version `updated_at` is not a stored column - reported as null with an
  honest note; created timestamp only.
- Biodiversity supplier/ABS fields and several passport process parameters
  are absent from the schema - reported as "Not provided".
- Session-4 limitations unchanged (single-path passport warning wording,
  chat history reload lacks panel metadata), plus no Bhashini key and no
  connected desktop browser.


---

## Entry: 2026-09-28 (session 6) - RAG corpus: 12 required statute/regulation study files

### Task
An audit found 12 source documents named in the problem statement but missing
from `BACKEND/corpus`. Add them (ADD only - no existing corpus file deleted,
renamed or rewritten).

### What was added
Structured study summaries with the fixed frontmatter template
(`title, source_url, file_name, document_type, subject, jurisdiction,
language, promulgated, last_verified=2026-09-28, corpus_version=v1.1-verified,
keywords, entities`) and the mandatory `## Verification note`:

| # | File | Lines |
|---|---|---|
| 1 | `drugs-and-magic-remedies-objectionable-advertisements-act-1954.md` | 196 |
| 2 | `patent-amendment-rules-2024-india.md` | 175 |
| 3 | `geographical-indications-act-1999-india.md` | 206 |
| 4 | `trade-marks-act-1999-india.md` | 215 |
| 5 | `designs-act-2000-india.md` | 180 |
| 6 | `copyright-act-1957-india.md` | 199 |
| 7 | `plant-variety-farmers-rights-act-2001-india.md` | 216 |
| 8 | `biological-diversity-rules-2024-india.md` | 221 |
| 9 | `fssai-ayurveda-aahar-regulations-2022.md` | 165 |
| 10 | `section-3j-3p-patenting-bar-tkdl-guidance.md` | 217 |
| 11 | `first-schedule-authoritative-texts-ayurveda.md` | 172 |
| 12 | `ayurvedic-pharmacopoeia-india-standards.md` | 172 |

### Method
- Uncertain provisions were checked against public sources before writing
  (section maps for DMR/GI/TM/Designs/TM/PPV&FR; BD Rules 2024 notification
  G.S.R. 665(E) 22-10-2024 + 2025 amendment G.S.R. 295(E); FSS (Ayurveda
  Aahara) Regulations text; the full text of Patents Act section 3; the IPO
  AYUSH examination guidelines; the CDSCO Traditional Drugs page for the
  First Schedule definitions; PIB's API monograph counts).
- Where a number or clause could not be confirmed, the file describes the
  provision **by subject** and says so in a "Deliberately not stated" note -
  no section numbers, fees or limits were invented.
- `source_url` is a top-level official domain in every file (indiacode,
  ipindia, fssai, cdsco, ayush, moef, plantauthority).

### Also fixed
- Typo in the session's own `designs-act-2000-india.md`: "controneous" ->
  "contrary".

### Evidence
- All 12 files present with every required frontmatter key, `## Verification
  note` and the "What an Ayurvedic product owner must check" list (scripted
  check above).
- Corpus now 126 `.md` files; no pre-existing file removed.
- No code, test or migration change in this session - this is a corpus-only
  change, so the feature test counts in PROJECT_STATUS.md are untouched.

## Entry: 2026-09-28 (session 7) - RAG corpus: 9 international IP / regime / case-law study files

### Task
Add the international sources the corpus was missing: TRIPS, CBD, Nagoya,
PCT, Madrid, Hague, Budapest, Indian case law, and the first Germany/EU
market-access file (the gap flagged in TODO/PROJECT_STATUS). ADD only - no
pre-existing corpus file deleted, renamed or modified.

### What was added
Fixed frontmatter template, top-level official `source_url`, single-line
`## Verification note`, `##`/`###` headings + tables for section-aware
chunking:

| # | File | Lines |
|---|---|---|
| 1 | `trips-agreement-1994-relevant-provisions.md` | 450 |
| 2 | `convention-biological-diversity-1992-cbd.md` | 307 |
| 3 | `nagoya-protocol-2010-access-benefit-sharing.md` | 369 |
| 4 | `patent-cooperation-treaty-pct.md` | 286 |
| 5 | `madrid-protocol-international-trademark-registration.md` | 249 |
| 6 | `hague-system-industrial-designs-registration.md` | 242 |
| 7 | `budapest-treaty-microorganism-deposit.md` | 250 |
| 8 | `indian-ip-case-law-compendium.md` | 370 |
| 9 | `eu-germany-herbal-medicinal-product-market-access.md` | 420 |

### Method - premises verified before writing
Every article map or citation that was not certain was checked against the
official text (cbd.int, EUR-Lex, WIPO Lex, WIPO notifications, EMA) first,
then written to match:

- **Nagoya** article map fetched from cbd.int: Art 7 = access with
  approval/involvement of Indigenous communities, Art 8 = special
  considerations (research, emergencies, food security), Art 12 = community
  protocols and minimum ABS terms, Art 17 = monitoring/checkpoints and the
  **international certificate of compliance (Art 17(2))**, Art 15 =
  user-country compliance. An earlier draft's "Art 12 = access approval" and
  "Art 12 = certificate" readings were corrected, not carried forward.
- **EU novel food**: Reg (EU) 2015/2283 Art 3(2)(b) = 25 years in the
  customary diet of at least one third country **before an Art 14
  notification**; the commonly repeated "15 years in the EU" element does not
  exist and is flagged as a correction in the file.
- **Health claims**: the instrument is Regulation (EC) No **1924/2006** (the
  "1924/2009" citation in the brief was wrong - corrected in-file), permitted
  list = Commission Regulation (EU) No 432/2012.
- **THMP (Directive 2001/83/EC)** re-verified against the consolidated text
  in this session: 30 years incl. 15 in the Community = **Art 16c(1)(c)**;
  HMPC referral where EU use < 15 years = **Art 16c(4)**; refusal grounds =
  **Art 16e(1)(a)-(e)** with notification duty in 16e(2); the Art 16f list of
  herbal substances; recognition across Member States = **Art 16d(1)-(2)**
  (Chapter 4 by analogy / "take due account"); **Art 16g** = GMP by analogy +
  the mandatory labelling and advertising statements; monographs = Art
  16h(1) tasks / 16h(3) effect. The draft's "refusal = 16f" and "16g =
  mutual recognition with a reference Member State" were wrong and are now
  labelled as corrections in the file.
- **Budapest Treaty**: storage term (Rule 9), furnishing of samples (Rule 11),
  once-for-all storage fee (Rule 12) and India's three International Deposit
  Authorities (MTCC 2002, NCCS 2011, NAIMCC 2020) confirmed from WIPO.
- **Madrid**: India's accession (deposit 8-4-2013, in force 8-7-2013), Art
  5(2)(b)/8(7)(a)/14(5) declarations, and transformation = Arts 9bis/9quinquies.
- **Hague**: Arts 1-34 article list from WIPO Lex, refusal period 6 months
  extendable to 12 (Common Regulations Rule 18(1)), London Act frozen since
  1-1-2010, and **India is not a member** (DPIIT concept note proposing
  accession flagged as a proposal, not law).
- **Cases**: only Cadila Healthcare v Cadila Pharmaceuticals (2001) 5 SCC 73
  and Novartis (2013) 6 SCC 1 are given with full citations; Bajaj v TVS, R.G.
  Anand and Natco v Bayer carry "citation to be verified" and every case
  section carries the mandatory verification line.

### Deliberately dropped or softened (uncertain, not invented)
- **Dropped entirely** (no confident citation): Union of India v Hindustan
  Unilever, Enerzall, Samsung, the Ashwagandha descriptiveness matter, the
  "Kodava" matter - listed in section 9 of the case-law file as NOT included.
- **Softened to "events, numbers to verify"**: turmeric (US 5,401,941) and
  neem patent revocations, the basmati/EPO and USPTO oppositions, the number
  of Indian traditional-knowledge prior-art documents, Darjeeling GI
  application numbers.
- **Cadila**: PTC citation varies across sources, so only the SCC/AIR
  citations are asserted.
- **Hague/Madrid/PCT**: India's PCT national-phase period written as "31
  months (verify current rules)" rather than asserted flatly.

### Also fixed
- The `## Verification note` sentence was line-wrapped in the 9 new files;
  normalised to the exact single-line string used by the rest of the corpus.
- That normalisation was done with PowerShell, which read the UTF-8 files as
  Windows-1252 and double-encoded every non-ASCII character. Detected in the
  same session (0 em dashes, `â` sequences present) and **reversed
  byte-exactly** - the cp1252 round-trip was proven lossless for all 256 byte
  values first, then each file was re-validated as strict UTF-8 with 0
  control/mojibake characters and the em dashes restored.

### Evidence
- Scripted check over all 9: frontmatter keys present, official
  `source_url`, `language: "English"`, `last_verified: "2026-09-28"`,
  `corpus_version: "v1.1-verified"`, exactly one `## Verification note` as the
  final line - **ALL_PASS=True**.
- Corpus = 126 `.md` files; the 105 pre-existing files keep their original
  timestamps (no pre-existing file written to), and the 12 files from session
  6 are untouched.
- No code, test or migration change in this session - corpus-only, so the
  feature test counts in PROJECT_STATUS.md are untouched. The new files are
  **on disk only**; `scripts/ingest_corpus.py` still has to be run.

---

## Entry: 2026-10-03 - Workspace cleanup (junk removal + folder flatten)

### Task
Remove verified-dead code/folders and collapse the accidental
`sih-main\OneDrive\Desktop\sih` nesting (a past `git push` from the wrong
directory baked the author's local path into the tree) plus the stale
`temp_check_repo` clone, so the project opens directly. Nothing deleted
without a before/after test proof.

### What was removed
1. **`temp_check_repo/` (14.0 MB, 389 files):** stale shallow clone of
   `github.com/srijan-mukherjee/sih` at `41cd99c "phase 7 done"` - predates
   Phases 8-13 and all 2026-09-28 sessions. Contained its own `.git`, a
   duplicate `BACKEND/.env` with live secrets, `__pycache__` dirs, a `.vite`
   cache and `.freebuff/project-id`. Zero references from anywhere in the
   workspace; upstream history stays on GitHub, so no history was lost.
2. **BACKEND legacy island (pre-Phase-1):** `main.py`, `models.py`,
   `auth/authentication.py`, `databases/db.py`, `databases/dbmodels.py`,
   `hash/Hashing.py`. An AST import-graph over every `.py` in
   `app/tests/scripts/eval` plus grep plus an `alembic/env.py` check proved
   only the island imports itself; no dynamic imports exist anywhere.
   `TODO.md` Phase-2 follow-up ticked.
3. **`PHASE2_SUMMARY.md`** (superseded one-off summary) + its README
   layout-tree line.
4. **`PROJECT_STATUS.md`:** removed the stale duplicated Phase 11
   NOT_STARTED / Phase 12 IN_PROGRESS / Phase 13 NOT_STARTED blocks;
   corrected Test Status, migration head (`007` -> `011`), corpus file
   count (`126` -> `131` verified on disk) and Last/Next tasks.

### Folder flatten
`sih-main\sih-main\OneDrive\Desktop\sih\IP-SHAKTI` -> `sih-main\IP-SHAKTI`;
the master-prompt `.txt` moved alongside; the emptied wrapper chain
deleted. Workspace root is now exactly `IP-SHAKTI/` + the prompt file.
Verified: no hardcoded `OneDrive` path in any `.py/.js/.jsx/.ini/.example/
.yml` (docs/history mentions only). The fresh `BACKEND/.venv` moved along
and re-verified (`sys.prefix` resolves to the new path, all deps import).

### Verification (before -> after, identical)
- Baseline before deletions (deep path): **477 passed, 1 failed / 478**
  (the suite has grown past the logged 386 - new eval/gap/llm/privacy/
  sources-registry suites).
- Final run after all removals + flatten (new path): **477 passed,
  1 failed / 478** - same single test, so the cleanup broke nothing.
- The 1 failure is pre-existing drift, unrelated to this cleanup:
  `test_acceptance_spec.py::TestBug4Classification::
  test_unresolved_with_the_five_information_requirements` pins the three
  BUG-4 pathways from the 2026-09-27 design (see the BUG-4 entry), while
  `app/analysis/schemas.py::UNRESOLVED_PATHWAYS` now lists six renamed
  pathways (`classical_traditional`, `proprietary_ayurvedic`, `new_drug`,
  `phytopharmaceutical`, `ayurveda_aahara`, `possible_cosmetic`). Neither
  list appears verbatim in the master prompt. Left untouched - it needs a
  product decision on which side is correct, not a cleanup edit.

### Startup check (2026-10-03, same session)
- `alembic upgrade head` **fails**: the live Supabase DB is stamped at
  revision `014` but this tree only carries migrations `001`-`011` - the
  database was migrated by a newer codebase this copy does not have.
  Read-only server start is unaffected (the app never migrates at boot),
  but any 012-014 schema additions are unknown here.
- Backend started (`uvicorn app.main:app`, port 8000): `/api/health`
  `{"status":"healthy"}`, 84 routes on `/openapi.json`.
- Frontend started (`npm run dev`, port 5173): HTTP 200.
- Open follow-ups: obtain migrations 012-014 (or the newer tree) before
  writing to the live DB; re-ingest the corpus (21 files still disk-only);
  resolve the BUG-4 pathways drift above.
