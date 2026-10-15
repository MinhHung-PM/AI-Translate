# AI Meeting Translator & Memo Hub — Workstream 1 (Product Core)

Internal web application for an IT outsourcing company serving Japanese clients. Project managers,
BrSEs, BAs, tech leads and division managers import meeting transcripts (Japanese / Vietnamese /
English), translate them, generate structured AI meeting minutes, review and approve them, and track
decisions, action items, issues and risks — each traceable to the original transcript line.

> **Scope.** Live Teams/Zoom/Google Meet integrations are Workstream 2 and are shown in the UI as
> *"Integration not configured"*. The live-style view in this release is an explicitly labelled
> **replay demo** of an imported transcript. See [`docs/workstream-2-integration-contract.md`](docs/workstream-2-integration-contract.md).

## Contents

| Path | |
|---|---|
| `backend/` | FastAPI + SQLAlchemy 2 + Alembic API and worker (Python 3.12) |
| `frontend/` | Next.js 16 App Router UI (TypeScript strict, Tailwind v4), Vietnamese interface |
| `samples/` | Sample transcripts: `ja_client_meeting.vtt`, `vi_internal_meeting.txt`, `en_steering_meeting.srt`, `sample_transcript.json`, `prompt_injection_test.txt` |
| `docs/` | [architecture](docs/architecture.md) · [data model](docs/data-model.md) · [security](docs/security.md) · [API contract](docs/api-contract.md) · [OpenAPI](docs/openapi.json) · [WS2 contract](docs/workstream-2-integration-contract.md) · [feature matrix, limitations, backlog](docs/feature-matrix.md) |
| `docker-compose.yml` | db, migrate (+ seed), api, worker, web |

## Quick start (Docker Compose)

```bash
cp .env.example .env
# Required for accepting user API keys (the mock provider works without it):
python3 -c "import base64,os;print('SECRET_ENCRYPTION_KEYS=kdev:'+base64.b64encode(os.urandom(32)).decode())" >> .env
docker compose up --build
```

Open <http://localhost:3000>, pick a seeded user (development login), e.g. **Trần Minh (PM)** —
`pm@example.com`. Redis is not needed: background jobs use a PostgreSQL-backed queue.

Seeded users (dev only): `admin@` (admin), `pm@` (project manager of ALPHA), `member@` / `ba@`
(members of ALPHA), `divmgr@` (division manager, summaries only), `outsider@` (manager of BETA, no
access to ALPHA) — all `@example.com`. Every user starts with the **mock** AI provider, so the full
workflow runs without any API key. To use OpenAI, open *Cài đặt AI*, choose OpenAI, enter your key.

## Local development (without Docker)

Prerequisites: Python 3.12+, Node 22, PostgreSQL 16.

```bash
# Database
createuser -P memohub            # password: memohub
createdb -O memohub memohub
createdb -O memohub memohub_test  # for tests

# Backend
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env           # set SECRET_ENCRYPTION_KEYS (python -m app.cli generate-key)
alembic upgrade head
python -m app.cli seed
EMBEDDED_WORKER=true uvicorn app.main:app --reload --port 8000   # or run `python -m app.worker` separately

# Frontend (new terminal)
cd frontend
npm ci
BACKEND_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

API docs: <http://localhost:8000/api/docs> (OpenAPI JSON at `/api/v1/openapi.json`).

## Primary workflow

1. **Dự án** → *Tạo dự án* (PM/admin).
2. **Cuộc họp mới** → title, project, date/timezone, participants, languages, platform.
3. **Transcript & bản dịch** → upload `samples/ja_client_meeting.vtt` (or paste text).
4. **Dịch toàn bộ** → translations appear beside the original (async job with progress).
5. **Tạo biên bản AI** → structured memo (A–J) with source links on every decision/action/issue/risk.
6. Edit, confirm/reject AI items, **Gửi duyệt**, then a project manager **Phê duyệt**.
7. **Xuất** Markdown / HTML (print to PDF) / JSON. Track actions in **Theo dõi công việc**.

Replay demo: create a meeting without a transcript → tab **Phát lại (Demo)** → paste text → start.

## Environment variables

See [`.env.example`](.env.example) for the full annotated list. Most important:

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enforces secure settings at startup |
| `DATABASE_URL` | local memohub | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `AUTH_MODE` | `oidc` | `dev` (seeded-user picker, refused in production) or `oidc` |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_REDIRECT_URI` | — | Microsoft Entra ID (or other OIDC) |
| `SESSION_COOKIE_SECURE` | `true` | set `false` only for local HTTP |
| `SECRET_ENCRYPTION_KEYS` | empty | AES-256-GCM keyring for user API keys; empty = keys refused |
| `ALLOW_PERSISTENT_API_KEYS` | `true` | enables the "remember key" option (needs keyring) |
| `ENABLE_MOCK_PROVIDER` | `true` | deterministic offline provider; must be `false` in production |
| `EMBEDDED_WORKER` | `false` | run the job worker inside the API process |
| `AI_RATE_LIMIT_PER_MINUTE` | `20` | per user, AI endpoints |
| `MAX_UPLOAD_BYTES` | `2097152` | transcript upload limit |
| `TRANSLATION_CHUNK_MAX_ENTRIES` / `_CHARS` | `20` / `6000` | bounded translation requests |
| `MEMO_MAX_TRANSCRIPT_CHARS` | `120000` | single-pass memo limit |
| `PROVIDER_CATALOG_PATH` | `app/ai/catalog.json` | providers, models, prices, capabilities |
| `ALLOW_PRIVATE_PROVIDER_URLS` | `false` | allow `http://localhost` LLM servers (dev only) |
| `BACKEND_URL` (frontend) | `http://localhost:8000` | proxy target, server-side only (build-time for `next build`) |

## Database migrations

```bash
cd backend
alembic upgrade head        # apply
alembic downgrade -1        # roll back one step
alembic check               # models vs migrations drift check
```

## Tests

```bash
# Backend (needs PostgreSQL; uses memohub_test, recreated per run)
cd backend && pytest                 # TEST_DATABASE_URL overrides the default
ruff check app tests alembic && mypy app && pip-audit --skip-editable

# Frontend
cd frontend && npm run lint && npm run typecheck && npm test && npm run build

# End-to-end (requires the stack running on :3000 with AUTH_MODE=dev and the mock provider)
cd frontend && npx playwright test   # PW_CHROMIUM_PATH=/path/to/chromium to use a preinstalled browser
```

External AI providers are always mocked in automated tests; no test makes a paid API call.
Current results: see [`docs/feature-matrix.md`](docs/feature-matrix.md#verification-run-this-delivery).

## Operations

* `python -m app.cli generate-key | rotate-keys | retention | seed`
* Health: `GET /api/v1/health/live`, `/api/v1/health/ready`; admin console → *Tình trạng hệ thống*.
* Logs: JSON lines with IDs/counts only (no transcript text, no keys).
* Key rotation and data flows to AI providers: [`docs/security.md`](docs/security.md).

## Production checklist

`ENVIRONMENT=production`, `AUTH_MODE=oidc` with Entra ID settings, `SESSION_COOKIE_SECURE=true`,
explicit `TRUSTED_HOSTS`, `ENABLE_MOCK_PROVIDER=false`, keyring from a secret manager, TLS at the
ingress, `api` not publicly exposed, `SEED_DEMO_DATA=false`. Startup refuses insecure combinations.
