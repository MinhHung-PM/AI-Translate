# AI Meeting Translator & Memo Hub — Product Core + Meeting Platform Integrations

Internal web application for an IT outsourcing company serving Japanese clients. Project managers,
BrSEs, BAs, tech leads and division managers import meeting transcripts (Japanese / Vietnamese /
English), translate them, generate structured AI meeting minutes, review and approve them, and track
decisions, action items, issues and risks — each traceable to the original transcript line.

> **Platform integrations (Workstream 2).** Teams, Zoom and Google Meet connect via OAuth under
> *Tích hợp nền tảng*; a meeting can be linked to a platform meeting to retrieve its authorized
> post-meeting transcript, and Zoom RTMS can feed the live view. **None of this has been verified against a
> real Microsoft, Zoom or Google account yet** — it is tested against mocks and a fake provider server
> (shown as **SANDBOX** in the UI). Teams transcripts need tenant admin consent; Teams/Meet live is not
> supported. Transcript file import always works. Status per provider: [`docs/integrations/`](docs/integrations/)
> · plan: [`docs/workstream-2-plan.md`](docs/workstream-2-plan.md). **Try it without accounts:**
> `./start.sh sandbox` (fake providers, dev only) — guide: [`docs/integrations/sandbox-vi.md`](docs/integrations/sandbox-vi.md). The replay view remains an explicitly
> labelled **demo**.

## Contents

| Path | |
|---|---|
| `backend/` | FastAPI + SQLAlchemy 2 + Alembic API and worker (Python 3.12) |
| `frontend/` | Next.js 16 App Router UI (TypeScript strict, Tailwind v4), Vietnamese interface |
| `samples/` | Sample transcripts: `ja_client_meeting.vtt`, `vi_internal_meeting.txt`, `en_steering_meeting.srt`, `sample_transcript.json`, `prompt_injection_test.txt` |
| `docs/` | [architecture](docs/architecture.md) · [data model](docs/data-model.md) · [security](docs/security.md) · [API contract](docs/api-contract.md) · [OpenAPI](docs/openapi.json) · [WS2 contract](docs/workstream-2-integration-contract.md) · [WS2 plan](docs/workstream-2-plan.md) · integrations: [Teams](docs/integrations/teams.md), [Zoom](docs/integrations/zoom.md), [Google Meet](docs/integrations/google-meet.md) · [feature matrix, limitations, backlog](docs/feature-matrix.md) |
| `docker-compose.yml` | db, migrate (+ seed), api, worker, web |

## Chạy nhanh bằng một lệnh / One-command start

Cần cài và mở **Docker Desktop**, sau đó trong thư mục dự án:

* macOS / Linux: `./start.sh` (dừng: `./start.sh stop`)
* Windows (PowerShell): `.\start.ps1` (dừng: `.\start.ps1 stop`) — nếu bị chặn script:
  `powershell -ExecutionPolicy Bypass -File .\start.ps1`

Script tự tạo `.env` kèm khóa mã hóa, build, khởi động và mở <http://localhost:3000>.

**Thu âm & dịch trực tiếp:** mở một cuộc họp → *Trực tiếp / Phát lại* → *Thu âm trực tiếp*, chọn micro và/hoặc
âm thanh cuộc họp (chia sẻ màn hình/tab kèm âm thanh) → hệ thống nhận dạng, tách người nói và dịch từng câu.
Cần thêm OpenAI (kèm API key) trong *Cài đặt AI*; nếu chưa có sẽ chạy MOCK. Chi tiết:
[`docs/audio-capture.md`](docs/audio-capture.md).

**Thử tích hợp Teams / Zoom / Google Meet mà không cần tài khoản thật:** `./start.sh sandbox`
(Windows: `.\start.ps1 sandbox`). Lệnh này chạy thêm máy chủ giả lập, gắn nhãn SANDBOX và chỉ dùng để
thử nghiệm. Hướng dẫn từng bước: [`docs/integrations/sandbox-vi.md`](docs/integrations/sandbox-vi.md).

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
| `PUBLIC_BASE_URL` | `http://localhost:3000` | external URL; OAuth redirect = `{PUBLIC_BASE_URL}/api/v1/integrations/{provider}/oauth/callback` |
| `TEAMS_*`, `ZOOM_*`, `GOOGLE_*` | empty | platform OAuth apps — see [`.env.example`](.env.example) and `docs/integrations/` |
| `INTEGRATION_ENDPOINT_OVERRIDES` | empty | **dev/test only**: fake provider server; marks connections SANDBOX, refused in production |
| `INTEGRATION_BROWSER_ENDPOINT_OVERRIDES` | empty | **dev/test only**: browser-facing address of the fake server's authorize page (Docker sandbox) |
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

# End-to-end (requires the stack running on :3000 with AUTH_MODE=dev and the mock provider).
# Workstream 2 specs also need the fake provider server (DEV/TEST ONLY) and the API started with:
#   cd backend && python -m tests.fakes.server --port 9100   # prints the INTEGRATION_ENDPOINT_OVERRIDES value
#   TEAMS_CLIENT_ID=teams-client TEAMS_CLIENT_SECRET=fake-secret ZOOM_CLIENT_ID=zoom-client \
#   ZOOM_CLIENT_SECRET=fake-secret ZOOM_WEBHOOK_SECRET_TOKEN=zoom-webhook-secret \
#   GOOGLE_CLIENT_ID=google-client GOOGLE_CLIENT_SECRET=fake-secret \
#   INTEGRATION_ENDPOINT_OVERRIDES='{"teams":"http://127.0.0.1:9100/teams","zoom":"http://127.0.0.1:9100/zoom","google_meet":"http://127.0.0.1:9100/google"}'
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
