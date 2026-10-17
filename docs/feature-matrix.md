# Feature matrix, verification results, limitations and backlog

Legend: **Tested** = implemented and covered by passing automated tests · **Implemented** = in code,
exercised manually or partially, no dedicated automated test · **Blocked** = needs credentials or
permissions not available · **Deferred** = out of scope. For Workstream 2 rows: **Mocked** = implemented
and tested only against mocked providers / the fake provider server (never a real Microsoft, Zoom or Google
endpoint) · **Admin approval** = works only after tenant/admin approval · **Not supported** = not offered.

## Feature matrix

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Core workflow | Project → Meeting → Import → Translate → Memo → Review → Approve → Confirm → Export | **Tested** | `tests/test_workflow.py`, `e2e/workflow.spec.ts` (also against Docker Compose) |
| Auth | Dev login (disabled in prod), server sessions, logout | **Tested** | `test_security.py` |
| Auth | OIDC / Microsoft Entra ID login | Implemented / **Blocked** (live test) | needs tenant, client id/secret |
| AuthZ | Roles, project boundaries, division manager transcript flag, admin no-content | **Tested** | `test_security.py` |
| Screen 1 | Dashboard (real data, filters, empty states) | **Tested** (API) / Implemented (UI) | `test_workflow.py`, screenshots |
| Screen 2 | New meeting form, truthful platform status (not configured / not linked / available) | **Tested** | E2E, `test_platform_status_is_truthful` |
| Screen 3 | TXT/SRT/VTT/JSON/plain import, validation, normalization, side-by-side view, search, status filter, editing | **Tested** | `test_unit_transcripts.py`, `test_integration.py`, E2E |
| Screen 3 | Replay (demo) mode, clearly labelled | **Tested** | `test_integration.py`, E2E |
| Screen 4 | Full/selected translation, retry failed, chunking, glossary, ambiguity notes, user corrections preserved | **Tested** | `test_integration.py`, `test_security.py`, `test_unit_ai.py` |
| Screen 5 | Structured memo A–J, edit narrative and items, confirm/reject, owners/deadlines, source references, submit/approve/reject/reopen | **Tested** (API) + E2E main path | `test_workflow.py`, E2E |
| Screen 5 | Export Markdown / HTML (print-to-PDF) / JSON, approved only | **Tested** | `test_workflow.py`, E2E (Markdown download) |
| Screen 6 | Action tracker: filters, overdue, links, status updates, owner-only status | **Tested** | `test_integration.py`, E2E |
| Screen 7 | History: search, filters, DB pagination, record export | **Tested** | `test_integration.py`, E2E |
| Screen 8 | Provider settings, model selection, test connection, capabilities, remove key, remember option | **Tested** (API, mock); UI Implemented | `test_security.py`, `test_integration.py` |
| AI | Provider abstraction (mock, OpenAI, OpenAI-compatible) | **Tested** with mocked HTTP | `test_unit_ai.py` |
| AI | Real OpenAI calls | **Blocked** (no API key in this environment; CI must not use paid calls) | optional manual check |
| AI | Strict output validation + bounded retry, no fabricated fallback | **Tested** | `test_unit_ai.py`, `test_security.py` |
| AI | Prompt-injection handling | **Tested** | `test_unit_ai.py`, `test_security.py` |
| Dates | Conservative relative-deadline resolution (ja/vi/en) | **Tested** (16 cases) | `test_unit_ai.py` |
| Usage | Usage records, estimated cost, by model/project/meeting, failed requests | **Tested** | `test_workflow.py`, `test_security.py` |
| Security | CSRF, upload limits, SSRF guard, redaction, headers, rate limit, CSV-injection | **Tested** | `test_security.py`, `test_unit_ai.py` |
| Ops | Audit events, admin console (users, divisions, audit, health, retention) | **Tested** (API) / Implemented (UI) | `test_integration.py` |
| Ops | Retention purge, soft delete | **Tested** | `test_integration.py` |
| Ops | Migrations up/down | **Tested** | `test_integration.py`, `alembic check` |
| Ops | Docker Compose (db, migrate, api, worker, web) | **Verified** (see note) | E2E passed against containers |
| i18n | Vietnamese UI, typed dictionary for more locales | Implemented | — |
| WS2 framework | Connector contract, typed capabilities, canonical event, dedup/ordering, bounded retry, OAuth (state+PKCE, encrypted tokens, rotation, revoke) | **Tested** | `test_integrations_unit.py`, `test_integrations_security.py` |
| WS2 UI | `/integrations` cards + wizard + diagnostics, meeting source selector, provider-aware live view | **Tested** (E2E, sandbox) | `e2e/workstream2-integrations.spec.ts`, `permission-status.test.ts` |
| Teams | Transcript import (VTT) | **Tested** | WS1 tests |
| Teams | OAuth (delegated), list meetings, resolve join URL | **Mocked** | `test_teams_oauth_link_fetch_translate_memo` |
| Teams | Post-meeting transcript via Graph | **Mocked** · **Admin approval** (`OnlineMeetingTranscript.Read.All`) | `test_teams_*` |
| Teams | Live transcript / live audio | **Not supported** (needs application permission + media bot) | `test_teams_live_is_never_offered` |
| Zoom | OAuth, recordings list, post-meeting transcript, signed webhooks | **Mocked** | `test_zoom_*`, `test_webhook_signature_and_replay_protection`, browser E2E |
| Zoom | Live transcript (RTMS, official SDK) | **Mocked** · requires RTMS provisioning | `test_live_rtms_ingestion_end_to_end` |
| Google Meet | OAuth, conference records, post-meeting transcript entries + participants | **Mocked** | `test_google_meet_*` |
| Google Meet | Live transcript / live audio | **Not supported** (Media API preview, no transcripts) | `test_live_never_available_for_teams_and_meet_even_with_all_scopes` |
| WS2 | Real-provider verification (any platform) | **Blocked** — no tenant/account credentials | [`integrations/`](integrations/) |
| Live audio | Capture from this computer (microphones, system/tab audio) → VAD → speech-to-text with speaker separation → live translation | **Tested** with MOCK STT + mocked OpenAI HTTP; browser E2E with fake microphone · **not verified against real OpenAI** | `test_audio_capture.py`, `audio.test.ts`, `e2e/audio-capture.spec.ts`, [audio-capture.md](audio-capture.md) |
| Live audio | Live interpretation (`gpt-realtime-translate`): translated words stream while speaking, stored with OpenAI's translation | **Tested** with mocked OpenAI HTTP + fake WebRTC peer · **not verified against real OpenAI** · no glossary, no in-source diarization (OpenAI limits) | `test_interpret_*`, `translation-events.test.ts`, `e2e/audio-streaming.spec.ts` |
| Live audio | System audio via screen share on a real Windows machine | Implemented · **not automated** (browser picker) | manual |
| Later | Auto-join bots, outbound voice, Jira/ADO/SharePoint | **Deferred** | backlog |

## Verification run (this delivery)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && pytest` | **201 passed** (WS1 + 76 WS2) |
| Lint / format | `ruff check app tests alembic`, `ruff format --check` | clean |
| Types | `mypy app` (strict) | no issues (97 files) |
| Migrations | `alembic upgrade head` / `downgrade base` / `alembic check` | ok, no drift; 0002 up/down/up verified on a database with WS1 data |
| Python deps | `pip-audit` | no known vulnerabilities |
| Frontend | `npm run lint`, `npm run typecheck`, `npm test` (9), `npm run build` | clean / pass |
| Node deps | `npm audit --omit=dev` | 0 vulnerabilities (5 high in dev-only ESLint toolchain, see risks) |
| E2E | `npx playwright test` (5 tests) | **5 passed** (twice in a row) against local servers + fake provider server; WS1's 3 tests also passed earlier against Docker Compose |

Docker note: images were built from the committed Dockerfiles with this sandbox's HTTPS proxy and CA
injected into scratch copies (the sandbox blocks direct registry access from build containers and Docker
Hub returned 429). The committed `docker-compose.yml` was then run unmodified with `--no-build`.
A normal `docker compose up --build` on a developer machine needs no such changes.

## Known limitations and unresolved risks

1. **OIDC not verified against a real IdP** — code follows the Entra ID flow but needs a tenant to test.
2. **No live provider verified** — the OpenAI adapter is tested against mocked HTTP only.
3. **Rate limiter is per process** — with multiple API replicas use a shared store (Redis) behind the
   same `RateLimiter` interface.
4. **Single-pass memo generation** is bounded by `MEMO_MAX_TRANSCRIPT_CHARS` (120 000); longer meetings
   fail with a clear message instead of being silently truncated. Hierarchical summarization is backlog.
5. **Mock provider** output is heuristic and marked `[MOCK]`; it exists for development/demo/testing only
   and is refused in production.
6. **Language detection** is script-based (ja/vi/en only); mixed-language lines take the dominant script.
   Users can override per meeting/import.
7. **System-generated review notes** (e.g. "No explicit owner stated") are in English while the UI is
   Vietnamese; they should move to message codes rendered by the UI.
8. **Frontend CSP** allows `'unsafe-inline'` scripts (Next.js inline bootstrap). A nonce-based CSP via
   `proxy.ts` is backlog.
9. **Dev-only npm advisories**: `braces` via `eslint-config-next` (no non-breaking fix upstream);
   not shipped in the production image.
10. **Next.js 16 `<Activity>` navigation** keeps recently visited routes mounted but hidden; polling is
    effect-based so it pauses when hidden, but tests must scope selectors to visible elements.
11. **Session-only keys** are encrypted at rest in PostgreSQL for the session lifetime (needed so the
    separate worker can use them); they are deleted at logout/expiry. A pure in-memory store would
    require the embedded worker only.
12. **Translation context** uses only two preceding lines; discourse-level consistency across chunks
    relies on the glossary.

### Workstream 2

13. **No platform verified against a real provider.** Teams, Zoom and Google Meet are tested only with
    mocks built from official API references (docs sites were unreachable from the build environment;
    official GitHub sources were used). See `docs/integrations/*.md` → *Unresolved*.
14. **Teams post-meeting transcripts require admin consent**; without it the product degrades to import.
15. **Zoom scopes are configuration** (`ZOOM_SCOPES`) because exact granular names were not verifiable.
16. **Zoom RTMS is not lossless**: a dropped stream marks the session *interrupted*; missing segments come
    from the post-meeting transcript.
17. **A platform meeting can be linked to only one hub meeting** (prevents duplicate ingestion); a second
    team wanting the same transcript must import the file.
18. **Live updates are polled** (1 s); the realtime ingestion thread runs in the worker process — run a
    single worker for RTMS sessions or pin them (multi-worker coordination is backlog).
19. **Live audio diarization** depends on OpenAI `gpt-4o-transcribe-diarize` (≤ 4 known speakers per
    request; utterances < 2 s from new speakers stay unattributed). Quality for ja/vi not yet measured.

## Prioritized backlog (after Workstream 2)

1. Verify Teams, Zoom (incl. RTMS) and Google Meet against real tenants/accounts; record results in `docs/integrations/`.
2. Production OIDC hardening: test with Entra tenant, group → role mapping, session revocation on IdP logout.
3. Teams transcript change notifications (needs application permission + application access policy) and Google Workspace Events (Pub/Sub) instead of polling.
4. Multi-worker coordination for live sessions; SSE/WebSocket push instead of polling.
5. Hierarchical (map-reduce) memo generation for long meetings.
6. Redis-backed rate limiter and job notifications (SSE/WebSocket) for multi-replica deployments.
7. Live interim captions UX (show `is_final=false` without persisting).
8. Additional providers (Azure OpenAI, Anthropic, Gemini) via the adapter interface; per-project provider policy.
9. Jira / Azure DevOps action-item sync; SharePoint export of approved memos.
10. DOCX/PDF server-side export; English/Japanese UI locales; nonce-based CSP.
11. Outbound translated voice (TTS) and automatic meeting joining (bot) — requires platform approvals.
