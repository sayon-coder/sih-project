# IP-SAKTI Sahayak

**A multilingual, source-backed AI decision-support platform for Ayurveda product development, intellectual property, regulatory and traditional-knowledge workflows.**

IP-SAKTI Sahayak helps founders, researchers and reviewers record a product's facts once (a *Product Passport*) and then get **evidence-backed, citation-validated answers** about patent routes, claim support, public disclosure, formulation change impact and expert review — without the platform ever inventing a source or pretending to be a lawyer.

> **Disclaimer:** this platform provides preliminary, source-backed information and decision support. It does **not** constitute legal, patent, regulatory, medical or government advice or approval.

---

## Table of contents

1. [What the platform does](#what-the-platform-does)
2. [How it works (architecture)](#how-it-works-architecture)
3. [Tech stack](#tech-stack)
4. [Repository layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [Configuration (.env)](#configuration-env)
7. [Getting started — step by step](#getting-started--step-by-step)
8. [Verifying the installation](#verifying-the-installation)
9. [Using the app (walkthrough)](#using-the-app-walkthrough)
10. [Testing and verification scripts](#testing-and-verification-scripts)
11. [API and frontend reference](#api-and-frontend-reference)
12. [Troubleshooting](#troubleshooting)
13. [Security model](#security-model)
14. [Project status and documentation](#project-status-and-documentation)

---

## What the platform does

| Area | What you can do |
|---|---|
| **Accounts & roles** | Register/login with JWT access + httpOnly refresh cookies, role-based access (default `VIEWER`, plus `EXPERT` / `ADMIN` for review and administration). |
| **Product Passport** | Create products with versions. Every version snapshots its content (`snapshot_data`) and a SHA-256 `content_hash`, so any change is a verifiable delta from the previous state. |
| **Content** | Ingredients, formulation, claims, evidence and target markets per version, with server-stamped provenance (`USER_PROVIDED` → `PUBLIC_SOURCE` / `AI_ANALYSIS` / `EXPERT_VERIFIED`). |
| **RAG assistant (chat)** | Ask multi-part questions; the question is decomposed and answered **per sub-topic** with validated citations (page numbers for uploaded PDFs). Unsupported sub-parts abstain individually — the whole question is never silently rejected or hallucinated. |
| **Knowledge base** | Upload your own PDF/TXT/DOCX documents; they are chunked, embedded and searched alongside the public corpus (110+ Ayurveda/IP/regulatory documents in `BACKEND/corpus/`). |
| **Claim-to-evidence analysis** | AI reviews every claim against retrieved evidence and can only *suggest* — it can never promote a claim to `supported`/`expert_verified` and never mutates your data. |
| **IP route map & screening** | Deterministic preliminary route map (patent, trademark, copyright, design, GI, trade secret, plant variety, TK, biodiversity/ABS), patent feature screening against a clearly-labelled demo corpus, biodiversity/ABS and traditional-knowledge screens. Restricted sources (e.g. TKDL) are listed but **never accessed**. |
| **Change impact** | Compare any two product versions: added/removed/modified items grouped by category, significance badges, review questions — advisory only, never modifies either version. |
| **Disclosures & reports** | Record immutable public-disclosure events (SHA-256 hash + public verification URL), generate PDF reports (IP brief, disclosure record, expert handoff) each printed with a QR verification code. |
| **Expert review workflow** | `DRAFT → AI_SCREENED → REVIEW_REQUIRED → EXPERT_REVIEW → … → REVIEWED → ARCHIVED`. Only completing a review as `EXPERT`/`ADMIN` promotes rows to `EXPERT_VERIFIED`. The review desk can be emailed per review (`POST /api/reviews/{id}/notify`) — best-effort, with honest failure reporting. |
| **Dashboard, audit, admin** | Per-user dashboard, personal audit trail, admin-only user/corpus/RAG overview and cache stats (`GET /api/admin/cache/stats`, `POST /api/admin/cache/clear`). |
| **Response caching** | An in-process TTL cache (no Redis) serves repeated overview/dashboard/knowledge/graph reads and **identical chat questions** — live on the Supabase free tier, a repeated question drops from 25–69 s to 5–6 s. Analysis and screening runs are reused while the version's `content_hash` is unchanged (`reused: true`; `?reuse=false` forces a fresh run). Every cache key carries a data revision (content hash / row ids), so a hit is never wrong by content. |
| **Multilingual (BHASHINI)** | English / Hindi / Bengali input & output; when BHASHINI is unconfigured the system says so with a warning instead of inventing a translation. |

### The safety rules the AI must follow

* Every citation is validated against passages that were **actually retrieved** — uncited statements are dropped.
* Citations are checked for jurisdiction; cross-jurisdiction citations are removed.
* User-provided facts, verified external evidence and system inferences are reported **separately** (`user_provided_facts`, `verified_external_facts`, `system_inferences`).
* Per-section statuses: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `INSUFFICIENT_EVIDENCE`, `ADDITIONAL_INFORMATION_NEEDED`, `USER_PROVIDED_ONLY`, `REVIEW_RECOMMENDED`, `SUPPORTED_AS_WORKFLOW_ANALYSIS`, `EXPERT_REVIEW_REQUIRED`, `PROCESSING_ERROR` — plus `next_steps` on every non-supported section.
* Banned conclusions (novelty, patentability, infringement, "government approval required/not required", legal advice) are blocked by a deterministic gate.
* Patent screening always reports `retrieval_mode: DEMO_CORPUS` and `search_is_live: false` — no fake patent numbers, ever.

---

## How it works (architecture)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — React SPA (Vite dev server, http://localhost:5173)        │
│  Landing / Login / Products / Versions / Knowledge / Chat / Reviews  │
│  Dashboard / Demo                                                    │
└───────────────┬──────────────────────────────────────────────────────┘
                │  /api/*  (Vite dev proxy → http://localhost:8000)
┌───────────────▼──────────────────────────────────────────────────────┐
│  FastAPI backend (http://localhost:8000)  —  app/main.py             │
│                                                                      │
│  Routers: auth · products/versions · knowledge · assistant ·         │
│  analysis · IP routes/patents · change-impact · disclosures ·        │
│  reports · reviews · dashboard · admin · bhashini · sources · users  │
│                                                                      │
│  RAG pipeline (per question / per sub-question):                     │
│    decompose → chunk → embed (BGE-M3, 1024-d) →                      │
│    hybrid retrieval (pgvector cosine + Postgres FTS) →               │
│    Reciprocal-Rank Fusion → cross-encoder rerank →                   │
│    Groq LLM (llama-3.3-70b) with Sarvam AI fallback →                │
│    citation validation → status/abstention gates → structured JSON   │
│                                                                      │
│  Deterministic engines (no LLM): IP route map, patent screening,     │
│  biodiversity/TK screen, version change impact, disclosure review    │
│  In-process TTL response cache: slow GETs + repeated chat answers    │
└───────────────┬──────────────────────────────────────────────────────┘
                │  SQLAlchemy + Alembic migrations
┌───────────────▼──────────────────────────────────────────────────────┐
│  PostgreSQL 16 + pgvector  (Docker :5433  —or—  managed Postgres)    │
│  tables: users/roles, products, product_versions, ingredients,       │
│  formulation, claims, evidence, target_markets, analyses,            │
│  source_documents, source_chunks (vector), chat_sessions/messages,   │
│  disclosures, reports, reviews, audit_log                            │
└──────────────────────────────────────────────────────────────────────┘

External services (keys go in BACKEND/.env):
  GROQ_API_KEY        – primary LLM (required for AI answers/analysis)
  SARVAM_API_KEY      – optional LLM fallback when Groq fails
  BHASHINI_API_KEY    – optional translation (degrades openly when unset)
  HF_TOKEN            – optional HuggingFace token for the embedding model
```

Two kinds of answers, deliberately kept apart:

* **Retrieval answers** (chat, analysis) — require real retrieved passages; otherwise the section abstains with a status and concrete next steps.
* **Deterministic answers** (IP routes, screening, change impact, disclosure review) — computed from your recorded data only; they are advisory, carry review questions, and never call the model.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ (verified on **3.13**), FastAPI, Pydantic v2 |
| Database | PostgreSQL 14+ with **pgvector**, SQLAlchemy 2, Alembic migrations |
| Auth | JWT (access + refresh), bcrypt, RBAC |
| Retrieval | pgvector cosine + Postgres full-text search, RRF fusion, cross-encoder rerank, BM25 |
| Embeddings | `BAAI/bge-m3` via sentence-transformers (1024-dim, local) |
| LLMs | Groq `llama-3.3-70b-versatile` (primary), Sarvam AI (fallback), JSON structured output |
| Documents | PyMuPDF (page-aware PDF text), ReportLab (PDF reports), QR verification |
| Language | BHASHINI — `en`, `hi`, `bn` |
| Frontend | React 19, Vite 8, react-router-dom 7, D3 (verified on **Node 24**) |
| Testing | pytest (in-memory SQLite), httpx, per-phase live verification scripts |

---

## Repository layout

```
IP-SHAKTI/
├── README.md                    ← you are here (project overview + setup)
├── AGENTS.md                    ← conventions/rules for AI agents working on this repo
├── PROJECT_STATUS.md            ← phase-by-phase verification status
├── DEVELOPMENT_LOG.md           ← chronological development log
├── TODO.md                      ← open work
├── gcp/                         ← GCP free-tier deployment (guide + VM startup script)
├── BACKEND/
│   ├── README.md                ← full API reference (every endpoint)
│   ├── app/
│   │   ├── main.py              ← FastAPI app + /api/health
│   │   ├── config.py            ← settings from .env
│   │   ├── routers/             ← API route handlers (19 routers)
│   │   ├── services/            ← business logic
│   │   ├── rag/                 ← ingestion, chunking, retrieval, citations,
│   │   │                          partial answering (selective per-topic answers)
│   │   ├── analysis/            ← claim review, IP routes, screening, change impact
│   │   ├── embeddings/          ← BGE-M3 provider
│   │   ├── llm/                 ← Groq provider + Sarvam fallback
│   │   ├── bhashini/            ← translation layer
│   │   ├── reports/             ← PDF generation + QR
│   │   ├── models/ · schemas/ · utils/ · data/
│   ├── alembic/                 ← migrations (alembic owns the schema)
│   ├── corpus/                  ← 110+ source documents (Ayurveda, IP, regulation)
│   ├── data/uploads/ · data/reports/   ← user uploads & generated PDFs
│   ├── scripts/                 ← seed_roles, ingest_corpus, verify_* checks
│   ├── tests/                   ← pytest suite (529 tests)
│   ├── docker-compose.yml       ← local pgvector Postgres on port 5433
│   ├── docker-compose.gcp.yml    ← single-VM cloud stack (nginx :80)
│   ├── requirements.txt
│   └── .env.example             ← configuration template (copy to .env)
└── FRONTEND/
    ├── README.md                ← frontend-specific notes
    ├── src/App.jsx              ← router + all pages
    ├── src/Landing.jsx · IPRiskMap.jsx · FormulationRiskDashboard.jsx · …
    ├── vite.config.js           ← dev port 5173 + /api proxy → :8000
    └── package.json
```

---

## Prerequisites

Install these once:

| Requirement | Version | Needed for |
|---|---|---|
| **Python** | 3.11+ (project verified on 3.13) | backend, tests |
| **Node.js** | 20.19+ / 22+ (project verified on 24) | frontend (`npm run dev`, build) |
| **PostgreSQL** | 14+ **with pgvector** | database |
| **Docker** *(optional)* | any recent | easiest way to run the bundled Postgres |
| **Groq API key** | free at console.groq.com | AI answers & analysis (**required** for AI features) |
| **Sarvam AI key** *(optional)* | — | LLM fallback when Groq fails |
| **BHASHINI key** *(optional)* | — | translation; without it the API works and reports honest fallback warnings |
| **HuggingFace token** *(optional)* | — | private embedding-model download (public model works without it) |

Python packages are listed in `BACKEND/requirements.txt`; frontend packages in `FRONTEND/package.json`.

---

## Configuration (.env)

Secrets live **only** in `BACKEND/.env` (git-ignored). Create it from the template:

```bash
cd BACKEND
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
```

| Variable | Required | Purpose / default |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://user:password@host:5432/dbname` (bundled Docker: `postgresql://ipsakti:ipsakti@localhost:5433/ipsakti`) |
| `JWT_SECRET_KEY` | ✅ | strong random secret for signing tokens |
| `JWT_ALGORITHM` | – | `HS256` (default) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | – | `30` / `7` |
| `CORS_ORIGINS` | – | `http://localhost:5173,http://localhost:3000` |
| `LLM_PROVIDER` / `LLM_MODEL` | – | `groq` / `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | ✅ for AI | primary LLM |
| `SARVAM_API_KEY` / `SARVAM_MODEL` | – | fallback LLM (`sarvam-105b-conversations`); empty = fallback disabled |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | – | `sentence-transformers` / `BAAI/bge-m3` / `1024` |
| `HF_TOKEN` | – | HuggingFace access token |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` / `RAG_TOP_K_RETRIEVAL` / `RAG_RERANK_TOP_K` / `RAG_MIN_SIMILARITY` | – | `800` / `120` / `20` / `6` / `0.30` |
| `MAX_UPLOAD_SIZE_MB` / `UPLOAD_DIR` | – | `25` / `data/uploads` |
| `REPORTS_DIR` / `PUBLIC_BASE_URL` | – | `data/reports` / `http://localhost:8000` |
| `BHASHINI_API_KEY` / `BHASHINI_BASE_URL` | – | optional translation |
| `DEBUG` | – | `true` adds the `debug` block to chat responses |
| `CACHE_ENABLED` / `CACHE_MAX_ENTRIES` | – | `true` / `2048` — in-process TTL response cache (no Redis needed) |
| `CACHE_DEFAULT_TTL_SECONDS` / `CACHE_OVERVIEW_TTL_SECONDS` / `CACHE_DASHBOARD_TTL_SECONDS` / `CACHE_STATUS_TTL_SECONDS` / `CACHE_REGISTRY_TTL_SECONDS` / `CACHE_GRAPH_TTL_SECONDS` / `CACHE_EMBEDDING_TTL_SECONDS` / `CACHE_CHAT_TTL_SECONDS` | – | `60` / `300` / `60` / `30` / `300` / `60` / `600` / `600` |
| `CACHE_ANALYSIS_REUSE` | – | `true` — reuse recorded analysis/screening runs while `content_hash` is unchanged (`?reuse=false` forces a fresh run) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_USE_TLS` | – | review-desk email (Gmail App Password, port 587); all empty = notifications honestly report "not configured" and nothing is sent |
| `REVIEW_NOTIFY_EMAIL` / `REVIEW_NOTIFY_FROM` | – | review-desk recipient (default set in `config.py`) / `From:` address (falls back to the SMTP username) |

---

## Getting started — step by step

Open a terminal in the project root (`IP-SHAKTI/`). Two terminals are needed: one for the backend, one for the frontend.

### 1. Database

**Option A — bundled Docker Postgres (recommended for local dev):**

```bash
cd BACKEND
docker compose up -d          # pgvector/pgvector:pg16 on port 5433
```

**Option B — your own PostgreSQL** (local or managed, e.g. Supabase): create a database with the `pgvector` extension available and use its connection string.

### 2. Backend setup

```bash
cd BACKEND

# 2.1 virtual environment (recommended; skip if you run system Python)
python -m venv .venv
# Windows:   .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 2.2 install dependencies
pip install -r requirements.txt

# 2.3 configure
#   Windows: Copy-Item .env.example .env
cp .env.example .env
#   then edit .env: DATABASE_URL, JWT_SECRET_KEY, GROQ_API_KEY

# 2.4 create the schema (Alembic owns the schema; the app never auto-creates tables)
alembic upgrade head

# 2.5 seed roles — REQUIRED once per database (registration assigns the default VIEWER role)
python scripts/seed_roles.py

# 2.6 (first run only) warm the embedding model and index the corpus;
#     otherwise the first AI request blocks while BGE-M3 (several GB) downloads
python scripts/ingest_corpus.py
```

### 3. Start the backend

```bash
cd BACKEND
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

* API root: http://localhost:8000
* Health check: http://localhost:8000/api/health → `{"status": "healthy"}`
* Interactive API docs (Swagger): http://localhost:8000/api/docs

### 4. Start the frontend

```bash
cd FRONTEND
npm install        # first time only
npm run dev        # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000` (see `FRONTEND/vite.config.js`), so no CORS configuration is needed in development.

### Full-stack Docker deployment

For a containerised run (PostgreSQL + pgvector, backend, production frontend):

```bash
cp BACKEND/.env.example BACKEND/.env   # then set DATABASE_URL, JWT_SECRET_KEY, GROQ_API_KEY
docker compose up --build              # app at http://localhost:8080
docker compose exec backend python scripts/seed_roles.py
docker compose exec backend python scripts/ingest_corpus.py --dir corpus/ --public --corpus-version v1.1-verified
```

`BACKEND/Dockerfile` runs `alembic upgrade head` on start (the app never
creates tables at boot); `FRONTEND/Dockerfile` bakes the production bundle
behind nginx with `/api/*` proxied to the backend. Docker is not required
for development - the two-terminal setup above is enough.

### Free-tier cloud deployment (GCP)

An always-free `e2-micro` VM can run the whole stack. The step-by-step guide
lives in [`gcp/DEPLOY_GCP.md`](gcp/DEPLOY_GCP.md) (project setup, the single
`gcloud` command, secret configuration):

* `docker-compose.gcp.yml` — production stack (Postgres + backend + nginx on port 80)
* `gcp/gce-startup.sh` — VM bootstrap: installs Docker, clones this repository,
  writes secrets from instance metadata (never committed) and starts the stack
* The guide runs plain HTTP on the free tier; HTTPS is listed as a follow-up.
  The repository must be publicly cloneable (or the VM given a deploy token),
  because the startup script clones anonymously.

### 5. Open the app

Visit **http://localhost:5173**, click **Register** (JSON fields: username, email, password, confirm_password), then log in.

> **Running on Windows without a venv?** Use the same commands with your system Python, e.g. `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

---

## Verifying the installation

| Check | Expected result |
|---|---|
| `curl http://127.0.0.1:8000/api/health` | `200` — `{"status":"healthy"}` |
| Open http://localhost:8000/api/docs | Swagger UI lists every endpoint |
| Open http://localhost:5173 | Landing page loads; login works |
| Register + login (JSON body) | `201` then `200` with an access token |
| Ask one question in **Chat** | Answer with `overall_status`, `sections[]`, citations and the platform disclaimer |

> Registration and login require **JSON** bodies (`content-type: application/json`); form-encoded data returns `422`.

---

## Using the app (walkthrough)

1. **Register / log in** → you land on `/home`.
2. **Create a product** (`/products/new`) — a product is created together with version 1 (its Product Passport).
3. **Open the version** (`/products/:id/versions/:versionId`) and record its content:
   ingredients → formulation → claims → evidence → target markets.
   Every edit refreshes the version's `snapshot_data` + `content_hash` and writes an audit entry.
4. **Analysis** — *Analyze claims* (claim-to-evidence review) or *Full analysis* (adds preliminary classification). Runs are recorded and reviewable, including failures.
5. **IP screening** — IP route map, patent screening with feature comparison, biodiversity/ABS and traditional-knowledge screens (deterministic, instant; *include corpus sources* opts into a corpus search).
6. **Versions page** — *Formulation change impact* compares any two versions.
7. **Knowledge** (`/knowledge`) — upload your own documents (PDF/TXT/DOCX) to make them searchable by the assistant.
8. **Chat** (`/chat`) — ask questions (multi-part questions are decomposed and answered per topic). Attach PDFs for page-cited answers; switch output language `en` / `hi` / `bn`.
9. **Disclosures & reports** — record disclosure events, then generate the IP brief / disclosure record / expert handoff PDFs (each with a QR verification link).
10. **Reviews** (`/reviews`) — submit a version into the expert-review workflow; an `EXPERT`/`ADMIN` completing a review is the only path to `EXPERT_VERIFIED`. Use **Email reviewer** to notify the review desk (best-effort — a missing SMTP config or send failure is reported honestly and never blocks the workflow).
11. **Dashboard** (`/dashboard`) — counts, pending reviews, recent activity; `/demo` shows the showcase screens.

---

## Testing and verification scripts

```bash
cd BACKEND

# Full unit/integration suite — runs against in-memory SQLite (never touches real data)
python -m pytest tests/ -q                      # 529 tests

# With coverage
python -m pytest tests/ --cov=app --cov-report=html
```

Live verification against the configured database (each script creates temporary
data and deletes what it created — **do not run them in parallel** against a
shared/remote database):

```bash
python scripts/verify_migrations.py   # migration chain check, rolled back
python scripts/verify_phase2.py       # ... through ...
python scripts/verify_phase9.py       # per-phase end-to-end checks
python scripts/verify_demo_flow.py    # full Ashwagandha demo workflow
python scripts/ingest_corpus.py       # (re)index the knowledge corpus

# With the server running — drives the same HTTP calls the UI makes (127 checks)
python scripts/verify_frontend_flow.py
```

> **Migration safety:** never run `alembic downgrade` against a database you care about — it drops tables and commits. Use `scripts/verify_migrations.py` to validate the chain safely inside a rolled-back transaction.

---

## API and frontend reference

* **Full endpoint documentation:** [BACKEND/README.md](BACKEND/README.md) — auth, products/versions/passport, version content (ingredients, formulation, claims, evidence, markets), analysis, IP routes & patent screening, change impact, disclosures, reports, expert reviews, dashboard/audit/admin, knowledge base, sources, assistant/chat, BHASHINI.
* **Live Swagger UI:** http://localhost:8000/api/docs while the backend runs.

Key routes at a glance:

| Group | Endpoints |
|---|---|
| Auth | `POST /api/auth/register` · `login` · `refresh` · `logout` · `GET /api/auth/me` |
| Products | `POST/GET/PUT/DELETE /api/products` · `GET/PUT /api/products/{id}/passport` |
| Versions | `/api/products/{id}/versions[...]` (+ `/clone`) |
| Content | `/versions/{vid}/ingredients` · `/formulation` · `/claims` · `/evidence` · `/target-markets` |
| Analysis | `POST /claims/analyze` · `POST /analyze` · `GET /analyses[/{id}]` |
| IP & screening | `GET /ip-routes` · `POST /patents/search|compare` · `POST /biodiversity/screen` · `POST /traditional-knowledge/screen` |
| Change impact | `POST/GET /api/products/{id}/change-impact` |
| Disclosures | `/versions/{vid}/disclosures` · `/disclosure-review` · `GET /api/disclosures/{id}/verify` |
| Reports | `POST /versions/{vid}/reports/{type}` · `GET /api/reports/{id}[/verify]` |
| Reviews | `POST /api/reviews` · state transitions (`submit`, `request-review`, `complete`, …) · `POST /api/reviews/{id}/notify` |
| Knowledge | `GET/POST /api/knowledge/documents` · `/index` · `/status` |
| Assistant | `POST /api/assistant/chat` · `/attachments` · `GET/DELETE /api/assistant/conversations` |
| Dashboard/Admin | `GET /api/dashboard` · `/api/audit` · `/api/admin/*` (incl. `cache/stats`, `cache/clear`) |

Frontend routes: `/` (landing), `/login`, `/register`, `/home`, `/products`, `/products/new`, `/products/:id/versions`, `/products/:id/versions/:versionId`, `/knowledge`, `/chat`, `/reviews`, `/dashboard`, `/demo`.

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Browser shows **502 / "Failed to fetch" / connection refused** | The backend is not running. Start uvicorn (step 3) and confirm `GET /api/health` returns `200`. |
| **Registration fails** with a role/database error | Roles table is empty — run `python scripts/seed_roles.py` once per database. |
| **First AI request takes minutes** | The BGE-M3 model is downloading (several GB). Warm it once with `python scripts/ingest_corpus.py`, then subsequent calls are fast. |
| Analysis returns **503** immediately | `GROQ_API_KEY` missing/invalid — the provider is resolved before retrieval so it fails fast. Add the key to `.env` and restart. |
| Groq **rate limit / outage** errors | 8k TPM free tier is tight. With `SARVAM_API_KEY` set the same prompt is retried once on Sarvam AI; otherwise you get an honest error, not a fabricated answer. |
| **CORS errors** in the browser | Add your origin to `CORS_ORIGINS` in `.env` (dev uses the Vite proxy, so this is only for non-proxied access). |
| Chat answers in English although you asked in Hindi | BHASHINI is unconfigured — the response carries `translated: false` and an explicit warning. Set `BHASHINI_API_KEY` to enable translation. |
| `404` on `/health` | The health endpoint is `/api/health` (with the `/api` prefix). |
| Port already in use | Backend: change `--port`; frontend: change `--port` in `vite.config.js` or pass `--port` to Vite. |
| Schema errors after pulling changes | Run `alembic upgrade head` (the app never creates tables at startup). |
| Tests seem to hit your real database | They don't — the pytest suite uses an in-memory SQLite database. Only the `verify_*` scripts touch the configured database. |
| Stale bytecode after editing code | Delete `__pycache__` folders / `.pytest_cache` — they regenerate automatically. |

---

## Security model

* **Secrets only in `.env`** — never committed; `.env` is git-ignored.
* JWT access tokens with expiry + httpOnly refresh cookie; passwords hashed with **bcrypt**.
* **RBAC** — products are owner-only (ADMIN sees all); reviewer actions require `EXPERT`/`ADMIN`; admin endpoints require `ADMIN`.
* **Provenance firewall** — the server stamps provenance; clients cannot set it. `EXPERT_VERIFIED` rows cannot be edited or deleted through content endpoints (`409`).
* **Evidence-status firewall** — users may only set `user_provided` / `needs_evidence`; conclusions (`supported`, `partially_supported`, `expert_verified`) return `422` because they must come from evidence review or expert workflow.
* **Ownership/IDOR protection** — child resources from another version/user return `404`.
* **Audit logging** on auth, product, content, analysis, review and admin operations.
* SQL-injection protection via the SQLAlchemy ORM; input validation via Pydantic.
* Document hashes (SHA-256) for disclosures and reports; public verification endpoints expose no file paths or internal ids.

---

## Project status and documentation

**Status: all phases 0–13 implemented and verified, plus the problem-statement completion batch** (explicit jurisdiction switch, citation confidence, clarifications loop, mounted privacy/registry/graph/agent layers, migrations 012–014, Docker deployment), **and the response-cache / answer-cache layer** (in-process TTL cache, chat answer cache, analysis/screening reuse, review-desk email, GCP free-tier artifacts) — see [PROJECT_STATUS.md](PROJECT_STATUS.md) for evidence per phase and [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) for the cache entries.

| Document | Purpose |
|---|---|
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Phase-by-phase status, features, verification evidence |
| [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) | Chronological log of every change and test run |
| [TODO.md](TODO.md) | Open work / deferred items |
| [AGENTS.md](AGENTS.md) | Rules for AI agents working on this repository |
| [BACKEND/README.md](BACKEND/README.md) | Complete API reference |
| `../IP-SAKTI-Sahayak-Backend-Master-Prompt.txt` | Original specification this project is built against |

**Verification at a glance:** `529` pytest tests pass with 0 failures (in-memory SQLite); per-phase live scripts plus the extended frontend-flow script pass against real PostgreSQL; the exact spec-17 chat scenario passes its live acceptance checks against the real LLM.

---

## License

No license file has been published yet. Add one before distributing the project.

---

*IP-SAKTI Sahayak — preliminary, source-backed decision support for Ayurveda IP and regulatory workflows. Not legal, patent, regulatory, medical or government advice.*
