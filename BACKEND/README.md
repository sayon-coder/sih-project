# IP-SAKTI Sahayak Backend

> **Project overview, prerequisites and step-by-step setup: [../README.md](../README.md)**
> This document is the detailed backend/API reference.

A multilingual RAG-based AI assistant for intellectual property and regulatory guidance related to Ayurveda.

## Overview

IP-SAKTI Sahayak is a source-backed decision-support platform for Ayurveda-related IP, regulatory, traditional-knowledge, biodiversity/ABS, and product-development workflows.

## Features

- User authentication and authorization with JWT tokens
- Role-based access control (RBAC)
- Product Passport and versioning
- Ingredients, formulation, claims, evidence and target markets with provenance tracking
- RAG-based evidence retrieval with citation validation
- Claim-to-evidence analysis and comprehensive preliminary product analysis (Phase 5)
- IP route mapping and patent screening
- Biodiversity/ABS/TK screening
- Formulation change-impact comparison across versions (Phase 7)
- Public-disclosure tracking with SHA-256 integrity and public verification (Phase 8)
- PDF reports (IP brief, disclosure record, expert handoff) with QR verification (Phase 8)
- Expert review workflow with verification promotion (Phase 9)
- Dashboard, audit trail and admin endpoints with RBAC (Phase 10)
- Multilingual support via BHASHINI integration (Phase 11)
- Audit logging

## Tech Stack

- **Backend:** Python, FastAPI, Pydantic
- **Database:** PostgreSQL, SQLAlchemy, Alembic
- **Authentication:** JWT, bcrypt
- **RAG:** pgvector, sentence-transformers
- **Testing:** pytest, httpx

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or Docker for the bundled compose file)
- Virtual environment (recommended)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd IP-SHAKTI/BACKEND
```

2. Create virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Start a database (optional - skip if you already have PostgreSQL):
```bash
docker compose up -d
# then use DATABASE_URL=postgresql://ipsakti:ipsakti@localhost:5433/ipsakti
```

5. Configure environment:
```bash
cp .env.example .env
# Edit .env with your database credentials and API keys
```

6. Run database migrations:
```bash
alembic upgrade head
```

7. Seed default roles:
```bash
python scripts/seed_roles.py
```

> Roles must exist before anyone registers: registration assigns the default
> VIEWER role. Run `seed_roles.py` once per database.

8. Run the server:
```bash
uvicorn app.main:app --reload
```

### Migration safety

Alembic owns the schema; the application never creates tables at startup.

- Apply migrations: `alembic upgrade head`
- **Do not** run `alembic downgrade` against a database you care about - it drops
tables and commits the change.
- To verify the migration chain safely, use the script below, which runs the
  whole chain inside a transaction it rolls back:
```bash
python scripts/verify_migrations.py
```

### API Documentation

Once the server is running, access the API documentation at:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Testing

The pytest suite runs against an in-memory SQLite database, so it is fast and
never touches your real data:
```bash
pytest tests/ -v
```

Run with coverage:
```bash
pytest tests/ --cov=app --cov-report=html
```

### Running the test UI

The frontend is a deliberately minimal React + Vite app used for manual checking
of the API (products, versions, content, knowledge base, chat, analysis).

```bash
# Terminal 1 - backend
cd IP-SHAKTI/BACKEND
.venv/Scripts/python.exe -m uvicorn app.main:app --reload     # http://localhost:8000/api/docs

# Terminal 2 - test UI
cd IP-SHAKTI/FRONTEND
node_modules/.bin/vite --host 0.0.0.0 --port 5173              # http://localhost:5173
```

**Register / log in (JSON, not form data).** The auth endpoints take Pydantic
models, so they require a JSON body:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register -H 'content-type: application/json' \
  -d '{"username":"demo","email":"demo@example.com","password":"demopass123","confirm_password":"demopass123"}'

curl -X POST http://127.0.0.1:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"demo@example.com","password":"demopass123"}'
```

Registration returns the user only; the access token comes from login. Login also
sets an httpOnly `refresh_token` cookie, which the UI uses to restore the session
after a reload (`POST /api/auth/refresh`). Posting form-encoded data to these
routes returns 422.

Register, log in, open a product, open a version, add a claim, then use the
**Analysis** section: *Analyze claims* runs a claim-to-evidence review, and *Full
analysis* adds the preliminary classification. Recorded runs stay reviewable in
the picker, including runs that failed.

The **IP screening (Phase 6)** section below it offers the IP route map, patent
screening (with a feature table), a re-run comparison, and the biodiversity/ABS
and traditional-knowledge screens. These are deterministic and do not call the
model, so they answer immediately; the *include corpus sources* checkbox opts into
a corpus search for supporting passages, which does need the embedding model.

On the product's versions page, the **Formulation change impact (Phase 7)** card
compares any two versions (defaulting to the two newest) and groups the differences
by category, with added/removed/modified items, significance badges, the reasons
the comparison recommends expert review, follow-up review questions and a list of
what it could not compare (for example public disclosure, which arrives with
Phase 8). Like the screening, this is deterministic: quantities, cultivation
status, process parameters, claims, evidence, target markets, patent-related
signals and biodiversity/TK status are all read from recorded data rather than
inferred. Comparisons are advisory and never modify either version.

**First AI call is slow.** Retrieval embeds with `BAAI/bge-m3` through
`sentence-transformers`, which is not bundled. On a cold machine the first analysis
or RAG query blocks while the model is downloaded (several gigabytes). Warm the
cache once up front:

```bash
python scripts/ingest_corpus.py        # or simply run one query in the UI
```

Analysis resolves the LLM provider *before* retrieval, so a missing `GROQ_API_KEY`
is reported immediately instead of after that download.

**Provider fallback.** GROQ is the primary LLM for normal answers. When
`SARVAM_API_KEY` is also set, the factory wraps the primary in a
`FallbackLLMProvider`: if the GROQ call fails (network, outage, rate limit), the
same prompt is retried once against Sarvam AI (`SARVAM_MODEL`, default
`sarvam-105b-conversations`) before the assistant falls back to its honest error
message. Leave `SARVAM_API_KEY` empty to disable the fallback.

### Verifying against the real database

```bash
# End-to-end API smoke test on the configured PostgreSQL database.
# Creates temporary users/products and deletes everything it created afterwards.
python scripts/verify_phase2.py
python scripts/verify_phase3.py
python scripts/verify_phase4.py
python scripts/verify_phase5.py
python scripts/verify_phase6.py
python scripts/verify_phase7.py
python scripts/verify_phase8a.py
python scripts/verify_phase9.py

# Full Ashwagandha demo workflow (master prompt section 34), live database
python scripts/verify_demo_flow.py

# Migration chain check (downgrade base + upgrade head, then rolled back)
python scripts/verify_migrations.py
```

With the server running, `scripts/verify_frontend_flow.py` drives the same HTTP
calls the UI makes (127 checks), covering auth, products, versions, content,
knowledge, chat, analyses, Phase 6 IP/patent/biodiversity/TK endpoints, Phase 7
change impact, Phase 8 disclosures/reports, Phase 9 reviews, the Phase 10
dashboard/audit endpoints and Phase 11 BHASHINI.

## Project Structure

```
backend/
├── alembic/              # Database migrations
├── app/
│   ├── main.py          # FastAPI application
│   ├── config.py        # Configuration management
│   ├── database.py      # Database connection
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── routers/         # API route handlers
│   ├── services/        # Business logic
│   └── utils/           # Utility functions
├── tests/               # Test files
├── scripts/             # Utility scripts
├── requirements.txt     # Python dependencies
└── .env.example         # Environment variables template
```

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - Logout user

### Products

All product routes require a Bearer access token. A product is only visible to
the user who created it (ADMIN users can see all products).

- `POST   /api/products` - Create a product (also creates version 1)
- `GET    /api/products` - List products visible to the caller
- `GET    /api/products/{id}` - Get a product
- `PUT    /api/products/{id}` - Update product metadata
- `DELETE /api/products/{id}` - Soft delete (`is_active = false`)
- `GET    /api/products/{id}/passport` - Full Product Passport
- `PUT    /api/products/{id}/passport` - Update product metadata from the passport view

Enum fields (for example `category`) use lowercase API values:
`classical_traditional`, `proprietary_ayurvedic`, `possible_medicinal`,
`ayurveda_aahara`, `possible_cosmetic`, `research_product`, `industrial_product`.

### Product versions

- `GET  /api/products/{id}/versions` - List versions (newest first)
- `POST /api/products/{id}/versions` - Create a version
- `GET  /api/products/{id}/versions/{version_id}` - Full version detail
- `PUT  /api/products/{id}/versions/{version_id}` - Update the change reason
- `POST /api/products/{id}/versions/{version_id}/clone` - Copy a version into a new one

Creating a version copies the current version's content by default, so a change
is always a delta from the previous state. Pass `start_empty` to begin blank.

Every version stores two integrity fields:

- `snapshot_data` - canonical JSON of the version content (ingredients,
  formulation, claims, evidence, target markets)
- `content_hash` - SHA-256 of that content only, so two versions with identical
  content share a hash and a real content change always changes it

Versions are independent: editing version 2 never modifies version 1.

### Version content (ingredients, formulation, claims, evidence, markets)

All nested routes live under
`/api/products/{id}/versions/{version_id}` and require an owned product. A child
id from another version or another user's product returns 404.

- `GET/POST/PUT/DELETE /ingredients[/{ingredient_id}]`
- `GET/PUT /formulation` - one per version; PUT merges the fields you send
- `GET/POST/PUT/DELETE /claims[/{claim_id}]`
- `GET/POST /evidence` and `GET/PUT /evidence/{evidence_id}`
- `GET/POST/PUT/DELETE /target-markets[/{market_id}]`

**Every edit refreshes `snapshot_data` and `content_hash`, and writes an audit
entry.** Because the hash covers content only, an inherited or cloned version
keeps the same hash until its content actually differs.

#### Provenance and the claim-to-evidence firewall

- Provenance is assigned by the server, never accepted from a client. New rows
  are stored as `USER_PROVIDED`. Values are `USER_PROVIDED`, `PUBLIC_SOURCE`,
  `AI_ANALYSIS`, `EXPERT_VERIFIED`.
- A row whose provenance is `EXPERT_VERIFIED` cannot be edited or deleted
  through these endpoints (`409`) - it belongs to the expert workflow.
- A claim's `evidence_status` may be set to `user_provided` or `needs_evidence`
  only. Declaring `supported` / `partially_supported` / `expert_verified` returns
  `422`; those statuses are conclusions reached by evidence or expert review.
- Evidence is created as `pending` and a user may only reset it to `pending`, not
  promote it to `verified`. `document_hash` stays null until a file is ingested
  (Phase 8).

### Analysis (Phase 5)

All nested under `/api/products/{id}/versions/{version_id}` and requiring an
owned product version. An analysis is **advisory**: it writes one new `analyses`
row pinned to the version it reviewed and never edits the content itself.

- `POST /claims/analyze` - claim-to-evidence review. Returns one assessment per
  claim: current and suggested evidence status, risk level, rationale, missing
  evidence, and citations resolved from the corpus.
- `POST /analyze` - comprehensive preliminary analysis: product classification,
  the claim review, target-market considerations and expert-review
  recommendations. Stages owned by later phases are listed in
  `deferred_components` rather than silently omitted.
- `GET /analyses` - list analyses for the version (optional
  `?analysis_type=claim_analysis|comprehensive|...`)
- `GET /analyses/{analysis_id}` - one recorded analysis

An analysis run begins with the model, not with retrieval: if the AI provider is
unavailable the request fails fast with `503` and a `FAILED` row is recorded, so
there is no wasted embedding work and no silent success.

#### What the AI is not allowed to do

- It cannot promote a claim. A suggested status is clamped to `user_provided`,
  `needs_evidence` or `partially_supported`; asking for `supported` or
  `expert_verified` is reduced to `needs_evidence`. Only human evidence review
  and the expert workflow (Phase 9) can reach those statuses.
- It cannot touch an `EXPERT_VERIFIED` claim. Such claims are returned with
  `expert_verified_locked: true` and their existing status unchanged.
- It cannot cite a passage it was not given. Citations are validated against the
  passages retrieved for that claim, and all metadata is read from the database.
- It cannot produce a result without citations or evidence: uncited claims stay
  as declared and are reported as needing evidence.
- It never mutates your data. Running an analysis five times leaves five rows and
  the same claims.

AI output is stamped `AI_ANALYSIS`; the response always carries the preliminary
screening disclaimers.

### IP route map, patent screening, biodiversity/ABS and traditional knowledge (Phase 6)

All nested routes require an owned product version. Nothing here is a legal,
patent or regulatory determination, and nothing here mutates your content.

- `GET  /ip-routes` - preliminary IP route map. Nine routes (patent, trademark,
  copyright, design, GI, trade secret, plant variety, traditional knowledge,
  biodiversity/ABS), each derived deterministically from the recorded data with a
  careful label (`Potentially Relevant`, `Further Review Recommended`,
  `Not Indicated`, `Insufficient Information`), the signals that triggered it and
  review questions. A route is never presented as legally applicable.
- `POST /patents/search` - extract the version's technical features and screen
  them against a frozen demonstration corpus. Stores the candidate records for
  the version and records the run.
- `GET  /patents` - the candidate records already identified for the version
- `POST /patents/compare` - re-compare the version's current features against the
  identified records (optional body `{"patent_record_ids": [...]}`); creates no
  new records
- `GET  /api/patents/{patent_id}` - one identified record
- `POST /biodiversity/screen` - biodiversity/ABS screening. Status, potential
  considerations, missing information, review questions and sources.
- `POST /traditional-knowledge/screen` - traditional-knowledge screening
- `GET  /api/traditional-knowledge/sources` - the source registry, distinguishing
  `public`, `permitted` and `restricted` / unavailable sources

#### Patent screening is a demonstration corpus

There is no live patent source. Every screening response therefore reports
`retrieval_mode: DEMO_CORPUS` and `search_is_live: false`, every record is
`is_demo: true`, carries a `DEMO-...` id and **no real patent number**, and the
response carries an explicit note. Screening runs against
`app/data/patent_demo_corpus.py` (`demo-patents-2026.09`); replacing it with a
real public-records source would set `retrieval_mode` to `LIVE_SOURCE` and change
nothing else.

The comparison returns matching / different / unknown features per record plus a
similarity indicator (a colour band over the fraction of the record's features
that the version matches) and an uncertainty note. It never asserts
patentability, novelty, validity, infringement or priority, and only uses the
careful labels `Potentially Relevant`, `Possible Technical Overlap` and
`Further Review Recommended`.

#### Screening statuses and restricted sources

Both screenings return one of four statuses: `NO_IMMEDIATE_CONSIDERATION_IDENTIFIED`,
`ADDITIONAL_INFORMATION_NEEDED`, `POTENTIALLY_RELEVANT` or `REVIEW_RECOMMENDED`.
Neither ever declares that government approval is required (or not required) or
that legal compliance has been achieved.

Restricted sources such as the **TKDL** are listed as `restricted` and are never
accessed, searched or reproduced. Only a passage genuinely retrieved from the
accessible corpus becomes a source; add `?include_sources=true` to a screening to
request that corpus search. If retrieval is unavailable, the screening still
completes and says so in its warnings.

### Formulation change impact (Phase 7)

Compares two versions of a product and reports what actually changed. Nothing here
mutates either version, and no conclusion is drawn beyond what the recorded data
supports.

- `POST /api/products/{product_id}/change-impact` - compare two versions. Body:
  `{"old_version_id": 1, "new_version_id": 2}`. Both must belong to the product
  and must differ; the earlier version is the baseline. Stores the run and returns
  the full report.
- `GET  /api/products/{product_id}/change-impact` - list recorded comparisons,
  newest first
- `GET  /api/products/{product_id}/change-impact/{impact_id}` - one recorded run

A report contains differences grouped by category (ingredients, botanical species,
plant parts, quantities, resource origin, cultivation status, formulation/process,
claims, evidence, target markets, patent-related signals, biodiversity/TK,
classification, public-disclosure history), each item labelled `added` / `removed`
/ `modified` with an `informational` / `review_recommended` / `significant`
significance, the reasons expert review is recommended, follow-up review questions,
cautious notes, and a `not_compared` list naming what could not be assessed
(for example classification when neither version has a recorded analysis).

A change from cultivated to wild-collected material is treated as significant, as
are added or removed claims and evidence and changed process parameters, because
those are the changes that most often alter what a regulator or examiner wants to
see.

### Knowledge base

- `GET/POST /api/knowledge/documents` - list and upload corpus documents (PDF, DOCX, TXT)
- `GET/DELETE /api/knowledge/documents/{id}` - read and delete (owner or ADMIN)
- `POST /api/knowledge/documents/{id}/reindex` - re-run ingestion for one document
- `POST /api/knowledge/index` - re-run ingestion for the caller's pending/failed
  documents (ADMIN: the whole corpus). Records without a file on disk are
  reported as `skipped`, never silently ignored; the response counts
  `attempted` / `indexed` / `failed` / `skipped`
- `GET /api/knowledge/status` - corpus-wide statistics

### Sources

- `GET /api/sources` - corpus sources visible to the caller (public documents
  plus the caller's own; ADMIN sees everything). File paths and document
  hashes are never exposed
- `GET /api/sources/search?q=` - search visible sources by title, author,
  source type or jurisdiction
- `GET /api/sources/{id}` - one source; documents the caller may not see
  return `404`

### Users

- `GET /api/users/me` - the caller's profile (username, email, roles)
- `PUT /api/users/me` - update own username and/or email. Roles, password and
  account state are deliberately not writable; changes are audit-logged as
  `update_profile` (`409` if the email belongs to someone else)
- `GET /api/users/me/history?limit=` - the caller's own audit history
  (never other users' entries)

### Assistant

- `POST /api/assistant/chat` - RAG chat with citation-backed answers. Accepts
  `input_language` / `output_language` (`en`, `hi`, `bn`); retrieval and reasoning
  always run on the canonical English form via BHASHINI, with an open fallback
  warning when translation is unavailable. LLM calls go GROQ first and fall
  back to Sarvam AI when `SARVAM_API_KEY` is set (see "Provider fallback"
  above). Optional request fields: `provider` (`groq` | `sarvam`) selects the
  answering LLM explicitly (default `groq`; selecting `sarvam` answers strictly
  via Sarvam), and `attachment_ids` injects uploaded PDFs into the answer
  context (the response echoes `provider` and adds `USER_PROVIDED` to
  `provenance` when a document was used).
- `POST /api/assistant/attachments` - upload a PDF to attach to a chat
  (multipart: `file`, optional `session_id`). Extracts the text with the same
  PyMuPDF parser as the knowledge base, stores it for the caller (300,000
  character cap with an honest `truncated` flag), rejects non-PDF, corrupt or
  text-less scan files with a clear reason, and binds it to the conversation so
  follow-up messages reuse it. The attachment is **indexed into retrievable
  chunks** (`document_id` FK, page numbers, SHA-256 `content_hash` dedupe,
  `USER_PROVIDED` provenance), so per-section retrieval can cite it with page
  numbers; the raw text (100,000 characters) is also injected into the prompt,
  with a truncation warning when the cap is hit. An extraction failure returns
  a document-processing error, never a legal abstention.
- `GET/DELETE /api/assistant/conversations[/{id}]` - conversation sessions

The chat response reports `product_id`, `product_version_id` and the
`provenance` of the sources used (`VERIFIED_PUBLIC_SOURCE` for the shared
corpus, `USER_PROVIDED` for your own uploaded documents).

**Selective answering (master-prompt items 16-17):** a multi-part question is
decomposed into sub-questions (>= 2 question marks or >= 3 task verbs), each is
retrieved separately (uploaded attachment chunks are always re-merged into
their section's context), and only the sub-parts without evidence abstain -
never the whole question. The response then carries:

- `overall_status` - `SUPPORTED` | `PARTIALLY_SUPPORTED` |
  `INSUFFICIENT_EVIDENCE` | `PROCESSING_ERROR` | `EXPERT_REVIEW_REQUIRED`
- `sections[]` - per topic: `status`, `answer`, `provenance`, `citations`
  (with page numbers for uploaded PDFs) and a `next_action` on every
  abstention, plus per-section evidence metrics
- `disclaimer` - the fixed platform disclaimer; `warnings` - extraction
  failures, dropped invalid citations, translation fallbacks
- `debug` - retrieval/answering diagnostics, present only when `DEBUG=true`

User-provided evidence is classified `USER_PROVIDED_ONLY` with
`independent_verification: NOT_FOUND` and `review_required: true`; claims the
sources cannot support are never asserted as legal conclusions (jurisdiction
and banned-conclusion gates return `EXPERT_REVIEW_REQUIRED` instead).
Document extraction failures surface as `PROCESSING_ERROR`, not as a legal
abstention.

### Disclosures and reports (Phase 8)

Disclosure events are immutable rows pinned to one product version, each with a
SHA-256 `record_hash`, a unique `verification_id` and the mandatory
invention-disclosure disclaimer (not a patent application, no priority).

- `GET/POST /api/products/{id}/versions/{vid}/disclosures` - record and list events
- `POST /api/products/{id}/versions/{vid}/disclosure-review` - advisory review
  (`PUBLIC_DISCLOSURE_REVIEW_RECOMMENDED` or `NO_EVENTS_RECORDED`)
- `POST /api/disclosures`, `GET /api/disclosures/{id}` - global create/read
- `GET /api/disclosures/{id}/verify` - public verification (no auth), `hash_match`
- `POST /api/products/{id}/versions/{vid}/reports/ip-brief|disclosure|expert-handoff`
- `GET /api/products/{id}/versions/{vid}/reports` - list generated reports
- `GET /api/reports/{id}` - download the PDF (owner only)
- `GET /api/reports/{id}/verify` - public verification (no auth); every PDF prints
  a QR code to this URL plus all platform disclaimers

### Expert review (Phase 9)

`DRAFT -> AI_SCREENED -> REVIEW_REQUIRED -> EXPERT_REVIEW -> CORRECTION_REQUESTED
-> RESUBMITTED -> REVIEWED -> ARCHIVED`.

- `POST /api/reviews` - open a DRAFT review for a version
- `GET /api/reviews[?status=]`, `GET /api/reviews/{id}` - list and read
- `POST /api/reviews/{id}/submit|request-review|comment|request-correction|resubmit|complete|archive`
- Reviewer-only actions (`request-correction`, `complete`, `archive`) require the
  EXPERT or ADMIN role. Completing with `verify_claim_ids` / `verify_evidence_ids`
  promotes those rows to `EXPERT_VERIFIED` - the only path to that provenance.

### Dashboard, audit and admin (Phase 10)

- `GET /api/dashboard` - product/version counts, pending reviews, analyses,
  claims needing evidence, screening coverage, recent disclosures and activity
- `GET /api/audit`, `GET /api/audit/{id}` - the caller's own audit trail
- `GET /api/admin/users`, `GET /api/admin/audit`, `GET /api/admin/rag/status` -
  platform overview (ADMIN only)
- `GET/POST/PUT/DELETE /api/admin/sources[/{id}]` - corpus source records (ADMIN only)

### BHASHINI language layer (Phase 11)

- `GET /api/bhashini/languages` - supported languages (`en`, `hi`, `bn`) + glossary
- `POST /api/bhashini/detect` - script-based language detection with confidence
- `POST /api/bhashini/translate` - translation; when BHASHINI is unconfigured the
  original text is returned with `translated: false` and a warning - never an
  invented translation. Patent numbers, URLs, DOIs and dates are never altered.

## Development Phases

All phases are implemented and verified (203/203 pytest tests pass, plus live PostgreSQL verification scripts per phase):

- Phase 0: Repository Inspection
- Phase 1: Backend Foundation, Authentication, RBAC
- Phase 2: Product Passport and Versioning
- Phase 3: Ingredients, Formulation, Claims, Evidence, Provenance
- Phase 4: RAG System
- Phase 5: IP-SAKTI Assistant (claim-to-evidence analysis, product analysis)
- Phase 6: IP Route Map, Patent Screening, Biodiversity/ABS and TK Screening
- Phase 7: Formulation Change Impact Simulator (version comparison, ranked differences, review questions)
- Phase 8: Reports and Disclosure (disclosure tracking, SHA-256/QR verification, PDF briefs)
- Phase 9: Expert Review (state machine, comments, correction round-trip, verification promotion)
- Phase 10: Dashboard, Audit and Admin (RBAC-protected)
- Phase 11: BHASHINI Integration (detection, translation with honest fallback, glossary)
- Phase 12: Frontend Integration - test UI covering all phases
- Phase 13: Integration Testing (demo workflow, security review, documentation)

## Security

- Never commit secrets to the repository
- Use environment variables for sensitive configuration
- JWT tokens with expiration
- Password hashing with bcrypt
- RBAC for authorization
- Input validation with Pydantic
- SQL injection prevention via SQLAlchemy ORM

## Disclaimer

This platform provides preliminary, source-backed information and decision support. It does not constitute legal, patent, regulatory, medical, or government advice or approval.

## License

[Specify License]

## Contributing

[Contributing Guidelines]
