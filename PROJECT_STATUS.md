# IP-SAKTI Sahayak - Project Status

**Last Updated:** 2026-09-28

## Overall Status: ALL PHASES VERIFIED (0-13 complete)

**Latest verified (2026-09-28, session 5): Overall Product View - the Live
Demo section is replaced by a production data view backed by real stored
rows (spec items 16-19)**
- Reported: the "Live Demo" section showed synthetic demo data (risk gauges,
  fabricated patent nodes, hard-coded scores) instead of the selected
  Product Passport, and read like a prediction/approval tool.
- What was built: `GET /api/products/{id}/versions/{vid}/overview`
  (`app/services/overview_service.py` + `app/routers/overview.py`) returns the
  16-section stored-data contract with provenance on every value where
  practical, the deterministic overall-status precedence
  (COMPLETE_FOR_REVIEW / PARTIALLY_COMPLETE / INSUFFICIENT_INFORMATION /
  ANALYSIS_NOT_RUN / ANALYSIS_OUTDATED / REVIEW_REQUIRED - never
  SAFE_TO_LAUNCH / APPROVED / LEGALLY_COMPLIANT / PATENT_SAFE / NO_RISK),
  the exact spec sentences, IP review that omits demo records
  (`records=[]` + `synthetic_records_omitted` + DEMO_CORPUS notice,
  SEARCH_UNAVAILABLE), and recommended actions derived only from actual gaps
  (HIGH/MEDIUM/LOW). The chatbot receives the same object
  (`overview_context_for_chat`) so page and answer cannot diverge.
- Frontend: `/overview` and `/overview/:id/:versionId` (`App.jsx`
  `OverallProductView`) with version header + content hash (full hash on
  hover), 13 sections in spec order, per-section loading/empty/error/outdated
  states, key-derivation state so versions never mix, "Re-run analysis"
  wired to the real analyze endpoint; `/demo` redirects to `/overview`;
  `FormulationRiskDashboard.jsx` and `IPRiskMap.jsx` deleted; no "Live Demo"
  or "illustrative demo" text anywhere in `src`.
- Evidence: `tests/test_overview.py` (29) - full suite **386 passed**;
  new live `scripts/overview_live.py` **84/84 checks PASSED** (fresh
  AshwaBio-X passport -> screenings -> real comprehensive analysis -> claim
  edit forces ANALYSIS_OUTDATED; final output: ANALYSIS_OUTDATED/LOW
  confidence, claim USER_PROVIDED_ONLY / DO NOT PRESENT AS VERIFIED /
  REVIEW_REQUIRED, markets INDIA + GERMANY/EU, classification UNRESOLVED
  (source ANALYSIS_DERIVED), ip SEARCH_UNAVAILABLE with 4 synthetic omitted
  and 0 verified records, 4 analysis runs, 10 actions);
  `verify_frontend_flow.py` **139/139** against the restarted server;
  ESLint **12 = baseline**; `npx vite build` OK (462.58 kB).
- Environment note: the remote Supabase pooler was intermittently slow or
  dropping connections this session (fresh session setup measured at 9 s;
  two runs hit transport errors). Infra, not code - uvicorn restarted to
  clear the stale pool; the live script now reports transport errors as
  FAILs instead of crashing. Suggested follow-up: `pool_pre_ping=True`
  (not applied - stable module, out of scope).

**Previously verified (2026-09-27, session 4): Chatbot Product Passport access - the model now answers from the selected passport instead of denying access**
- Reported: with Context Options on AshwaBio-X V1 the chatbot said "I do not
  have the ability to access external product files or databases". Root
  causes: (1) the SYSTEM_PROMPT said "Answer ONLY using the provided context
  passages" while the passport arrived under a bare `=== PRODUCT CONTEXT ===`
  header with no usage instruction; (2) both generation paths aborted (and
  the selective path's Gate 1 abstained) before reading the model's answer
  whenever the corpus matched nothing, even with a passport selected.
- Fix: SYSTEM_PROMPT "WHAT YOU ALREADY HAVE ACCESS TO" inventory + new rule
  never to disclaim access to the product/files/database when PRODUCT
  CONTEXT is present; passport header "It IS available to you..." with
  attribution wording; passport-only questions reach the model in both paths;
  Gate 1 skips its abstain-out when `used_product_context` (provenance stays
  USER_PROVIDED, jurisdiction gate and banned-conclusion stripping intact).
  **Launch questions keep the deterministic evidence-gap path**
  (`launch_question` flag): spec TEST 4/5's `fake.calls == 0` guarantee is
  preserved - a passport can never prove launch readiness.
- Evidence: new `tests/test_chat_product_context.py` (12 tests); full suite
  **357 passed** (345 baseline + 12; 720s); live `passport_access_live.py`
  (real LLM, exact reported question + knowledge question against fresh
  AshwaBio-X V1) **8/8 checks PASS** - "Yes. I have access to the Product
  Passport version you provided ... AshwaBio-X, version 1", ingredients
  question returns the passport facts verbatim (Withania somnifera root,
  100 g, Uttarakhand), `insufficient_evidence=False`,
  `market_context=["India","Germany/EU"]`, zero 21 CFR leakage.

**Previously verified (2026-09-27, session 3): Chatbot jurisdiction scope - market-entry evidence, citations and UI**
- The chatbot now derives its jurisdiction scope from the selected Product
  Passport target markets: retrieval is filtered per market, the prompt carries
  the `MARKET CONTEXT` rules (per-market sections, no cross-country
  substitution, launch-readiness structure), produced answers are scrubbed of
  unselected U.S. references, and the response reports market context,
  jurisdiction filter, excluded jurisdictions, evidence status
  (SUFFICIENT/PARTIALLY_SUPPORTED/INSUFFICIENT + CANNOT_BE_DETERMINED),
  market-specific gap warnings, a "Why this answer?" payload and per-claim
  reviews (USER_PROVIDED_ONLY / NOT_FOUND / REVIEW_REQUIRED).
- Corpus metadata corrected on the live DB: 12 mislabelled documents (9 U.S.,
  1 China, 2 International) - U.S. 21 CFR CGMP can no longer pass as "India".
- Evidence: new `tests/test_chat_jurisdiction.py` (16 tests, spec TEST 1-10 +
  sanitizer/multi-part/sarvam parity) - full suite **345 passed** (329
  baseline + 16); ESLint **12 = baseline**; live `verify_frontend_flow.py`
  **139/139**; `spec18_live.py` (real LLM, exact launch question, fresh
  AshwaBio-X V1) **11/11 checks PASS** - answer opens "Launch readiness: Cannot
  be determined from the current information.", zero 21 CFR references, server
  log shows `Jurisdiction scope [India, Germany, European Union]: excluded 8
  candidate chunk(s) from China, United States`.

**Previously verified (2026-09-27, session 2): Product Passport analysis spec - the 12 reported bugs (BUG 1-12)**
- All twelve bugs root-caused (live-DB evidence) and fixed at the narrowest
  layer: claim provenance + run staleness (content_hash pinning), source
  location vs target markets, exact formulation shape with `"" -> null` and the
  "not yet provided" note, UNRESOLVED classification gate with the spec's five
  information requirements, five-field evidence-based IP routes, demo/verified
  corpus labelling everywhere, explicit source metadata (TKDL restricted label,
  human jurisdictions - no raw `IN`/`INT`, no "AVAILABLE IN"), analysis summary
  card, "Why this result?" explanations, change-impact areas/reassessment/missing
  info (exactly the seven spec areas for the acceptance scenario), the exact
  public-disclosure disclaimer (no deadlines), and report content built from the
  recorded claims/markets/formulation/provenance/corpus.
- Evidence: new `tests/test_acceptance_spec.py` (34 tests, acceptance steps
  1-14) - full suite **329 passed** (295 baseline + 34); ESLint **12 = baseline**;
  live `scripts/verify_frontend_flow.py` **139/139** after uvicorn restart;
  `spec17_live.py` (real LLM) **35/35**.

**Previously verified (2026-09-27): RAG selective/partial answering (master-prompt items 16-17)**
- Multi-part questions decompose and answer **per sub-part**; only unsupported
  sub-parts abstain (SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE
  per section, next_action on every abstention, no whole-question rejection).
- Evidence: `pytest tests/ -q` **286 passed**; exact spec-17 live scenario
  (real LLM) **16/16 checks passed** - overall PARTIALLY_SUPPORTED, 8
  validated citations with page numbers, 40% claim USER_PROVIDED /
  not-independently-verified / review_required, spec-vocabulary provenance,
  exact disclaimer, no banned conclusions.
- Semantic arm reactivated (`sentence-transformers` installed; live log shows
  `Retrieval arms: vector=20, keyword=20` + cross-encoder reranker +
  `embeddings=yes`); per-query diagnostics now reach the server log.

---

## Phase Progress

### Phase 0: Repository Inspection and Planning
- **Status:** VERIFIED
- **Completed:** 2026-09-21

### Phase 1: Backend Foundation, Database, Authentication, JWT, RBAC
- **Status:** VERIFIED
- **Started / Completed / Verified:** 2026-09-21
- **Evidence:** 11 auth tests pass; register/login/me verified end to end against PostgreSQL

### Phase 2: Product Passport and Versioning
- **Status:** VERIFIED
- **Started:** 2026-09-21
- **Implemented:** 2026-09-21
- **Verified:** 2026-09-22 15:20 IST
- **Evidence:**
  - 46/46 pytest tests pass (SQLite in-memory, 53s)
  - `scripts/verify_phase2.py`: 27/27 checks pass against the real PostgreSQL database
  - `scripts/verify_migrations.py`: downgrade base + upgrade head verified inside a rolled-back transaction
  - Database confirmed at alembic revision `002 (head)` with all 12 migrated tables

#### Phase 2 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| Product model + migration | VERIFIED | `products`, `product_versions` created by migration 002 |
| Product CRUD | VERIFIED | create/list/get/update/soft-delete, all with ownership checks |
| Product Passport (GET/PUT) | VERIFIED | Full passport: product + current version + version count + latest analysis |
| Version creation | VERIFIED | Auto-numbered; copies current version content by default (`start_empty` for blank) |
| Version retrieval/isolation | VERIFIED | Version must belong to the product; `PUT` for change reason |
| Version clone | VERIFIED | `POST /versions/{id}/clone` deep-copies all version content |
| Content snapshots | VERIFIED | `snapshot_data` = canonical JSON of version content |
| Content hashes | VERIFIED | `content_hash` = SHA-256 of content only; clone preserves it |
| Ownership / IDOR protection | VERIFIED | Cross-user access returns 404 for read, write, delete and version routes |
| RBAC on products | VERIFIED | Owner-only; ADMIN sees all products |
| Audit logging on product ops | VERIFIED | create/update/delete/version actions logged |

### Phase 3: Ingredients, Formulation, Claims, Evidence, Provenance
- **Status:** VERIFIED
- **Started:** 2026-09-22
- **Implemented / Verified:** 2026-09-22 15:50 IST
- **Evidence:**
  - 67/67 pytest tests pass (SQLite in-memory)
  - `scripts/verify_phase3.py`: 38/38 checks pass against the real PostgreSQL database
  - `content_hash` and `snapshot_data` refresh after every content mutation (verified)

#### Phase 3 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| Ingredient CRUD | VERIFIED | list/create/update/delete under `/versions/{id}/ingredients` |
| Formulation GET/PUT | VERIFIED | one per version; PUT merges fields (create-then-update) |
| Claim CRUD | VERIFIED | create/list/update/delete; evidence status restricted |
| Evidence CRUD | VERIFIED | create/list/get/update; provenance + verification status |
| Target market CRUD | VERIFIED | list/create/update/delete under `/target-markets` |
| Version scoping | VERIFIED | child ids from another version/owner return 404 |
| Ownership / IDOR protection | VERIFIED | nested routes require an owned product (ADMIN bypass) |
| Provenance firewall | VERIFIED | server stamps `USER_PROVIDED`; clients cannot set provenance |
| EXPERT_VERIFIED protection | VERIFIED | edits/deletes of verified rows return 409 |
| Evidence-status firewall | VERIFIED | users limited to `user_provided`/`needs_evidence` (422 otherwise) |
| Content hash refresh | VERIFIED | every edit recomputes snapshot + SHA-256 `content_hash` |
| Version isolation | VERIFIED | editing v2 leaves v1's hash untouched |
| Audit logging on content ops | VERIFIED | each edit logs action + resulting content_hash |

**Not in this phase (deliberately deferred):** `POST /claims/analyze` (needs the AI/RAG stack, Phase 5) and `evidence.document_hash` (needs file ingestion, Phase 8).

### Phase 4: RAG System (Ingestion, pgvector, Hybrid Retrieval, Citations, Custom User Data)
- **Status:** VERIFIED
- **Started:** 2026-09-22
- **Implemented / Verified:** 2026-09-22 18:30 IST
- **Evidence:**
  - 89/89 pytest tests pass (0 failures)
  - `scripts/verify_phase4.py`: 9/9 live PostgreSQL + pgvector checks pass
  - Migration 003 applied: `pgvector` enabled, `source_documents`, `source_chunks`, `chat_sessions`, `chat_messages` tables created
  - Frontend built and verified with zero compilation errors (`dist/assets` built via Vite)

#### Phase 4 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| pgvector extension | VERIFIED | `CREATE EXTENSION IF NOT EXISTS vector;` applied in migration 003 |
| RAG database schema | VERIFIED | `source_documents`, `source_chunks`, `chat_sessions`, `chat_messages` |
| BGE-M3 embedding provider | VERIFIED | `app/embeddings/bge_m3_provider.py`, dense 1024-dim, BAAI/bge-m3 |
| Groq LLM provider | VERIFIED | `app/llm/groq_provider.py`, `llama-3.3-70b-versatile`, JSON structured output |
| Document parsing (PDF & TXT) | VERIFIED | `app/rag/parser.py`, page-aware text extraction with PyMuPDF & plain text |
| Chunking pipeline | VERIFIED | `app/rag/chunking.py`, 800-token chunks with 120-token overlap & sentence boundaries |
| Ingestion & dedup | VERIFIED | `app/rag/ingestion.py`, SHA-256 deduplication, chunking, embedding, FTS vector |
| Hybrid retrieval (pgvector + FTS) | VERIFIED | `app/rag/retrieval.py`, pgvector cosine distance + PostgreSQL ts_rank_cd |
| RRF fusion & reranking | VERIFIED | Reciprocal Rank Fusion + cross-encoder reranker with fallback |
| Citation validation | VERIFIED | `app/rag/citation.py`, verifies all cited chunk IDs exist in retrieved set |
| Insufficient evidence fallback | VERIFIED | Returns controlled message when evidence is missing; prevents hallucinations |
| User-uploaded custom data | VERIFIED | Users can upload private documents; RAG chatbot searches both public corpus and user's private data |
| Knowledge Base endpoints | VERIFIED | `GET/POST /api/knowledge/documents`, status, delete, reindex |
| RAG Assistant chat endpoints | VERIFIED | `POST /api/assistant/chat`, conversations CRUD, product context injection |
| Frontend integration | VERIFIED | Minimal test UI with `/knowledge` and `/chat` pages wired to backend |

### Phase 5: IP-SAKTI Assistant (claim-to-evidence analysis, product analysis)
- **Status:** VERIFIED
- **Started:** 2026-09-23
- **Implemented / Verified:** 2026-09-23 00:10 IST
- **Evidence:**
  - 105/105 pytest tests pass (0 failures; 16 new Phase 5 tests)
  - `scripts/verify_phase5.py`: 37/37 checks pass against the real PostgreSQL database
  - `scripts/verify_migrations.py`: full downgrade/upgrade chain still verified transactionally at head `004`
  - Migration `004` applied: `CLAIM_ANALYSIS` added to the `analysistype` enum

#### Phase 5 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| Claim-to-evidence analysis | VERIFIED | `POST .../versions/{id}/claims/analyze`; per-claim assessment with rationale, risk level and review status |
| Comprehensive product analysis | VERIFIED | `POST .../versions/{id}/analyze`; classification + claim review + market considerations + expert-review recommendations |
| Preliminary product classification | VERIFIED | Validated against the platform's own `ProductCategory` enum; always flagged `preliminary` |
| Structured AI output | VERIFIED | LLM JSON -> Pydantic validation -> citation validation -> safety clamp; malformed output is a controlled failure |
| AI provenance firewall | VERIFIED | AI output is stamped `AI_ANALYSIS` and can never suggest `supported` / `expert_verified` (clamped to `needs_evidence`) |
| EXPERT_VERIFIED protection | VERIFIED | Expert-verified claims are returned locked and are never assessed or altered by the AI |
| Citation validation | VERIFIED | Reuses the Phase 4 validator; chunk ids the AI was not given are dropped with a warning |
| Advisory-only analysis | VERIFIED | Running an analysis never mutates claims, evidence or ingredients (asserted in tests and live) |
| Analysis persistence | VERIFIED | One `analyses` row per run, pinned to the reviewed version with `content_hash` in the audit trail |
| Controlled AI failure | VERIFIED | An unavailable/erroneous model returns 503 and records a `FAILED` analysis row |
| Analysis retrieval | VERIFIED | `GET .../analyses` (+ `analysis_type` filter) and `GET .../analyses/{id}` |
| Analysis scoping | VERIFIED | Cross-user reads return 404; an analysis is not reachable through another version |
| Honest phase boundaries | VERIFIED | Later-phase stages are declared in `deferred_components` instead of appearing to work |
| Assistant source provenance | VERIFIED | Chat response reports `product_id`, `product_version_id` and `provenance` (PUBLIC_SOURCE / USER_PROVIDED) |
| Frontend integration | VERIFIED | Analysis section on the version page: run buttons, recorded-run picker, claim assessment cards (suggested status/risk/review/provenance badges), citations with quoted passages, classification, market considerations, missing information, deferred components, warnings; chat now renders source provenance |

**Not in this phase (deliberately deferred):** public-disclosure review (Phase 8).
The Phase 6 stages (`POST .../analyze` used to name them in `deferred_components`)
are now implemented and embedded in the comprehensive result.

### Phase 6: IP Route Map, Patent Screening, Biodiversity/ABS/TK Screening
- **Status:** VERIFIED
- **Started:** 2026-09-25
- **Implemented / Verified:** 2026-09-25 23:47 IST
- **Evidence:**
  - 130/130 pytest tests pass (0 failures; 25 new Phase 6 tests)
  - `scripts/verify_phase6.py`: 57/57 checks pass against the real PostgreSQL database
  - Migration `005` applied: `patent_records`, `patent_features` created (head is now `005`)
  - `scripts/verify_migrations.py` 5/5; `scripts/verify_frontend_flow.py` 90/90 live

#### Phase 6 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| IP route map | VERIFIED | `GET .../ip-routes`; nine routes (patent, trademark, copyright, design, GI, trade secret, plant variety, traditional knowledge, biodiversity/ABS), each deterministically derived with a careful label and the signals that triggered it |
| No AI-asserted applicability | VERIFIED | The route map is a rule engine over recorded data; a route is never presented as legally applicable |
| Patent screening (demo mode) | VERIFIED | `POST .../patents/search`; extracts technical features and screens against a frozen, labelled demonstration corpus |
| Patent feature comparison | VERIFIED | `POST .../patents/compare`; field-by-field matching / different / unknown verdicts with a similarity indicator and uncertainty note |
| Patent record retrieval | VERIFIED | `GET .../patents` and `GET /api/patents/{patent_id}`, both version- and owner-scoped |
| Demo data is never passed off as real | VERIFIED | `retrieval_mode=DEMO_CORPUS`, `search_is_live=false`, `is_demo=true`, `DEMO-...` ids, no real patent numbers, explicit demo-corpus note |
| No patentability conclusions | VERIFIED | Careful labels only (Potentially Relevant / Possible Technical Overlap / Further Review Recommended); never patentable, novel, valid or infringing |
| Biodiversity / ABS screening | VERIFIED | `POST .../biodiversity/screen`; status, considerations, missing information, review questions, sources |
| Traditional-knowledge screening | VERIFIED | `POST .../traditional-knowledge/screen`; public sources only |
| Restricted sources excluded | VERIFIED | `GET /api/traditional-knowledge/sources` distinguishes public / permitted / restricted; the TKDL is listed as restricted and is never accessed, searched or reproduced |
| Screening statuses | VERIFIED | Only the four allowed values: NO_IMMEDIATE_CONSIDERATION_IDENTIFIED, ADDITIONAL_INFORMATION_NEEDED, POTENTIALLY_RELEVANT, REVIEW_RECOMMENDED |
| Opt-in corpus sources | VERIFIED | `?include_sources=true` attaches only genuinely retrieved passages; a retrieval failure degrades with a warning rather than failing the screening |
| Version-pinned persistence | VERIFIED | Each screening is an `analyses` row pinned to the reviewed version; candidate records cascade with it |
| Advisory-only | VERIFIED | Screenings never mutate claims, evidence, ingredients or the formulation |
| Frontend integration | VERIFIED | "IP screening (Phase 6)" section on the version page: route map, patent screening with a feature table, re-run comparison, biodiversity/ABS and TK screens, TK source registry |

### Phase 7: Formulation Change Impact Simulator
- **Status:** VERIFIED
- **Started:** 2026-09-26
- **Implemented / Verified:** 2026-09-26 00:56 IST
- **Evidence:**
  - 150/150 pytest tests pass (0 failures; 20 new Phase 7 tests)
  - `scripts/verify_phase7.py`: 48/48 checks pass against the real PostgreSQL database
  - Migration `006` applied: `change_impacts` created (head is now `006`)
  - `scripts/verify_migrations.py` 5/5; `scripts/verify_frontend_flow.py` 108/108 live

#### Phase 7 Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| Version comparison endpoint | VERIFIED | `POST /api/products/{id}/change-impact` with `{old_version_id, new_version_id}` |
| Ingredients / botanical species / plant parts | VERIFIED | Added, removed and reidentified ingredients; species and plant-part changes |
| Quantities | VERIFIED | Amount and unit compared per ingredient |
| Resource origin and cultivated/wild status | VERIFIED | Origin and sourcing changes; cultivated -> wild is ranked significant |
| Formulation and extraction process | VERIFIED | Method, solvent, temperature, pressure, duration, concentration, process text |
| Claims | VERIFIED | Added/removed claims; a new therapeutic claim is significant; claim-type and evidence-status changes |
| Evidence | VERIFIED | Added/removed documents and verification-status changes |
| Target markets | VERIFIED | Added/removed markets; regulatory-status changes; a new market is significant |
| Patent-related signals | VERIFIED | Re-runs the Phase 6 engine on both versions and diffs the technical features and overlap indicator |
| Biodiversity / TK considerations | VERIFIED | Compares the Phase 6 biodiversity/ABS and TK screening status of both versions |
| Product classification | VERIFIED | Compares recorded preliminary classifications; declared as not comparable when absent |
| Public disclosure | VERIFIED (declared unavailable) | Not tracked until Phase 8; listed in `not_compared` with the reason, never silently omitted |
| Review questions | VERIFIED | Per changed category, with the disclosure-timing and expert-review questions always asked |
| Significance ranking | VERIFIED | informational / review recommended / significant; the report is ordered by significance |
| Expert-review recommendation | VERIFIED | Derived from the significant changes, with the reasons recorded |
| Version-pinned persistence | VERIFIED | One immutable `change_impacts` row per run, pinned to both versions |
| Advisory-only | VERIFIED | A comparison never edits either version |
| Frontend integration | VERIFIED | "Formulation change impact (Phase 7)" card on the versions page: from/to pickers, recorded-run picker, differences grouped by category, review questions, not-compared list |

### Phase 8: Reports, Disclosure, Verification
- **Status:** VERIFIED (8a + 8b, 2026-09-26)

#### Phase 8b: ReportLab PDFs (VERIFIED 2026-09-26)
- **Evidence:**
  - 9/9 new pytest tests pass (`tests/test_phase8_reports.py`)
  - Migration `008` applied to live DB (head `008`); `verify_migrations.py` 5/5
  - `tests/test_analysis.py` updated: `deferred_components` is now empty

| Feature | Status | Notes |
|---------|--------|-------|
| Reports table | VERIFIED | `reports` + `reporttype` enum, migration 008 |
| IP Opportunity & Evidence Brief | VERIFIED | `POST .../reports/ip-brief` |
| Invention Disclosure Record | VERIFIED | `POST .../reports/disclosure` |
| Expert Handoff Package | VERIFIED | `POST .../reports/expert-handoff` |
| PDF download + listing | VERIFIED | `GET /api/reports/{id}`, `GET .../reports` (owner-only) |
| Public verification + QR | VERIFIED | `GET /api/reports/{id}/verify` (no auth, `hash_match`); QR printed in every PDF |
| SHA-256 integrity | VERIFIED | Downloaded bytes match stored `content_hash` (asserted in tests) |
| Disclaimers in every PDF | VERIFIED | General + patent + analysis + invention-disclosure |

#### Phase 8a: Disclosure tracking + disclosure review (VERIFIED 2026-09-26)
- **Evidence:**
  - 17/17 new pytest tests pass (`tests/test_phase8_disclosures.py`)
  - `scripts/verify_phase8a.py`: 13/13 checks pass against live PostgreSQL
  - Migration `007` applied to live DB (head is now `007`); `verify_migrations.py` 5/5
  - Phase 7 suite updated: disclosure history now comparable (2 tests replaced)

| Feature | Status | Notes |
|---------|--------|-------|
| Disclosures table | VERIFIED | `disclosures` + `disclosuretype` enum, migration 007 |
| Version-scoped endpoints | VERIFIED | `GET/POST .../versions/{id}/disclosures` |
| Disclosure review | VERIFIED | `POST .../disclosure-review`; `PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED` / `NO_EVENTS_RECORDED` |
| Global endpoints | VERIFIED | `POST /api/disclosures`, `GET /api/disclosures/{id}` (owner-only) |
| Public verification | VERIFIED | `GET /api/disclosures/{id}/verify`, no auth, `hash_match` flag |
| SHA-256 integrity | VERIFIED | `record_hash` over canonical payload; recomputed on verify |
| QR verification id | VERIFIED | Unique `verification_id` per record (QR rendering in 8b) |
| Mandatory disclaimer | VERIFIED | Invention-disclosure disclaimer on every record + verify payload |
| Cautious wording | VERIFIED | Considerations/questions only; banned conclusive phrases asserted absent |
| Change-impact integration | VERIFIED | `public_disclosure` compared from recorded events; new event is significant |
| Advisory-only | VERIFIED | Recording/review never edits version content (asserted in tests) |

#### Phase 8b: ReportLab PDFs (NOT_STARTED, next)
- IP Opportunity & Evidence Brief, Invention Disclosure Record, Expert Handoff Package
- `POST .../reports/ip-brief`, `POST .../reports/disclosure`, `POST .../reports/expert-handoff`
- QR code rendering to the verify endpoint

### Phase 9: Expert Review Workflow
- **Status:** NOT_STARTED

### Phase 9: Expert Review Workflow
- **Status:** VERIFIED (2026-09-26)
- **Evidence:**
  - 9/9 pytest tests pass (`tests/test_phase9_reviews.py`)
  - `scripts/verify_phase9.py`: 9/9 live PostgreSQL checks pass
  - Migration `009` applied (head `009`); `verify_migrations.py` 5/5

| Feature | Status | Notes |
|---------|--------|-------|
| Review tables | VERIFIED | `expert_reviews` + `review_comments`, migration 009 |
| State machine | VERIFIED | DRAFT→AI_SCREENED→REVIEW_REQUIRED→EXPERT_REVIEW→CORRECTION_REQUESTED→RESUBMITTED→REVIEWED→ARCHIVED |
| Comments | VERIFIED | `POST .../comment`; expert comment opens EXPERT_REVIEW; closed reviews refuse |
| Correction round-trip | VERIFIED | request-correction → resubmit → complete |
| EXPERT_VERIFIED promotion | VERIFIED | `complete` with verify ids promotes claims/evidence; only path to that provenance |
| Reviewer-only guards | VERIFIED | complete/request-correction/archive are 403 for non-experts |
| Reviewer access | VERIFIED | EXPERT/ADMIN pool may open any review; others owner-only (404) |

### Phase 10: Dashboard, Audit, Admin
- **Status:** VERIFIED (2026-09-26)
- **Evidence:** 9/9 pytest tests pass (`tests/test_phase10_admin.py`); no migration needed

| Feature | Status | Notes |
|---------|--------|-------|
| Dashboard | VERIFIED | `GET /api/dashboard` (counts, screenings, recent disclosures/activity; owner-scoped) |
| Audit | VERIFIED | `GET /api/audit`, `GET /api/audit/{id}` (own entries; ADMIN may read any) |
| Admin users/audit | VERIFIED | `GET /api/admin/users`, `GET /api/admin/audit` (ADMIN-only) |
| Admin sources | VERIFIED | CRUD on `source_documents` metadata (ADMIN-only) |
| RAG status | VERIFIED | `GET /api/admin/rag/status` (corpus counts, models, demo mode) |
| RBAC | VERIFIED | `require_admin` guard; every admin route 403 for non-admins (tested) |

### Phase 11: BHASHINI Integration
- **Status:** VERIFIED (2026-09-26)
- **Evidence:** 8/8 pytest tests pass (`tests/test_phase11_bhashini.py`); RAG suite 22/22 unaffected

| Feature | Status | Notes |
|---------|--------|-------|
| Language detection | VERIFIED | `POST /api/bhashini/detect` (script heuristics, hi/bn/en + confidence) |
| Translation endpoint | VERIFIED | `POST /api/bhashini/translate`; honest fallback when unconfigured |
| Languages + glossary | VERIFIED | `GET /api/bhashini/languages` (18 controlled terms) |
| Identifier preservation | VERIFIED | URLs/patent numbers/DOIs/dates masked and restored verbatim |
| Assistant integration | VERIFIED | Canonical-query in, translated answer out, warnings on fallback |
| Isolated module | VERIFIED | `app/bhashini/` (client, translator, detector, glossary, exceptions) |

### Phase 12: Simple Frontend Integration
- **Status:** VERIFIED (2026-09-26)
- **Evidence:**
  - `vite build` clean (343 kB bundle, 0 errors)
  - `scripts/verify_frontend_flow.py`: 127/127 live checks (108 pre-existing + 19 new)

| Feature | Status | Notes |
|---------|--------|-------|
| Disclosures UI | VERIFIED | `DisclosuresSection` on version page (record + review) |
| Reports UI | VERIFIED | `ReportsSection` (3 generators + PDF download) |
| Reviews UI | VERIFIED | `/reviews` page (create, transitions, comments) |
| Dashboard UI | REMOVED 2026-10-04 | `/dashboard` page deleted on user request; backend `GET /api/dashboard` kept for Home stat tiles |
| BHASHINI UI | VERIFIED | Chat input/output language selects (en/hi/bn) |
| Flow coverage | VERIFIED | 19 new flow checks mirror exactly what the UI calls |

### Phase 13: Integration Testing, Security Review, Documentation
- **Status:** VERIFIED (2026-09-26)
- **Evidence:**
  - Full pytest suite: 203/203 pass (incl. 5 auth tests fixed by the 401 correction)
  - `scripts/verify_demo_flow.py`: 26/26 live (full Ashwagandha acceptance flow)
  - `scripts/verify_frontend_flow.py`: 127/127 live
  - `scripts/verify_migrations.py`: 5/5 at head 009
  - Security pass: no hardcoded secrets, no raw SQL, upload validation, safe errors
  - README updated for phases 8-13; requirements + `.env.example` completed
  - Real bug fixed: keyword-only retrieval fallback when embeddings unavailable

## Current Blockers

None - all phases 0-13 implemented and verified.

## Known Bugs

None open. The 2026-09-24 authentication-form bug (`res.json is not a function`,
422 on register/login, blank pages on deep links) is fixed, and the 2026-09-25
`Products` delete bug (an undeclared `setError` threw a `ReferenceError`) is fixed
too - see `DEVELOPMENT_LOG.md`.

## Known Issues / Technical Debt

1. **First AI analysis run downloads the embedding model.** Retrieval uses `BAAI/bge-m3` via `sentence-transformers`, which is not bundled. On a cold machine the first analysis (or RAG query) blocks on a multi-gigabyte HuggingFace download. Cache it during setup by running `scripts/ingest_corpus.py` or any RAG query once. Analysis resolves the LLM provider *before* retrieval, so a missing `GROQ_API_KEY` fails fast rather than after the download starts.
2. **`evidence.document_hash` stays null** - the column exists but is only meaningful once evidence files are uploaded (Phase 8).
3. **Analyses are not cached or deduplicated** - each `POST .../analyze` call performs a fresh (paid) model run. A content-hash-based cache would avoid re-running an unchanged version.
4. **Analysis results are stored in an `analyses` row that is never edited** - sound for auditability, but a superseded analysis is only distinguished by `created_at`.
5. **The frontend is a test UI, not a product UI** - one file, inline styles, no state library. It is deliberately minimal for manual testing through Phase 5.
6. **Legacy files at BACKEND root removed 2026-10-03** - `main.py`, `models.py`, `auth/`, `databases/`, `hash/` (pre-Phase-1 dead code) were confirmed unimported by anything in `app/`, `tests/` or `scripts/` and deleted.
7. **Pydantic v2 deprecation warnings** - schemas still use class-based `Config`; migrate to `ConfigDict` when convenient.
8. **Restoring a session logs a 401 in the browser console** - on a first visit (no refresh cookie) `AuthProvider`'s `POST /api/auth/refresh` probe answers 401 by design. It is handled silently in the UI, but the browser's network log still shows it.
9. **The patent corpus is a demonstration corpus.** Phase 6 has no live patent source, so screening runs against `app/data/patent_demo_corpus.py` (`demo-patents-2026.09`). Every response says so. Replacing it with a real public-records source would flip `retrieval_mode` to `LIVE_SOURCE`; nothing else would change.
10. **Screening results are not cached** - each screening writes a new `analyses` row, as analyses do in Phase 5.
11. **`HF_TOKEN` must be declared in `Settings`.** Pydantic-settings forbids undeclared keys, so any new key added to `.env` must be added to `app/config.py` and `.env.example` or the app will not start.
12. **Change-impact classification comparison needs a recorded analysis.** The simulator compares the latest recorded preliminary classification of each version; when neither has one it reports classification as not comparable rather than guessing. A deterministic classification signal would remove that dependency.
13. **Public disclosure is not comparable yet** - the disclosures table does not exist until Phase 8, so change-impact runs list it in `not_compared`.
14. **Change-impact runs are not cached** - each run writes a new `change_impacts` row, like analyses and screenings.

## Test Status

- **Full pytest suite:** 478 collected - **477 passing, 1 pre-existing failure** (in-memory SQLite, verified 2026-10-03, identical before and after the workspace cleanup + folder flatten). The failure is `test_acceptance_spec.py::TestBug4Classification::test_unresolved_with_the_five_information_requirements` - the test pins the three BUG-4 pathways from the 2026-09-27 design while `app/analysis/schemas.py::UNRESOLVED_PATHWAYS` now lists six renamed pathways. Code/test drift, needs a product decision - see `DEVELOPMENT_LOG.md` 2026-10-03 entry.
- **Live HTTP frontend-flow test:** `verify_frontend_flow.py` 139/139 against a running server
- **Overall Product View live checks:** `overview_live.py` 84/84
- **Demo workflow:** `verify_demo_flow.py` 26/26
- **Migration chain:** `verify_migrations.py` 5/5
- **Frontend:** ESLint 12 = baseline; `npx vite build` OK (462.58 kB bundle)

## Migration Status

- **Alembic:** configured; single linear chain 001 -> 002 -> ... -> 011
- **Head:** `011` (applied on live PostgreSQL Supabase database)

## RAG Corpus Status

- **Status:** CONFIGURED & READY
- **Corpus files on disk:** 131 `.md` sources (verified 2026-10-03; +12 Indian statute/regulation files and +9 international IP/regime/case-law files added 2026-09-28, incl. the first Germany/EU market-access source) - **not yet re-ingested**
- **Embedding Model:** BAAI/bge-m3 (1024 dimensions)
- **LLM:** Groq (llama-3.3-70b-versatile)
- **Retrieval:** Hybrid pgvector cosine + PostgreSQL FTS + RRF + Cross-Encoder Rerank

## External Integrations

- **Database:** PostgreSQL (Supabase) with pgvector extension enabled
- **LLM Provider:** Groq (`llama-3.3-70b-versatile`)
- **Embedding Provider:** `BAAI/bge-m3` via sentence-transformers
- **BHASHINI:** NOT_CONFIGURED

---

## Last Verified Task

**Task:** Overall Product View - Live Demo replacement (spec items 16-19),
plus the 2026-09-28 corpus additions (12 Indian statute files, 9 international
IP/regime/case-law files - disk only, not ingested)
**Date:** 2026-09-28
**Status:** VERIFIED - 386/386 tests, ESLint 12 = baseline, flow 139/139,
`overview_live.py` 84/84, `npx vite build` OK

## Next Task

**Task:** None remaining for the Overall Product View batch (VERIFIED
2026-09-28). Open items: persist the panel metadata on `chat_messages` so
history reloads show it (needs migration 012), re-ingest the corpus (21
study files added on disk 2026-09-28, incl. the first Germany/EU source -
DB still has none), Bhashini key, visual browser check of `/overview`.
Handover: `alembic upgrade head` (currently at `011`), `pytest tests/ -q`
(386), `verify_frontend_flow.py`, `verify_demo_flow.py`. Backend:
http://localhost:8000/api/docs.

---

## Environment Configuration

### Required Environment Variables
Configured in `.env` (real values) and `.env.example` (template):

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `CORS_ORIGINS`
- `DEMO_MODE`

### Running the tests and the servers

```bash
# With the backend running, this drives the same calls the UI makes:
cd IP-SHAKTI/BACKEND
.venv/Scripts/python.exe scripts/verify_frontend_flow.py

cd IP-SHAKTI/BACKEND
.venv/Scripts/python.exe -m pytest tests/ -q     # 150 tests
.venv/Scripts/python.exe scripts/verify_phase2.py
.venv/Scripts/python.exe scripts/verify_phase3.py
.venv/Scripts/python.exe scripts/verify_phase4.py
.venv/Scripts/python.exe scripts/verify_phase5.py
.venv/Scripts/python.exe scripts/verify_phase6.py
.venv/Scripts/python.exe scripts/verify_phase7.py
.venv/Scripts/python.exe scripts/verify_migrations.py
.venv/Scripts/python.exe scripts/verify_frontend_flow.py
.venv/Scripts/python.exe -m uvicorn app.main:app --reload   # http://localhost:8000

# In another terminal:
cd IP-SHAKTI/FRONTEND
node_modules/.bin/vite --host 0.0.0.0 --port 5173   # http://localhost:5173
```
