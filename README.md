# Memo Hub — AI Meeting Translator & Memo

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Ứng dụng web tự cài đặt (self-hosted) để **phụ đề, phiên dịch trực tiếp và viết biên bản họp bằng AI**
cho các cuộc họp Nhật / Việt / Anh. Dữ liệu nằm trên máy chủ của bạn; bạn dùng API key OpenAI
(và tùy chọn Soniox) của chính mình.

*Self-hosted web app for live captions, live interpretation and AI meeting minutes in Japanese /
Vietnamese / English meetings. Your data stays on your server; you bring your own OpenAI (and
optionally Soniox) API key. English summary: [below](#english).*

## Tính năng

- **Thu âm trực tiếp trên trình duyệt**: micro và/hoặc âm thanh cuộc họp (chia sẻ tab/màn hình kèm âm
  thanh từ Teams, Zoom, Meet…). Tự nhận biết ngôn ngữ, tách người nói.
- **3 chế độ**: phụ đề chính xác theo câu · phụ đề hiện từng chữ · **phiên dịch trực tiếp**
  (OpenAI `gpt-realtime-translate`, luôn lưu kèm lời gốc để đối chiếu) · hoặc **Soniox** (rẻ hơn nhiều).
- **Nhập transcript** có sẵn (VTT, SRT, TXT, JSON) và dịch toàn bộ.
- **Biên bản AI có cấu trúc**: quyết định, việc cần làm, vấn đề, rủi ro — mỗi mục dẫn về đúng dòng
  transcript gốc. Sửa, xác nhận, gửi duyệt, phê duyệt, xuất Markdown / HTML (in PDF) / JSON.
- **Theo dõi công việc** theo dự án, bảng thuật ngữ riêng cho từng dự án.
- Giao diện tiếng Việt, chế độ sáng/tối.

## Cài đặt — chọn một cách

Cần: **Docker Desktop** (Windows / macOS / Linux) và **Chrome hoặc Edge** để thu âm.

| Bạn muốn | Lệnh | Đăng nhập | API key |
|---|---|---|---|
| **Dùng thử / dùng một mình** trên máy mình | `./start.sh` (Windows: `.\start.ps1`) | Chọn người dùng mẫu | Mỗi người tự nhập trong *Cài đặt AI* (chưa có thì chạy MOCK) |
| **Site cho đồng nghiệp trong mạng công ty** | `.\start-lan.cmd` (Windows) | Không cần | Dùng chung key của người cài, lưu trên máy chủ |
| **Triển khai chính thức** có đăng nhập công ty | Docker Compose + OIDC | Microsoft Entra ID / OIDC | Mỗi người, hoặc key chung của máy chủ |

**1. Dùng thử trên máy mình.** Trong thư mục dự án chạy `./start.sh` (dừng: `./start.sh stop`).
Trên Windows: `.\start.ps1`; nếu bị chặn script thì `powershell -ExecutionPolicy Bypass -File .\start.ps1`.
Script tự tạo `.env` kèm khóa mã hóa, build, khởi động và mở <http://localhost:3000>. Vào *Cài đặt AI*
→ thêm OpenAI kèm API key. Đây là chế độ **phát triển** (đăng nhập không mật khẩu): chỉ dùng trên máy
mình, không mở cho người khác.

**2. Site trong mạng nội bộ** (máy bạn làm máy chủ, đồng nghiệp mở `https://<IP-máy-bạn>`):
`.\start-lan.cmd` — lần đầu hỏi API key, tự dựng HTTPS trên IP nội bộ và mở firewall. Hướng dẫn đầy đủ,
vận hành và sao lưu: [docs/deploy-lan-vi.md](docs/deploy-lan-vi.md). Script hiện chỉ có cho Windows; trên
macOS/Linux có thể dùng `docker compose --profile lan` với file env tương tự (xem script).

**3. Triển khai chính thức**: xem [Quick start](#quick-start-docker-compose),
[biến môi trường](#environment-variables) và [production checklist](#production-checklist).

> [!WARNING]
> **Bảo mật — đọc trước khi cài cho người khác dùng**
> - Chế độ **không đăng nhập** (`start-lan`, `AUTH_MODE=shared`) chỉ dành cho **mạng nội bộ tin cậy**.
>   **Tuyệt đối không mở ra Internet**: ai truy cập được là xem/sửa được **mọi** dự án, biên bản và tiêu
>   tiền vào API key của bạn. Mọi người dùng chung một tài khoản nên nhật ký không biết ai đã sửa gì.
>   Cần phân quyền / audit theo từng người → dùng `AUTH_MODE=oidc`.
> - Chế độ `./start.sh` (đăng nhập chọn người dùng mẫu) chỉ để thử trên máy mình.
> - Âm thanh và nội dung họp được gửi tới OpenAI / Soniox để xử lý. Kiểm tra chính sách bảo mật của
>   công ty và hợp đồng với khách hàng (NDA) trước khi dùng cho cuộc họp có dữ liệu nhạy cảm.
> - API key chỉ nằm trên máy chủ (mã hóa AES-256-GCM khi lưu trong DB); trình duyệt chỉ nhận khóa tạm
>   thời vài phút. Chi tiết: [docs/security.md](docs/security.md).

## Chi phí (tính vào API key của bạn)

Ước tính theo bảng giá công bố, tham khảo:

| Chế độ | Khoảng |
|---|---|
| Phiên dịch trực tiếp OpenAI (`gpt-realtime-translate` + ghi lời gốc) | ~ $3 / giờ họp |
| Phụ đề OpenAI (không phiên dịch) | ít hơn đáng kể; dịch từng câu bằng `SERVER_AI_MODEL` |
| Soniox (phụ đề + dịch) | ~ $0.18 / giờ họp |
| Biên bản AI | vài cent / cuộc họp |

Hãy **đặt trần chi tiêu** trong trang quản lý của OpenAI (Billing → Usage limits) và Soniox. Ứng dụng
chỉ giới hạn số lượt mỗi phút, không giới hạn tiền. Màn hình *Chi phí & sử dụng AI* hiển thị ước tính.

## Trạng thái & giới hạn

- **Đã dùng thật**: thu âm trên trình duyệt, phụ đề, phiên dịch trực tiếp OpenAI, nhập transcript, biên
  bản AI, site mạng nội bộ trên Windows.
- **Chưa kiểm chứng với tài khoản thật**: tích hợp Teams / Zoom / Google Meet qua OAuth (mới thử với máy
  chủ giả lập, hiển thị nhãn **SANDBOX**; Teams cần quản trị viên tenant cấp quyền). Cách thu âm trên
  trình duyệt dùng được với mọi nền tảng họp mà không cần tích hợp.
- Thu âm cần **Chrome / Edge** trên máy tính; Safari / Firefox có thể không chia sẻ được âm thanh tab.
- Một máy chủ, một database PostgreSQL: hãy sao lưu định kỳ (`.\start-lan.cmd backup`).

Danh sách đầy đủ: [docs/feature-matrix.md](docs/feature-matrix.md).

## Báo lỗi & bảo mật

- Lỗi / đề xuất: mở [GitHub Issue](../../issues).
- **Lỗ hổng bảo mật: đừng đăng công khai** — dùng *Security → Report a vulnerability* (GitHub private
  vulnerability reporting) của repo này.
- Khi báo lỗi, **không dán API key, transcript hay nội dung họp** vào issue.

## English

**Memo Hub** is a self-hosted web app for meetings in Japanese, Vietnamese and English: browser-based
capture of the microphone and/or the meeting's tab audio, live captions with automatic language
detection, live interpretation (OpenAI `gpt-realtime-translate`, with the original words always kept
for audit) or Soniox, transcript import, and structured AI minutes (decisions, actions, issues, risks)
linked back to the transcript, with review/approval and export. The UI is in Vietnamese.

- **Try it locally:** install Docker Desktop, run `./start.sh` (Windows: `.\start.ps1`), open
  <http://localhost:3000>, add your OpenAI key under *Cài đặt AI* (AI settings). Dev sign-in, local use only.
- **Company-network site without sign-in** (Windows): `.\start-lan.cmd` — HTTPS on the machine's LAN IP,
  shared server-side API key. **Private networks only — never expose it to the Internet.**
- **Production:** `AUTH_MODE=oidc` (e.g. Microsoft Entra ID); see the sections below.
- Your API keys pay for usage (roughly $3/meeting-hour for OpenAI live interpretation, ~$0.18 for
  Soniox). Set spending limits with the providers. Teams/Zoom/Meet OAuth integrations are not yet
  verified against real accounts.
- Licensed under the [MIT License](LICENSE).

---

# Developer reference

Internal architecture: FastAPI + SQLAlchemy 2 + Alembic API and worker (Python 3.12), Next.js 16 App
Router UI (TypeScript strict, Tailwind v4), PostgreSQL 16 (also used as the job queue; no Redis).

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
| `deploy/` | Caddy config for the company-network (LAN) HTTPS site |
| `samples/` | Sample transcripts (fictional): `ja_client_meeting.vtt`, `vi_internal_meeting.txt`, `en_steering_meeting.srt`, `sample_transcript.json`, `prompt_injection_test.txt` |
| `docs/` | [architecture](docs/architecture.md) · [data model](docs/data-model.md) · [security](docs/security.md) · [audio capture](docs/audio-capture.md) · [LAN deploy](docs/deploy-lan-vi.md) · [API contract](docs/api-contract.md) · [OpenAPI](docs/openapi.json) · [WS2 contract](docs/workstream-2-integration-contract.md) · [WS2 plan](docs/workstream-2-plan.md) · integrations: [Teams](docs/integrations/teams.md), [Zoom](docs/integrations/zoom.md), [Google Meet](docs/integrations/google-meet.md) · [feature matrix, limitations, backlog](docs/feature-matrix.md) |
| `docker-compose.yml` | db, migrate (+ seed), api, worker, web; profile `lan` adds Caddy (HTTPS) |
| `start.sh` / `start.ps1` | one-command local start · `start-lan.cmd` / `start-lan.ps1`: company-network site |

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
| `AUTH_MODE` | `oidc` | `dev` (seeded-user picker, refused in production), `oidc`, or `shared` (no sign-in, one team account, private network only) |
| `OPENAI_API_KEY` / `SONIOX_API_KEY` | empty | server-wide AI keys, never sent to browsers; `OPENAI_API_KEY` required for `shared` |
| `SERVER_AI_MODEL` | `gpt-4.1` | translation / memo model used with the server key |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_REDIRECT_URI` | — | Microsoft Entra ID (or other OIDC) |
| `SESSION_COOKIE_SECURE` | `true` | set `false` only for local HTTP |
| `SECRET_ENCRYPTION_KEYS` | empty | AES-256-GCM keyring for user API keys; empty = keys refused |
| `ALLOW_PERSISTENT_API_KEYS` | `true` | enables the "remember key" option (needs keyring) |
| `ENABLE_MOCK_PROVIDER` | `true` | deterministic offline provider; must be `false` in production |
| `EMBEDDED_WORKER` | `false` | run the job worker inside the API process |
| `AI_RATE_LIMIT_PER_MINUTE` | `20` | per user (per browser session in `shared` mode), AI endpoints |
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

For a site without sign-in on a private network, `AUTH_MODE=shared` replaces OIDC and requires
`OPENAI_API_KEY`; `start-lan.ps1` generates such a configuration (`.env.lan`).

## License

[MIT](LICENSE) © 2026 MinhHung-PM. Third-party dependencies keep their own licenses (MIT / Apache-2.0 / BSD).
