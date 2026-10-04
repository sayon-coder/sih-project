# IP-SAKTI Sahayak - TODO List

---

## Phase 0: Repository Inspection and Planning
- [x] Inspect existing repository
- [x] Identify reusable code
- [x] Identify missing components
- [x] Create project state files
- [x] Establish baseline

## Phase 1: Backend Foundation, Database, Authentication, JWT, RBAC

### Database & Migrations
- [x] Add Alembic to requirements.txt
- [x] Initialize Alembic
- [x] Create initial migration for existing tables
- [x] Add roles table migration
- [x] Add user_roles junction table migration
- [x] Add audit_logs table migration
- [x] Test migrations (up/down) - verified by scripts/verify_migrations.py (2026-09-22)

### Database Models
- [x] Refactor dbmodels.py to proper models directory structure
- [x] Create Role model
- [x] Create UserRole model
- [x] Create AuditLog model
- [x] Update User model (add created_at, updated_at, is_active)
- [x] Add model relationships

### Pydantic Schemas
- [x] Create schemas directory
- [x] Create base response schema (standardized API response)
- [x] Create user schemas (UserCreate, UserLogin, UserResponse)
- [x] Create token schemas
- [x] Create error schemas
- [x] Add proper validation

### Authentication Enhancement
- [x] Refactor auth to use proper dependency injection
- [x] Add standardized error responses
- [x] Improve token handling
- [x] Fix circular import in authentication.py

### RBAC Implementation
- [x] Create role constants (ADMIN, RESEARCHER, EXPERT, VIEWER)
- [x] Create role assignment service
- [x] Create permission checking methods
- [ ] Add role-based route protection - **Optional for Phase 1**
- [x] Create admin user seeding script

### Audit Logging
- [x] Create audit service
- [x] Log authentication events
- [x] Log user actions

### Configuration
- [x] Create .env.example
- [x] Refactor config to centralized config.py
- [x] Add all required environment variables
- [x] Add validation for environment variables

### Testing
- [x] Set up pytest
- [x] Create test database configuration
- [x] Write tests for user registration
- [x] Write tests for duplicate registration
- [x] Write tests for user login
- [x] Write tests for invalid credentials
- [x] Write tests for JWT token validation
- [x] Write tests for protected routes
- [x] Run all tests and verify - 46/46 passing (2026-09-22)

### Code Quality
- [x] Remove circular imports
- [x] Add proper type hints
- [x] Add docstrings to complex functions
- [x] Refactor main.py to be smaller
- [x] Create routers directory
- [x] Move auth routes to auth router
- [x] Create services directory
- [x] Move business logic to services

### Documentation
- [x] Update README.md with setup instructions
- [x] Document API endpoints
- [x] Document environment variables

### Verification
- [x] All tests pass - 46/46 (2026-09-22)
- [x] Migrations work correctly - upgrade/downgrade verified transactionally (2026-09-22)
- [x] API endpoints respond correctly - scripts/verify_phase2.py, 27/27 checks (2026-09-22)
- [x] Error handling works - 404/401/403/422 paths covered by tests
- [x] RBAC works - ownership boundaries covered by tests; ADMIN bypass implemented
- [x] Audit logging works - product and version actions logged and verified
- [x] Database operations work - verified against PostgreSQL (Supabase)
- [x] Update PROJECT_STATUS.md to VERIFIED

---

## Phase 2: Product Passport and Versioning  (VERIFIED 2026-09-22)
- [x] Design Product model
- [x] Design ProductVersion model
- [x] Create migrations (002_product_passport)
- [x] Create schemas
- [x] Create routers
- [x] Create services
- [x] Implement CRUD operations
- [x] Implement version creation (content inherited by default)
- [x] Implement version retrieval
- [x] Implement version isolation
- [x] Add PUT /versions/{id} (change reason only)
- [x] Add POST /versions/{id}/clone
- [x] Add PUT /passport
- [x] Implement real snapshot_data + SHA-256 content_hash
- [x] Enforce ownership on every product and version route (IDOR fix)
- [x] Remove create_all() startup schema creation
- [x] Write tests (22 new version/authorization tests)
- [x] Verify (46/46 unit tests, 27/27 real-database checks, migration chain)

### Phase 2 follow-ups (not blocking)
- [x] Delete the legacy pre-Phase-1 modules at the BACKEND root (main.py, models.py, auth/, databases/, hash/) - done 2026-10-03, verified unimported by anything in app/tests/scripts; suite re-run after shows no new failures
- [ ] Block content edits to a version that already has a completed analysis
- [ ] Migrate Pydantic schemas from class-based Config to ConfigDict
- [ ] Make `is_active` non-writable through PUT /api/products/{id}

---

## Phase 3: Ingredients, Formulation, Claims, Evidence, Provenance  (VERIFIED 2026-09-22)
- [x] Design models (done in Phase 2; tables live in migration 002)
- [x] Confirm migration coverage (no new migration needed)
- [x] Implement ingredient CRUD
- [x] Implement formulation GET/PUT (one per version)
- [x] Implement claim CRUD
- [x] Implement evidence create/list/get/update
- [x] Implement target market CRUD
- [x] Link all content to product versions (version-scoped 404)
- [x] Add provenance tracking (server-stamped `USER_PROVIDED`)
- [x] Enforce the claim-to-evidence firewall (no self-declared `supported`)
- [x] Protect `EXPERT_VERIFIED` rows from user edits (409)
- [x] Refresh `snapshot_data` + `content_hash` after every edit
- [x] Audit-log every content mutation
- [x] Write tests (21 new version-content tests)
- [x] Verify (67/67 unit tests, 38/38 real-database checks)

### Phase 3 follow-ups (not blocking)
- [x] Implement `POST /versions/{id}/claims/analyze` with the Phase 5 AI stack (done 2026-09-23)
- [ ] Populate `evidence.document_hash` when files are ingested (Phase 8)
- [ ] Freeze version content once a completed analysis exists

---

## Phase 4: RAG Ingestion, Embeddings, Retrieval  (VERIFIED 2026-09-22)
- [x] Set up pgvector extension (migration 003)
- [x] Create document models (SourceDocument in app/models/rag_models.py)
- [x] Create chunk models (SourceChunk with vector + tsvector)
- [x] Implement document parsing (PDF via PyMuPDF + TXT in app/rag/parser.py)
- [x] Implement chunking strategy (800-token chunks, 120-token overlap, sentence boundaries)
- [x] Set up embedding provider (BGE-M3 / sentence-transformers in app/embeddings)
- [x] Set up LLM provider (Groq llama-3.3-70b-versatile in app/llm)
- [x] Implement vector storage (pgvector float array + cosine similarity)
- [x] Implement keyword search (PostgreSQL tsvector + ts_rank_cd)
- [x] Implement hybrid retrieval (RRF merge of vector + keyword arms)
- [x] Implement reranking (cross-encoder ms-marco-MiniLM-L-6-v2)
- [x] Implement citation validation (strict retrieved-chunk matching)
- [x] Implement insufficient-evidence fallback (prevents hallucination)
- [x] Implement custom user-uploaded data ingestion & scoping (private vs public)
- [x] Create Knowledge Base API (/api/knowledge/documents, status, delete, reindex)
- [x] Create Assistant Chat API (/api/assistant/chat, sessions CRUD, product context)
- [x] Write tests (22 new unit & API tests in tests/test_rag.py, 89/89 total passing)
- [x] Verify (scripts/verify_phase4.py 9/9 against live PostgreSQL + pgvector)
- [x] Integrate with frontend (Knowledge Base & RAG Chat test pages)

---

## Phase 5: IP-SAKTI Assistant  (VERIFIED 2026-09-23)

### Analysis foundation
- [x] Add `CLAIM_ANALYSIS` to the analysis type enum (migration 004)
- [x] Create `app/analysis/` package (schemas, prompts, claim analyzer, classifier)
- [x] Add the AI evidence-status clamp to the provenance firewall
- [x] Implement the structured-AI-output pipeline (JSON -> Pydantic -> citation validation -> safety clamp)

### Claim-to-evidence analysis
- [x] Implement `POST /api/products/{product_id}/versions/{version_id}/claims/analyze`
- [x] Retrieve corpus passages per claim (hybrid retrieval)
- [x] Produce per-claim assessment: suggested status, risk level, rationale, missing evidence
- [x] Block AI promotion of a claim (never `supported` / `expert_verified`)
- [x] Return `EXPERT_VERIFIED` claims locked and unmodified
- [x] Validate every citation against the retrieved set
- [x] Keep analysis advisory (no mutation of claim/evidence rows)

### Comprehensive analysis
- [x] Implement `POST /api/products/{product_id}/versions/{version_id}/analyze`
- [x] Preliminary product classification, validated against `ProductCategory`
- [x] Orchestrate the claim/evidence review
- [x] Derive target-market considerations and expert-review recommendations
- [x] Declare later-phase stages in `deferred_components`

### Persistence, retrieval and safety
- [x] Persist each run as one `analyses` row pinned to the reviewed version
- [x] Audit-log each run with the version `content_hash`
- [x] Record a `FAILED` row and return 503 on AI failure
- [x] Implement `GET /analyses` (with `analysis_type` filter) and `GET /analyses/{id}`
- [x] Scope analyses to the owning user and the correct version
- [x] Add disclaimers and warnings to every analysis response
- [x] Expose assistant source provenance (`PUBLIC_SOURCE` / `USER_PROVIDED`) in the chat response
- [x] Write tests (16 new tests in `tests/test_analysis.py`, 105/105 total)
- [x] Verify (`scripts/verify_phase5.py`, 37/37 against live PostgreSQL; migrations at head 004)

---

## Phase 6: IP Route Map, Patent Screening  (VERIFIED 2026-09-25)

### IP route map
- [x] Implement the route map endpoint (`GET .../ip-routes`)
- [x] Cover all nine routes (patent, trademark, copyright, design, GI, trade secret, plant variety, traditional knowledge, biodiversity/ABS)
- [x] Derive routes deterministically from recorded data (no AI-asserted applicability)
- [x] Use only careful labels (Potentially Relevant / Further Review Recommended / Not Indicated / Insufficient Information)

### Patent screening
- [x] Design patent models (`patent_records`, `patent_features`; migration 005)
- [x] Implement patent search against a frozen demonstration corpus
- [x] Label demo data explicitly (`DEMO_CORPUS`, `is_demo`, no real patent numbers)
- [x] Implement technical-feature extraction (species, plant part, extraction, solvent, temperature, pressure, duration, standardization, delivery form, effect, use)
- [x] Implement patent feature comparison (matching / different / unknown + similarity indicator + uncertainty)
- [x] Add `GET .../patents` and `GET /api/patents/{patent_id}`
- [x] Never claim patentability, novelty, validity, infringement or priority

### Biodiversity / ABS and traditional knowledge
- [x] Implement `POST .../biodiversity/screen` with the four allowed statuses
- [x] Implement `POST .../traditional-knowledge/screen`
- [x] Implement `GET /api/traditional-knowledge/sources` (public / permitted / restricted)
- [x] Keep restricted TKDL material out of every response
- [x] Make corpus-source retrieval opt-in so the default screen is fast and deterministic

### Cross-cutting
- [x] Add proper disclaimers (IP route, patent, biodiversity, traditional knowledge)
- [x] Replace the Phase 6 entries in `deferred_components`; embed the stages in comprehensive analysis
- [x] Write tests (25 new in `tests/test_phase6.py`)
- [x] Verify (`scripts/verify_phase6.py`, 57/57 live; migrations at head 005)

### Phase 6 follow-ups (not blocking)
- [ ] Replace the demonstration patent corpus with a real public-records source and flip `retrieval_mode` to `LIVE_SOURCE`
- [ ] Cache screening results by version content hash

---

## Phase 7: Formulation Change Impact Simulator  (VERIFIED 2026-09-26)

### Model and persistence
- [x] Design the change-impact model (`change_impacts`, migration 006)
- [x] Pin each run to both compared versions; never rewrite a historical run
- [x] Audit-log every run with both content hashes

### Comparison
- [x] Compare ingredients (added/removed/reidentified)
- [x] Compare botanical species
- [x] Compare plant parts
- [x] Compare quantities (amount and unit)
- [x] Compare resource origin
- [x] Compare cultivation/wild status (cultivated -> wild is significant)
- [x] Compare formulation and extraction process (method, solvent, temperature, pressure, duration, concentration)
- [x] Compare claims (added/removed, claim-type and evidence-status changes)
- [x] Compare evidence (added/removed, verification status)
- [x] Compare target markets (added/removed, regulatory status)
- [x] Compare patent-related signals (re-runs the Phase 6 feature engine on both versions)
- [x] Compare biodiversity/TK considerations (Phase 6 screening status of both versions)
- [x] Compare product classification when each version has a recorded one
- [x] Declare public disclosure and classification as not comparable rather than omitting them

### Report
- [x] Rank differences (informational / review recommended / significant)
- [x] Generate review questions per changed category
- [x] Always ask the disclosure-timing and expert-review questions
- [x] Derive the expert-review recommendation and its reasons
- [x] Add cautious notes and the change-impact disclaimer
- [x] Keep the comparison advisory (never edit either version)

### Endpoints and UI
- [x] `POST /api/products/{id}/change-impact`
- [x] `GET /api/products/{id}/change-impact` and `GET .../change-impact/{id}`
- [x] Frontend card on the versions page (from/to pickers, recorded-run picker, grouped differences, review questions, not-compared list)

### Verification
- [x] Write tests (20 new in `tests/test_phase7.py`)
- [x] Verify (`scripts/verify_phase7.py`, 48/48 live; migrations at head 006)

### Phase 7 follow-ups (not blocking)
- [ ] Add a deterministic classification signal so classification can always be compared
- [ ] Cache change-impact runs by the pair of content hashes

---

## Phase 8: Reports, Disclosure, Verification
- [x] Design disclosure model (`disclosures`, migration 007)
- [x] Implement version-scoped disclosure endpoints (`GET/POST .../disclosures`)
- [x] Implement disclosure review (`POST .../disclosure-review`, advisory vocabulary)
- [x] Implement global endpoints (`POST /api/disclosures`, `GET /api/disclosures/{id}`)
- [x] Implement public verification (`GET /api/disclosures/{id}/verify`, no auth)
- [x] Add SHA-256 hashing + verification id
- [x] Add mandatory invention-disclosure disclaimer
- [x] Wire disclosures into change-impact (no longer `not_compared`)
- [x] Write tests (`tests/test_phase8_disclosures.py`, 17 tests)
- [x] Verify (`scripts/verify_phase8a.py` 13/13 live; migrations 5/5 at head 007)
- [x] Set up ReportLab PDF generation (`app/reports/builders.py`)
- [x] Implement IP brief report (`POST .../reports/ip-brief`)
- [x] Implement disclosure record PDF (`POST .../reports/disclosure`)
- [x] Implement expert handoff report (`POST .../reports/expert-handoff`)
- [x] Add QR verification rendering (QR + verify URL in every PDF)
- [x] Verify reports (9/9 tests; migration 008; `verify_migrations.py` 5/5 at head 008)

---

## Phase 9: Expert Review Workflow
- [x] Design review model (`expert_reviews`, `review_comments`, migration 009)
- [x] Implement state machine (submit/request-review/comment/request-correction/resubmit/complete/archive)
- [x] Create review endpoints (`POST/GET /api/reviews`, transitions, comments)
- [x] Implement reviewer-only guards (403) and illegal-transition handling (409)
- [x] Implement EXPERT_VERIFIED promotion on completion (claims + evidence)
- [x] Write tests (`tests/test_phase9_reviews.py`, 9 tests)
- [x] Verify (`scripts/verify_phase9.py` 9/9 live; migrations 5/5 at head 009)

---

## Phase 10: Dashboard, Audit, Admin
- [x] Implement dashboard endpoint (`GET /api/dashboard`, owner-scoped aggregates)
- [x] Implement audit log retrieval (`GET /api/audit`, `GET /api/audit/{audit_id}`)
- [x] Implement admin endpoints (users, sources CRUD, RAG status, audit)
- [x] Add RBAC protection (`require_admin`; 403 asserted in tests)
- [x] Write tests (`tests/test_phase10_admin.py`, 9 tests)
- [x] Verify (9/9 pass; no migration required)

---

## Phase 11: BHASHINI Integration
- [x] Set up BHASHINI client (`app/bhashini/client.py`, honest unavailable behavior)
- [x] Implement language detection (`POST /api/bhashini/detect`)
- [x] Implement translation (`POST /api/bhashini/translate`, same-language passthrough)
- [x] Add glossary (18 controlled terms) + identifier preservation
- [x] Integrate with assistant (canonical query + translated answer + fallback warnings)
- [x] Handle fallbacks (original preserved, warning, English fallback)
- [x] Write tests (`tests/test_phase11_bhashini.py`, 8 tests)
- [x] Verify (8/8 pass; RAG 22/22 unaffected)

---

## Phase 12: Simple Frontend Integration
- [x] Set up React + Vite (existing skeleton reused)
- [x] Implement login page
- [x] Implement register page
- [x] Implement dashboard / product list
- [x] Implement new product form
- [x] Implement version list + new version form
- [x] Implement version detail with ingredient/formulation/claim/evidence/market editors
- [x] Wire to backend APIs (`/api/...`)
- [x] Test full flow end to end (`scripts/verify_frontend_flow.py`, 36/36 -> now 50/50)

### Phase 5 analysis UI (added 2026-09-23)
- [x] Add API client methods for analyse/list/read analyses
- [x] Add the Analysis section to the version detail page (`/products/:id/versions/:versionId`)
- [x] "Analyze claims" and "Full analysis" run buttons with loading and error states
- [x] Recorded-run picker (type, status, timestamp) so past runs can be reviewed
- [x] Claim assessment cards: declared vs AI-suggested status, risk, review status, provenance, rationale, missing evidence, citations with quoted passages
- [x] Render expert-verified locked notices
- [x] Render comprehensive extras: preliminary classification, target-market considerations, missing information, deferred later-phase components, recommendations, warnings/disclaimers
- [x] Handle the 503 AI-unavailable response in the UI and reload the recorded failed run
- [x] Show chat source provenance (PUBLIC_SOURCE / USER_PROVIDED) in the RAG assistant
- [x] Verify production build (`vite build`) and re-run the flow test (50/50 live)
- [ ] Finish as a real product UI (Phase 12, later)

### Login / register fix (added 2026-09-24)
- [x] `parseResponse` now accepts a `fetch()` promise or a `Response` (fixes `res.json is not a function` for every API call)
- [x] `register` / `login` send JSON bodies instead of urlencoded form data (fixes the 422s)
- [x] `register` sends `confirm_password` (the schema field name) and validates the 8-character minimum client-side
- [x] Human-readable FastAPI validation errors (field name + message) instead of `[object Object]`
- [x] Session restore via `POST /api/auth/refresh` (httpOnly cookie) instead of a credential-less login probe
- [x] `logout` uses `POST /api/auth/logout` (the route is not a GET)
- [x] Outer route mounted at `path="/*"` so `/products`, `/knowledge`, `/chat` deep links render
- [x] `Button` forwards `type` so `type="button"` controls stop submitting their form
- [x] Verify in a real browser: register 201 -> login 200 -> `/auth/me` 200 -> reload keeps the session -> deep links work

### Phase 7 change-impact UI (added 2026-09-26)
- [x] Add API client methods for run/list/read change-impact comparisons
- [x] Add the "Formulation change impact (Phase 7)" card to the versions page
- [x] From/To version pickers defaulting to the two newest versions
- [x] Recorded-comparison picker
- [x] Render differences grouped by category with added/removed/modified and significance badges
- [x] Render the expert-review reasons, review questions and not-compared list
- [x] Stack the versions page cards (`.page-stack`) instead of side-by-side
- [x] Verify in a browser and re-run the flow test (108/108 live)

### Phase 6 IP screening UI (added 2026-09-25)
- [x] Add API client methods for IP routes, patent search/list/detail/compare, biodiversity screen, TK screen and TK sources
- [x] Add the "IP screening (Phase 6)" section to the version detail page
- [x] Render the IP route map with labels, signals and review questions
- [x] Render patent screening: aggregate matching/different/unknown features and per-record feature tables with verdicts
- [x] Add a re-run comparison control
- [x] Render biodiversity/ABS and TK screening results (status, considerations, missing information, review questions, sources)
- [x] Render the TK source registry with restricted entries marked "not accessed"
- [x] Add the "include corpus sources" opt-in checkbox
- [x] Render the Phase 6 components embedded in a comprehensive analysis
- [x] Fix the `Products` delete bug (undeclared `setError`)
- [x] Verify in a browser and re-run the flow test (90/90 live)

### Phase 12 UI (added 2026-09-26)
- [x] Add API client methods (disclosures, reports + download, reviews, dashboard, audit, BHASHINI)
- [x] Add `DisclosuresSection` + `ReportsSection` to the version detail page
- [x] Add `/reviews` page (create, transition buttons, comments)
- [~] `/dashboard` page REMOVED on user request (2026-10-04) - nav link, route and `Dashboard()` deleted from `App.jsx`; Home stat tiles still reuse the backend `GET /api/dashboard` endpoint, which is unchanged
- [x] Add chat input/output language selects wired to `input_language`/`output_language`
- [x] Verify production build (`vite build`, 0 errors)
- [x] Extend `scripts/verify_frontend_flow.py` (+19 checks, 127/127 live)

### Demo showcase (added 2026-09-26, judge walkthrough at `/demo`)
- [x] `FormulationRiskDashboard` — live scoring + SVG gauges, cure-claim CRITICAL banner
- [x] `ProtectionTimeline` — before/after animated timelines with replay
- [x] `IPRiskMap` — D3 force graph (npm `d3`), draggable, tooltips, risk ring, legend
- [x] All three wired into `/demo` + nav; production build clean and verified in bundle
- [~] **Superseded 2026-09-28:** the Live Demo section is replaced by the
  Overall Product View (`/overview`); `FormulationRiskDashboard.jsx` and
  `IPRiskMap.jsx` deleted, `DemoShowcase` removed, `/demo` redirects;
  `d3` no longer imported by any component

### Verified auth endpoint reference (what the UI must send)
- `POST /api/auth/register` - JSON `{username, email, password, confirm_password}`; returns the user only, **no token**
- `POST /api/auth/login` - JSON `{email, password}`; returns `data.access_token` and sets the refresh cookie
- `POST /api/auth/refresh` - no body; reads the refresh cookie, returns a new access token
- `POST /api/auth/logout` - no body; clears the refresh cookie

---

## Phase 13: Integration Testing, Security Review, Documentation
- [x] Run full integration tests (203/203 pytest; 127/127 frontend flow; 26/26 demo flow)
- [x] Security review (secrets, SQL, uploads, error handling, RBAC - clean)
- [x] Fix retrieval fallback bug (keyword-only when embeddings missing)
- [x] Fix 401-on-missing-token (5 auth tests)
- [x] Complete documentation (README phases 8-13, requirements, .env.example)
- [x] Demo workflow verification (`scripts/verify_demo_flow.py`)
- [x] Final verification (migrations 5/5 at head 009)

---

## RAG selective/partial answering (master-prompt items 16-17) — VERIFIED 2026-09-27

- [x] Root-cause diagnosis with live DB evidence (tsquery AND=0, dead vector arm, global abstention flag, prompt-only attachments)
- [x] OR-based keyword search + SQLite ILIKE fallback; query expansion + synonym groups
- [x] Page-aware, header/footer-stripped, section-carrying chunking with content_hash/provenance/page metadata; empty chunks skipped
- [x] `partial_answer.py`: decomposition, per-subquestion retrieval, per-section statuses/provenance/citations/metrics, enforcement gates (jurisdiction, banned conclusions, citation validation, claims classification)
- [x] Selective routing in `assistant.py`; ChatResponse `overall_status`/`sections`/`disclaimer`/`debug` (DEBUG=true only)
- [x] Attachment indexing (`document_id` FK, migration 011 applied) + content-hash dedupe
- [x] Prompt-size budget for live provider limits (Groq 8k TPM / Sarvam 32k window)
- [x] `_ANSWERED_STATUSES` includes PARTIALLY_SUPPORTED (response-level over-abstention fix)
- [x] Per-query diagnostics logging (`logging.basicConfig(INFO)` in main.py)
- [x] `sentence-transformers` installed; vector arm + cross-encoder reranker reactivated
- [x] Tests: new `tests/test_partial_answering.py` (24) — full suite **286 passed**
- [x] Exact spec-17 live scenario: **16/16 checks passed** (real LLM)

---

## Product Passport analysis spec - reported bugs 1-12 - VERIFIED 2026-09-27

- [x] BUG 1 - claims scoped to `product_version_id`; runs persist/serialize the analysed `content_hash`; frontend staleness badge; `NO_CLAIMS_RECORDED` version-scoped with explanation
- [x] BUG 2 - source location labelled distinctly; both target countries returned; no derived market (test asserts no "west bengal")
- [x] BUG 3 - formulation `"" -> null` coercion (schema + service + frontend); exact shape incl. `cold_press`/4/`C`; `MISSING_PARAMETERS_NOTE` auto-fill; Temperature unit input
- [x] BUG 4 - deterministic classification gate: UNRESOLVED + three pathways + LOW confidence + five information requirements + review_required; updates when information arrives
- [x] BUG 5 - per-route `status/label/why_flagged/missing_information/next_action/limitation` with spec-exact texts; frontend renders all five
- [x] BUG 6 - `record_verification_fields` + `DEMO_RECORD_LABEL`/`VERIFIED_RECORD_LABEL` + `corpus_type`/`live_search_performed`/`records_verified` on responses; per-record banner
- [x] BUG 7 - source metadata (vocab, human jurisdiction, authority, access/verification status, URL, retrieved_at); `TKDL_RESTRICTED_LABEL`; `human_jurisdiction` at citations **and** patent records; no "AVAILABLE IN"
- [x] BUG 8 - `AnalysisSummary` + `_build_analysis_summary` + frontend summary card
- [x] BUG 9 - `SignalExplanation` on claim/patent/biodiversity/TK + frontend "Why this result?"
- [x] BUG 10 - `affected_areas` (seven spec areas in order) / `reassessment_recommended` / `missing_information` / `review_questions`; V2 seeded from V1 via `copy_from_version_id`; no approval statement
- [x] BUG 11 - exact `PUBLIC_DISCLOSURE_DISCLAIMER`, no deadlines/banned phrases
- [x] BUG 12 - reports use recorded claims/markets/formulation/provenance/corpus/uncertainty (content sections in all three PDFs)
- [x] Tests: `tests/test_acceptance_spec.py` (34) - full suite **329 passed**; live `verify_frontend_flow.py` **139/139**; `spec17_live.py` **35/35**; ESLint **12 = baseline**

---

## Chatbot jurisdiction scope: market-entry evidence, citations and UI - VERIFIED 2026-09-27

- [x] Root-cause with live-DB evidence: 108/108 corpus docs tagged `jurisdiction='India'` (incl. 21 CFR/FDA, China, PIC/S, WIPO); no market-derived scope in the chat flow; jurisdiction gates keyed off question text only
- [x] New `app/rag/jurisdiction_scope.py`: market -> allowed jurisdictions, scope filter with exclusion logging, `JurisdictionScopeTracker` (over-retrieve 18 / filter / trim 6, `retrieval.py` untouched), `MARKET CONTEXT` prompt block (rules 1-8, dynamic section names, ~10-part launch structure), launch-question detection, evidence status (SUFFICIENT / PARTIALLY_SUPPORTED / INSUFFICIENT + CANNOT_BE_DETERMINED + spec reason), exact rule-6 + launch-gap sentences, ordered 7-item missing-information list, claim standing, U.S.-reference sanitizer
- [x] Scope block threaded into both the single-shot (`generation.py`) and selective (`partial_answer.py`) prompts
- [x] `assistant.py`: scope from the selected version snapshot before filters; tracker wraps both retrieval paths; U.S.-reference stripping + per-section gap fallbacks + market gap warnings; 14 new `ChatResponse` fields; `filters_applied` market entries; `getattr(..., "rag_rerank_top_k", 6)` for partial settings stubs
- [x] `scripts/fix_corpus_jurisdictions.py` run on live DB: 12 docs corrected (9 United States, 1 China, 2 International); distribution India 96 / US 9 / untagged 7 / International 2 / China 1
- [x] Frontend: assistantMsg captures the new fields; `ChatMarketPanel` (MARKET CONTEXT / SOURCE SCOPE / EVIDENCE STATUS / JURISDICTION WARNING + gap warnings + collapsible "Why this answer?" with counts, exclusions, missing info, claim reviews) + CSS
- [x] Tests: `tests/test_chat_jurisdiction.py` (16) - full suite **345 passed**; ESLint **12 = baseline**; `verify_frontend_flow.py` **139/139**; `spec18_live.py` (real LLM, exact launch question) **11/11 checks PASS**
- [ ] Persist the panel metadata on `chat_messages` (migration) so old sessions show it after a history reload
- [ ] Ingest verified Germany/EU sources (first source file now on disk: `eu-germany-herbal-medicinal-product-market-access.md`, added 2026-09-28; still not ingested - gaps remain correct by design until then)
- [ ] Provide the Bhashini key (translation stays in honest fallback until then)

---

## Chatbot Product Passport access: no more "I cannot access your product" - VERIFIED 2026-09-27

- [x] Root-cause: SYSTEM_PROMPT said "Answer ONLY using the provided context passages" while the passport arrived under a bare `=== PRODUCT CONTEXT ===` header with no usage instruction; both generation paths aborted (and selective Gate 1 abstained) when the corpus matched nothing, even with a passport selected
- [x] `generation.py`: SYSTEM_PROMPT "WHAT YOU ALREADY HAVE ACCESS TO" inventory + rule 8 (never disclaim access to the product/files/database when PRODUCT CONTEXT is present); passport header "It IS available to you..." + attribution as "Product Passport (user-provided)"; `generate_rag_answer(launch_question=...)` - passport-only questions reach the model
- [x] `partial_answer.py`: same instructions in `PARTIAL_SYSTEM_PROMPT` rule 4 / `build_partial_prompt`; full-abstention and Gate 1 now honour `used_product_context` (provenance stays USER_PROVIDED; jurisdiction gate + banned-conclusion stripping intact)
- [x] `assistant.py`: threads `launch_question` into generation - **launch questions keep the deterministic evidence-gap path** (spec TEST 4/5 `fake.calls == 0`; a passport can never prove launch readiness)
- [x] Tests: `tests/test_chat_product_context.py` (12) - full suite **357 passed** (345 baseline + 12); live `passport_access_live.py` (real LLM, exact reported question + knowledge question, fresh AshwaBio-X V1) **8/8 checks PASS**
- [ ] Reword the single-path warning "produced from retrieved sources, but no verifiable citations were attached" when the ground is the passport, not retrieved sources

---

## Overall Product View: Live Demo replacement (spec items 16-19) - VERIFIED 2026-09-28

### Backend contract
- [x] `GET /api/products/{id}/versions/{vid}/overview` (`app/services/overview_service.py`, `app/routers/overview.py`, mounted in `main.py`)
- [x] 16-section stored-data JSON with provenance on every value where practical (product, overall_status, facts, formulation, ingredients, claims, evidence, target_markets, regulatory_classification, ip_review, biodiversity_abs_review, traditional_knowledge_review, disclosures, analysis_history, recommended_actions, missing_information, provenance, disclaimers)
- [x] Deterministic overall-status precedence + confidence (NOT_ASSESSED/LOW/LOW/MEDIUM/MEDIUM/HIGH); only the six allowed statuses - never SAFE_TO_LAUNCH / APPROVED / LEGALLY_COMPLIANT / PATENT_SAFE / NO_RISK
- [x] Exact spec sentences as constants (preliminary-decision-support notice, overdue-hash warning, no-market-evidence, no-patent-result, claim user-provided warning, no-evidence-documents, no-disclosure-event, TK restricted-sources, DEMO CORPUS label)
- [x] IP review omits demo records (`records=[]`, `synthetic_records_omitted`, `demo_notice`, SEARCH_UNAVAILABLE); no hard-coded risk values anywhere
- [x] Recommended actions derived only from actual gaps (run_analysis / rerun_analysis / add_*), priorities HIGH/MEDIUM/LOW
- [x] Chatbot consumes the same object (`overview_context_for_chat` attached in `assistant.py`) - no second interpretation

### Frontend
- [x] `api.productOverview`; routes `/overview`, `/overview/:id/:versionId`; `/demo` -> `<Navigate to="/overview" replace />`
- [x] Sidebar link "Overall Product View"; home card + `Landing.jsx` links renamed (zero "Live Demo" / "illustrative demo" strings in `src`)
- [x] `OverallProductView` in `App.jsx`: version header (product, version, content hash w/ full hash on hover, created/updated, analysis status/run/timestamp) + "All versions" control; preliminary-decision-support notices; overall-status card with overdue alert + "Re-run analysis" (real `api.analyzeProduct`); 13 sections in spec order; Provenance footer; `OV_CSS`
- [x] Key-derivation state (no sync setState in effects) so switching versions reloads every section and never mixes versions; loading/empty/error/outdated/missing-info states per section
- [x] Deleted `FormulationRiskDashboard.jsx`, `IPRiskMap.jsx`; `DemoShowcase` removed
- [x] Editing stays on the passport pages - the overview never mutates a version

### Verification (2026-09-28)
- [x] `pytest tests/ -q` -> **386 passed** (357 baseline + 29 new `tests/test_overview.py`)
- [x] `scripts/verify_frontend_flow.py` -> **139/139** against restarted uvicorn
- [x] `scripts/overview_live.py` (new) -> **84/84 checks PASSED**, incl. outdated-analysis transition and version-scoped hash
- [x] `npm run lint` -> **12 = baseline**; `npx vite build` -> OK (462.58 kB)

### Follow-ups (not blocking)
- [ ] Visual browser check of `/overview` (no desktop browser connected this session - verified via lint, build and API contract only)
- [ ] `pool_pre_ping=True` on the SQLAlchemy engine - remote Supabase pooler dropped connections twice this session (stable module, out of scope)
- [ ] Version `updated_at` column is not stored - overview reports `updated_at: null` with an honest note
- [ ] Germany/EU corpus still empty **in the database** - a first source file exists on disk (2026-09-28) but is not ingested, so market sections still show the exact no-evidence sentence by design
- [ ] Replace the demonstration patent corpus with a real public-records source (existing Phase 6 follow-up)
- [ ] Bhashini key still not provided (translation stays in honest fallback)

---

## RAG corpus: 12 required statute/regulation study files - ADDED 2026-09-28

- [x] `drugs-and-magic-remedies-objectionable-advertisements-act-1954.md` (196)
- [x] `patent-amendment-rules-2024-india.md` (175)
- [x] `geographical-indications-act-1999-india.md` (206)
- [x] `trade-marks-act-1999-india.md` (215)
- [x] `designs-act-2000-india.md` (180) - typo fix applied in the same session
- [x] `copyright-act-1957-india.md` (199)
- [x] `plant-variety-farmers-rights-act-2001-india.md` (216)
- [x] `biological-diversity-rules-2024-india.md` (221)
- [x] `fssai-ayurveda-aahar-regulations-2022.md` (165)
- [x] `section-3j-3p-patenting-bar-tkdl-guidance.md` (217)
- [x] `first-schedule-authoritative-texts-ayurveda.md` (172)
- [x] `ayurvedic-pharmacopoeia-india-standards.md` (172)
- [ ] Re-ingest the corpus so the new files are embedded and chunked (run
  `scripts/ingest_corpus.py` against the live DB - not done in this session)
- [ ] After re-ingest, confirm the jurisdiction/metadata pass labels the new
  India files correctly (see the session-4 `fix_corpus_jurisdictions.py` run)

---

## RAG corpus: 9 international IP / regime / case-law study files - ADDED 2026-09-28

Closes the sources gap: international treaties/regimes (TRIPS, CBD, Nagoya,
PCT, Madrid, Hague, Budapest), Indian case law, and the first Germany/EU
market-access source. ADD only - no pre-existing corpus file was deleted,
renamed or modified.

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

- [x] All 9 files: fixed frontmatter template, top-level official `source_url`,
  single-line `## Verification note`, `##`/`###` headings + tables for
  section-aware chunking (scripted check: PASS on all 9)
- [ ] Re-ingest the corpus so these 9 files are embedded and chunked too
  (`scripts/ingest_corpus.py` against the live DB - not done in this session)
- [ ] Confirm the jurisdiction/metadata pass labels these files as intended
  (India / International / Germany-EU)
- [ ] Germany/EU market evidence now has a source **on disk** but is still not
  ingested - market sections keep the honest no-evidence sentence until ingest

---

## Problem-statement completion batch (2026-10-04, Bhashini excluded)

- [x] Explicit jurisdiction switch: `jurisdiction_mode` (both/india/international) on chat, strict scope, toolbar control, 5 new tests
- [x] Citation confidence indicator populated from reranker scores (all paths via `validate_citations`) + chat badge UI
- [x] Mount privacy + official-sources registry routers (migration 012 for fresh DBs)
- [x] Mount knowledge-graph + agent routers, fix `AgentRun` import (migration 013), 8 new tests
- [x] Clarification model/service/router/endpoints (migration 014), version-page Q&A card, 6 new tests
- [x] Fix BUG-4 pathways drift (test aligned to the six problem-statement categories)
- [x] Fix `ingest_document` int/object contract crash + cross-checkout stale-path fallback
- [x] Deploy artifacts: backend/frontend Dockerfiles, nginx conf, full-stack compose, README deploy docs
- [~] Corpus ingest of the remaining disk files (bulk done; OOM/timeout retries in progress)
- [ ] Re-run `scripts/fix_corpus_jurisdictions.py` after ingest, confirm India/International/Germany-EU labelling
- [ ] Persist the chat panel metadata on `chat_messages` so history reloads show it (pre-existing open item)
- [ ] Bhashini API key (translation stays in honest fallback until provided)

## Legend
- [ ] Not started
- [~] In progress
- [x] Completed
- [!] Blocked
