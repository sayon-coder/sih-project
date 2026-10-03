# PRIVACY.md — DPDP-aligned privacy layer + authoritative-sources / consent-gated connectors

**Module:** IP-SAKTI Sahayak backend (`BACKEND/`)
**Framework cited:** Digital Personal Data Protection Act, 2023 (India) — cited by name only; this
document deliberately does not invent section numbers.
**Notice version:** `PRIVACY_NOTICE_VERSION` (default `2026-09-1`), declared in `app/config.py` and
served by `GET /api/privacy/notice`.

---

## 1. What this layer adds (the two audit findings it closes)

| Finding | Was missing | Is now implemented in |
|---|---|---|
| **A** — *"access to authoritative sources — free official databases directly and the user's own paid subscriptions only with explicit, logged permission"* | No links to any official registry (`traditional_knowledge_sources.py` had `url: None` on all 5 entries); `grep consent` = 0 matches; no paid-subscription mechanism anywhere | `app/data/official_sources.py` (33 sourced entries, real URLs), `app/routers/sources_registry.py`, `SourceConsent` + `SourceAccessLog` tables, `app/routers/privacy.py` source-permission routes |
| **B** — *"privacy, audit and security aligned to the Digital Personal Data Protection regime"* | No consent capture, no retention/erasure, no data-principal rights, no privacy notice, no PII handling; audit logging absent from the knowledge router; `auth_service.py` wrote `email`/`username` into audit `details` | `DataConsent` table, `GET/POST/DELETE /api/privacy/consent`, `GET /api/privacy/export`, `DELETE /api/privacy/account`, `GET /api/privacy/retention`, `POST /api/privacy/purge`, `PRIVACY_NOTICE_TEXT`, audit logging in `routers/knowledge.py`, `sanitize_details()` in `app/services/audit_service.py` |

---

## 2. DPDP mapping table

| DPDP concept | Implemented endpoint / mechanism | Status |
|---|---|---|
| Notice before consent | `GET /api/privacy/notice` → `PRIVACY_NOTICE_TEXT` + `PRIVACY_NOTICE_VERSION` + purposes + rights; also `GET /api/users/me/privacy` (entry point) | **Implemented** |
| Consent: free, specific, informed, unconditional, unambiguous, purpose-limited | `POST /api/privacy/consent {purposes[], grant:true}` → `DataConsent(notice_version, purposes, granted, granted_at)`; `grant` must be an explicit `true` (400 `GRANT_REQUIRED`); unknown purposes rejected (400 `UNKNOWN_PURPOSE`) | **Implemented** |
| Consent bounded to a named notice version | `DataConsent.notice_version` is stamped from the `PRIVACY_NOTICE_VERSION` setting at write time | **Implemented** |
| Right to withdraw consent | `DELETE /api/privacy/consent/{id}` → sets `withdrawn_at`, never deletes the row (auditability), idempotent, owner-scoped (404 for another user's row) + audit `withdraw_privacy_consent` | **Implemented** |
| Consent for third-party / paid processing (explicit + logged) | `POST /api/privacy/sources/consent` (`confirm:true` mandatory) → `SourceConsent(GRANTED)` + `SourceAccessLog(PERMISSION_GRANTED)` + audit entry; `DELETE /api/privacy/sources/consent/{id}` revokes → `SourceConsent(REVOKED)` + `SourceAccessLog(PERMISSION_REVOKED)` | **Implemented** |
| Access to personal data (right of access) | `GET /api/privacy/export` — one JSON payload: profile, roles, products, versions, claims, evidence, disclosures, reports, chat sessions/messages/attachments, uploaded-document metadata, audit entries, consents, source consents, source access log. Owner-scoped **by construction** (no user-id parameter), returned as a downloadable attachment | **Implemented** |
| Portability | Same export (`format: ip-sakti-data-export/v1`), capped by `EXPORT_MAX_ITEMS` per dataset with an explicit `truncated` list | **Implemented** |
| Correction | `PUT /api/users/me` (username / email), pre-existing; recorded in the export | **Implemented** (pre-existing) |
| Right to erasure | `DELETE /api/privacy/account {"confirm": "<own email>"}` → anonymise + delete (see §5) + audit `data_erasure` | **Implemented** |
| Retention limited to the purpose | `GET /api/privacy/retention` (policy as data), `POST /api/privacy/purge` (ADMIN) applies `CHAT_RETENTION_DAYS` / `UPLOAD_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS`; `0` = never purge | **Implemented** (manual purge; no scheduler) |
| Accountability / audit trail | `AuditService.log_action` on every privacy action; knowledge upload/delete/reindex now audited; `sanitize_details()` redacts PII from every `details` payload | **Implemented** |
| Grievance redressal | The notice states the right and points at the deployment's support channel; privacy actions are visible to the data principal at `GET /api/audit` and `GET /api/privacy/sources/access-log` | **Partially** — no ticketing workflow exists in this build |
| Nomination (nominee exercises rights) | Described in the notice as a right; no model/endpoint exists | **Not implemented** (see §8) |
| Children's data | The notice states the platform is not directed at children and does not track them | **Statement only** — no age gate exists |
| Data-fiduciary obligations (DPO contact, consent managers, breach notification workflow) | — | **Not implemented** (see §8) |

---

## 3. Consent + access-log model

Three tables, defined in `app/models/privacy_models.py`:

```
DataConsent         — consent to the privacy notice and its purposes
SourceConsent       — explicit permission for one external connector
SourceAccessLog     — the evidence trail (grant / deny / revoke / access / block)
```

**Permission lifecycle** (`SourceConsent.permission`): `GRANTED → REVOKED` (user withdraws),
`GRANTED → EXPIRED` (detected lazily on read: `expires_at` passed ⇒ the row is flipped to `EXPIRED`
and access is refused), `DENIED` (recorded when permission is refused).

**Evidence vocabulary** (`SourceAccessLog.action`): `PERMISSION_GRANTED`, `PERMISSION_DENIED`,
`PERMISSION_REVOKED`, `ACCESS_ATTEMPTED`, `ACCESS_BLOCKED_NO_PERMISSION`, `ACCESS_PERFORMED`.

**The access decision** (`POST /api/privacy/sources/access`):

1. Resolve the source in the official-source registry (unknown id ⇒ 404 `SOURCE_NOT_FOUND`).
2. Look up the caller's *latest* permission row for that source.
3. **No effective `GRANTED` permission** ⇒ write `ACCESS_BLOCKED_NO_PERMISSION` **and**
   `PERMISSION_DENIED` (+ audit `source_access_blocked`), then **403** with a machine-readable body:
   `{"detail": {"code": "ACCESS_BLOCKED_NO_PERMISSION", "grant_endpoint": "POST /api/privacy/sources/consent", ...}}`.
4. **Permission granted** ⇒ write `ACCESS_ATTEMPTED` then `ACCESS_PERFORMED` (+ audit
   `source_access_performed`) and return the connector descriptor:
   `mode: "HANDOFF"`, `data_fetched_by_platform: false`, the source URL and instructions.

> **Honesty rule:** this platform never proxies, scrapes or fetches a paid/restricted source.
> Permission records *that the user is allowed to open it themselves*; the hand-off is issued and
> logged, and the user performs the access in their own subscription. No paid data is ever stored.

Every privacy/permission route also writes a regular `AuditLog` entry
(`grant_privacy_consent`, `withdraw_privacy_consent`, `grant_source_consent`,
`revoke_source_consent`, `source_access_blocked`, `source_access_performed`,
`export_data`, `data_erasure`, `purge_retention`), so the `GET /api/audit` trail and the
`GET /api/privacy/sources/access-log` trail agree.

---

## 4. Data-principal rights endpoints

| Right | Endpoint | Notes |
|---|---|---|
| Notice | `GET /api/privacy/notice`, `GET /api/users/me/privacy` | Full text, purposes, rights, retention |
| Access & portability | `GET /api/privacy/export` | JSON attachment, owner-scoped, per-dataset capped by `EXPORT_MAX_ITEMS` |
| Consent (grant) | `POST /api/privacy/consent` | `grant: true` required |
| Consent (read) | `GET /api/privacy/consent` | Notice + caller's records |
| Withdraw consent | `DELETE /api/privacy/consent/{id}` | Row kept, `withdrawn_at` stamped |
| Correction | `PUT /api/users/me` | Pre-existing |
| Erasure | `DELETE /api/privacy/account` | Typed confirmation `{"confirm": "<email>"}` |
| Retention (read) | `GET /api/privacy/retention` | Policy as data |
| Retention (apply) | `POST /api/privacy/purge` | ADMIN only; `retention_days == 0` ⇒ never purges |
| Connector permission | `POST /api/privacy/sources/consent` / `GET` / `DELETE /{id}` | `confirm: true` required |
| Permission evidence | `GET /api/privacy/sources/access-log` | Caller's own trail only |
| Free official sources | `GET /api/official-sources`, `/topics`, `/{source_id}` | Filterable registry |

---

## 5. Erasure: what is erased, what is retained

`DELETE /api/privacy/account` requires `{"confirm": "<the caller's own email>"}` (400
`CONFIRM_MISMATCH` otherwise) and then:

**Erased**
- chat sessions + chat messages + chat attachments of the caller;
- uploaded document rows **and** their files on disk (chunks first, then rows);
- `DataConsent` rows and `SourceConsent` rows;
- role assignments of the account;
- the account's identifiers: `email → deleted+<id>@example.invalid`, `username → NULL`,
  `password_hash → "erased"` (no longer a valid bcrypt hash), `is_active → false`.
  The row itself survives so foreign keys keep pointing at something (anonymise, don't break).

**Retained (deliberately)**
- `AuditLog` rows — with `user_id` set to **NULL** (the schema's `ondelete="SET NULL"` semantics,
  applied in SQL), so the trail proves what happened without identifying anyone;
- `SourceAccessLog` rows — likewise `user_id → NULL` (`source_consent_id → NULL` on cascade);
- project records the user created (products, versions, reports, disclosures) — they belong to the
  work product, not to the person, and now point at the anonymised account.

The response is an honest summary: `{"erased": {...counts...}, "retained": {...counts...},
"anonymised_user": {...}}`. The erasure itself is audited as action **`data_erasure`**
(`details.action_label = "DataErasure"`).

---

## 6. Retention policy

Settings (all in `app/config.py`, documented in `.env.example`):

| Setting | Default | Meaning |
|---|---|---|
| `PRIVACY_NOTICE_VERSION` | `2026-09-1` | Version stamped on every consent record |
| `CHAT_RETENTION_DAYS` | `0` | 0 = keep until the user deletes it |
| `UPLOAD_RETENTION_DAYS` | `0` | 0 = keep until the user deletes it |
| `AUDIT_RETENTION_DAYS` | `0` | 0 = **never purge** (audit is evidence) |
| `SOURCE_CONSENT_DEFAULT_DAYS` | `365` | Default validity of a granted connector permission |
| `EXPORT_MAX_ITEMS` | `50000` | Per-dataset cap for the export |

`GET /api/privacy/retention` returns this as data, including, per dataset: `retention_days`,
`action`, `purge_job_exists`, `purge_job`, `automatic_purge_job`.
`POST /api/privacy/purge` (ADMIN) is the purge job: **manual, not scheduled**
(`purge_job.scheduled == false`). It deletes chat messages older than the window, then sessions
left with no messages, then uploaded documents (rows + files + chunks), then — only if
`AUDIT_RETENTION_DAYS > 0` — audit rows. A run with every window at `0` deletes nothing, and that
behaviour is covered by tests.

---

## 7. Audit coverage and PII handling

- `AuditService.sanitize_details(details)` (new, in `app/services/audit_service.py`) redacts any
  key whose normalised name matches `email | username | password | token | secret | phone | mobile`
  (case-insensitive, separator-insensitive: `user_name`, `api-token`, `refresh_token` all match),
  recursively through nested dicts/lists, replacing values with `"***"`. `log_action` now applies it
  unconditionally — so `routers/audit.py`'s docstring promise ("sensitive values are never stored in
  audit details") is true even for `app/services/auth_service.py`, which this layer was **not**
  allowed to edit. Opaque ids (`user_id`, `product_id`) and non-PII field names stay readable so the
  audit trail keeps its investigative value.
- `app/routers/knowledge.py` now audits **upload**, **delete** and **reindex** of knowledge
  documents (resource `knowledge_document`, actions `upload_document`, `delete_document`,
  `reindex_document`) with `Request` for IP/user-agent.
- **Integration note:** the chat router's audit call is added by the integrator (this layer may not
  edit `app/routers/assistant.py`). Chat reads/queries are therefore **not** yet audit-logged;
  chat content is covered by the export and by erasure.

---

## 8. Deliberately NOT implemented (no overclaiming)

1. **No proxying of paid sources.** No paid/restricted content is ever fetched, cached or stored —
   only `HANDOFF` descriptors and permission logs.
2. **No nomination workflow** (nominee designation under the Act): stated as a right in the notice,
   no endpoint or model exists.
3. **No grievance ticketing / SLA tracking**: the notice points at the deployment's support channel.
4. **No background purge scheduler**: retention is applied on demand by an ADMIN.
5. **No age gate / children's-consent mechanism**; the notice states the service is not for children.
6. **No data-fiduciary registration, DPO directory, or breach-notification workflow.**
7. **No consent manager / consent dashboard integration** and no cookie consent UI (backend API only).
8. **No encryption-at-rest or field-level encryption of PII** — that is an infrastructure concern.
9. **No cross-border transfer controls** beyond what the notice states; no per-country transfer log.
10. **TKDL is never accessed.** The registry entry is `RESTRICTED_NOT_ACCESSED`, never `FREE`, and
    the platform neither queries nor reproduces its contents.

---

## 9. Authoritative-sources registry

`app/data/official_sources.py` — 33 entries covering, at minimum:
IP India (patent search, e-Register, TM public search, GI search), NBA India, TKDL (restricted),
Ministry of AYUSH, CDSCO, FSSAI, e-Gazette, India Code, PPV&FR Authority (`plantauthority.gov.in`),
CCRAS; WIPO (PATENTSCOPE, Madrid Monitor, Hague, Global Brand Database, WIPO Lex), EPO Espacenet,
USPTO, Google Patents, The Lens, EUIPO, WTO TRIPS, CBD, Nagoya ABSCH, EUR-Lex, EMA, WHO; plus paid
connectors (Derwent Innovation, Questel Orbit, TotalPatent One) and a third-party API
(Google Patents Public Data on BigQuery).

Each entry carries `id, title, authority, jurisdiction, ip_types, topics, access, url,
what_you_can_do, notes, verified_on`, and is served with derived flags
`requires_permission`, `direct_access`, `restricted_note`.

Access vocabulary: `FREE`, `FREE_REGISTRATION`, `PAID_SUBSCRIPTION`, `THIRD_PARTY_API`,
`RESTRICTED_NOT_ACCESSED`. Anything outside `FREE`/`FREE_REGISTRATION` is returned with
`requires_permission: true`, `direct_access: false` and a `restricted_note` — never as if it were
directly accessible.

Functions: `list_official_sources(jurisdiction=, ip_type=, topic=, access=)`,
`get_official_source(id)`, `sources_for_topic(query)`, `distinct_topics()`,
`distinct_jurisdictions()`.

> **URL verification:** `verified_on = "2026-09-28"`, top-level official domains preferred over
> deep links. **Re-verify before relying on any entry** — official sites move. A registry entry is a
> pointer, not a citation; citations are only ever emitted for passages actually retrieved from the
> corpus.

### Prefix collision note (why `/api/official-sources` and not `/api/sources`)

`app/routers/sources.py` already owns `/api/sources`, `/api/sources/search` and
`/api/sources/{source_id}` for **corpus documents** (asserted by `tests/test_gap_endpoints.py`).
Starlette matches routes in registration order and its `/{source_id}` path param is `str`-shaped at
the routing layer, so:

- registering this router **before** `source_router` would shadow `GET /api/sources` and break
  `tests/test_gap_endpoints.py`;
- registering it **after** would make every one-token suffix (e.g. `/topics`) return **422** from
  the corpus router's integer `source_id` validation before this router is ever reached.

`/api/official-sources` is collision-free in either order. If the integrator prefers the literal
`/api/sources` path, the corpus router must be moved/renamed first (not this layer's file to edit).

---

## 10. Router registration (for the integrator)

```python
from app.routers.privacy import router as privacy_router              # prefix "/api/privacy"
from app.routers.sources_registry import router as sources_registry_router  # prefix "/api/official-sources"
```

Register **before/after `source_router` does not matter** (no shared prefix). `app/main.py` was not
edited by this layer.

**Alembic:** `alembic/env.py` imports `app.models` (the package `__init__`), which does **not**
import `app/models/privacy_models.py`. Before `alembic revision --autogenerate`, add
`import app.models.privacy_models` (or re-export the three classes from `app/models/__init__.py`),
otherwise the new tables will be invisible to autogenerate.

---

## 11. New tables (exact columns for the migration)

### `data_consents`
| Column | Type | Constraints |
|---|---|---|
| `id` | `Integer` | PK, indexed |
| `user_id` | `Integer` | NOT NULL, FK `users.id` ON DELETE CASCADE, indexed |
| `notice_version` | `String(50)` | NOT NULL |
| `purposes` | `Text` | NOT NULL (JSON list of purpose keys) |
| `granted` | `Boolean` | NOT NULL, default `false` |
| `granted_at` | `DateTime(timezone=True)` | NULL |
| `withdrawn_at` | `DateTime(timezone=True)` | NULL |
| `created_at` | `DateTime(timezone=True)` | NOT NULL, server default `now()` |

### `source_consents`
| Column | Type | Constraints |
|---|---|---|
| `id` | `Integer` | PK, indexed |
| `user_id` | `Integer` | NOT NULL, FK `users.id` ON DELETE CASCADE, indexed |
| `source_id` | `String(100)` | NOT NULL, indexed |
| `source_title` | `String(255)` | NOT NULL |
| `access_type` | `String(50)` | NOT NULL (`PAID_SUBSCRIPTION` \| `THIRD_PARTY_API` \| `FREE`) |
| `scope` | `Text` | NOT NULL (JSON list) |
| `permission` | `String(20)` | NOT NULL, default `GRANTED` (`GRANTED` \| `DENIED` \| `REVOKED` \| `EXPIRED`) |
| `granted_at` | `DateTime(timezone=True)` | NULL |
| `revoked_at` | `DateTime(timezone=True)` | NULL |
| `expires_at` | `DateTime(timezone=True)` | NULL |
| `ip_address` | `String(45)` | NULL (IPv6 compatible) |
| `user_agent` | `Text` | NULL |
| `created_at` | `DateTime(timezone=True)` | NOT NULL, server default `now()` |

### `source_access_logs`
| Column | Type | Constraints |
|---|---|---|
| `id` | `Integer` | PK, indexed |
| `user_id` | `Integer` | NULL, FK `users.id` ON DELETE **SET NULL**, indexed |
| `source_consent_id` | `Integer` | NULL, FK `source_consents.id` ON DELETE **SET NULL** |
| `source_id` | `String(100)` | NOT NULL, indexed |
| `action` | `String(50)` | NOT NULL, indexed |
| `detail` | `Text` | NULL |
| `ip_address` | `String(45)` | NULL |
| `created_at` | `DateTime(timezone=True)` | NOT NULL, server default `now()` |

---

## 12. Files

**Created:** `app/data/official_sources.py`, `app/models/privacy_models.py`,
`app/routers/privacy.py`, `app/routers/sources_registry.py`, `app/services/privacy_service.py`,
`tests/test_privacy.py`, `tests/test_sources_registry.py`, `PRIVACY.md`.
**Edited (additive only):** `app/config.py` (+6 settings), `.env.example` (+6 keys),
`app/services/audit_service.py` (`sanitize_details` + applied in `log_action`),
`app/routers/knowledge.py` (3 audit calls), `app/routers/users.py` (`GET /api/users/me/privacy`).
**Not touched:** `app/main.py`, `app/routers/assistant.py`, `app/rag/*`, `app/analysis/*`,
`app/graph/*`, `app/agents/*`, `alembic/*`, `corpus/`, `FRONTEND/`, existing tests,
`DEVELOPMENT_LOG.md`, `TODO.md`, `PROJECT_STATUS.md`, `app/data/traditional_knowledge_sources.py`,
`app/services/auth_service.py`.
