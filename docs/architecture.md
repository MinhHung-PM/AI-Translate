# Architecture — AI Meeting Translator & Memo Hub (Workstreams 1 & 2)

## Overview

```
Browser ──HTTPS──▶ Next.js (web, :3000) ──/api/v1 proxy──▶ FastAPI (api, :8000) ──▶ PostgreSQL
                                                              ▲                         ▲
                                                              │ enqueue (jobs table)    │
                                                     worker (python -m app.worker) ─────┘
                                                              │
                                                              ▼
                                               AI provider (mock | OpenAI | OpenAI-compatible)

Workstream 2 (meeting platforms):
  Graph / Zoom API / Meet REST ◀─OAuth tokens (encrypted)── api + worker ──▶ same TranscriptEntry pipeline
  Zoom webhooks ──▶ POST /integrations/zoom/webhook ──▶ provider_events ──▶ jobs (fetch_transcript | realtime_ingest)
  Zoom RTMS (official SDK, worker thread) ──▶ ordering buffer ──▶ ingest_event ──▶ translate ──▶ live feed (polling)
```

* **web** — Next.js 16 App Router, strict TypeScript, Tailwind v4. Client-rendered pages; the browser
  only talks to its own origin. `/api/v1/*` is rewritten server-side to the API, so session cookies
  are first-party and no backend URL or secret reaches client bundles.
* **api** — FastAPI + Pydantic + SQLAlchemy 2 (sync, psycopg 3). Versioned REST under `/api/v1`,
  OpenAPI at `/api/v1/openapi.json`, Swagger UI at `/api/docs`.
* **worker** — the same image running `python -m app.worker`. Claims jobs from PostgreSQL with
  `SELECT … FOR UPDATE SKIP LOCKED`, runs translation / memo generation / replay, and performs
  maintenance (expired-session purge, retention, stale-job requeue). `EMBEDDED_WORKER=true` runs it
  inside the API process for single-process development.
* **PostgreSQL 16** — the only stateful dependency. **Redis is not required**: the job queue lives in
  PostgreSQL. The in-process rate limiter is the one component that would need Redis when running
  several API replicas (see Known limitations).

## Backend layering (`backend/app`)

| Layer | Modules | Responsibility |
|---|---|---|
| API | `api/v1/*.py`, `api/deps.py` | HTTP, auth/CSRF dependencies, request/response schemas, status codes |
| Authorization | `services/authz.py` | Single policy module; every query is filtered through it |
| Services | `services/*.py` | Business rules: import, translation, memo generation, exports, usage, retention |
| Transcript pipeline | `services/transcripts/` | Parsers (TXT/SRT/VTT/JSON), decoding, normalization, segmentation, language detection |
| AI abstraction | `ai/base.py`, `ai/llm.py`, `ai/openai_provider.py`, `ai/mock.py`, `ai/catalog.json` | Provider-neutral interfaces, adapters, prompts, output schemas |
| Connectors (WS1) | `connectors/` | Platform status summary for the meeting form; replay demo |
| Integrations (WS2) | `integrations/` | Connector contract, capabilities, canonical event, normalization (dedup/ordering), OAuth, Teams/Zoom/Meet connectors, orchestration (ingestion, retrieval, live sessions, recovery). See [`workstream-2-integration-contract.md`](workstream-2-integration-contract.md) |
| Data | `models/`, `alembic/` | SQLAlchemy models, migrations |
| Core | `core/` | Settings, structured logging + redaction, AES-GCM keyring, errors, rate limiting |

### AI provider abstraction

```
TranslationProvider / MemoGenerationProvider   (business logic depends only on these)
   ├── LLMTranslationProvider / LLMMemoGenerator  (prompting + output validation)
   │       └── AIProvider.complete_json            (OpenAIProvider: wire format, error mapping)
   └── MockProvider                                 (deterministic, no network)
UsageMeter (DbUsageMeter) records every call; cost = configured price × tokens ("Estimated Cost").
```

Providers, models, prices and capabilities are configuration (`ai/catalog.json`,
`PROVIDER_CATALOG_PATH`), not code. Adding a provider with a different wire format means adding one
adapter implementing `AIProvider` (or the two higher-level protocols directly).

### Processing flows

1. **Import** (synchronous, bounded by `MAX_UPLOAD_BYTES`): decode → parse → normalize (NFC, control
   characters, long-entry splitting) → detect language → store `transcript_entries` with sequence numbers.
2. **Translate** (job): entries grouped by source language and chunked (`TRANSLATION_CHUNK_MAX_ENTRIES`
   / `_CHARS`), with two preceding lines as context and only the glossary terms that occur in the chunk.
   Output must return exactly the input refs; malformed output is retried (`AI_OUTPUT_MAX_ATTEMPTS`).
   Failures mark only that chunk's translations `failed`; auth/quota errors stop the job.
3. **Generate memo** (job): versioned prompt (`memo-v1`) → strict `MemoDraft` schema validation with
   bounded repair retries → grounding checks (owners must appear in cited lines; deadlines resolved
   deterministically) → items persisted as `draft`/`needs_review` with source links.
4. **Review**: humans edit, confirm/reject items, submit, approve/reject (project manager only).
   Approved memos lock content; action tracking (status/owner/due) continues.
5. **Replay demo** (job): parsed events are emitted one by one through `services/ingestion.ingest_event`
   — the same entry point real connectors will use — and translated per entry. UI polls `/live`.

## Frontend structure (`frontend/src`)

* `app/(main)/…` — the eight screens (dashboard, new meeting, transcript workspace, memo editor,
  live replay, action tracker, history, projects, settings, usage, admin); `app/login`.
* `components/ui` — small accessible component set (native `<dialog>`, labelled fields, focus rings).
* `lib/api.ts` — fetch wrapper; CSRF token kept in memory only. `lib/i18n` — typed Vietnamese dictionary.

## Deployment notes

* Production requires `ENVIRONMENT=production`, `AUTH_MODE=oidc`, `SESSION_COOKIE_SECURE=true`,
  explicit `TRUSTED_HOSTS`, `ENABLE_MOCK_PROVIDER=false` — startup fails otherwise
  (`Settings.validate_for_environment`).
* Terminate TLS at a reverse proxy/ingress in front of `web`; keep `api` on a private network.
* `SECRET_ENCRYPTION_KEYS` should be injected from a secret manager (Azure Key Vault, AWS Secrets
  Manager, …); rotation procedure in `docs/security.md`.
