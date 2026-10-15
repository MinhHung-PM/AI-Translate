# Feature matrix, verification results, limitations and backlog

Legend: **Tested** = implemented and covered by passing automated tests · **Implemented** = in code,
exercised manually or partially, no dedicated automated test · **Blocked** = needs credentials or
permissions not available · **Deferred** = out of scope for Workstream 1.

## Feature matrix

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Core workflow | Project → Meeting → Import → Translate → Memo → Review → Approve → Confirm → Export | **Tested** | `tests/test_workflow.py`, `e2e/workflow.spec.ts` (also against Docker Compose) |
| Auth | Dev login (disabled in prod), server sessions, logout | **Tested** | `test_security.py` |
| Auth | OIDC / Microsoft Entra ID login | Implemented / **Blocked** (live test) | needs tenant, client id/secret |
| AuthZ | Roles, project boundaries, division manager transcript flag, admin no-content | **Tested** | `test_security.py` |
| Screen 1 | Dashboard (real data, filters, empty states) | **Tested** (API) / Implemented (UI) | `test_workflow.py`, screenshots |
| Screen 2 | New meeting form, platform status "Integration not configured" | **Tested** | E2E |
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
| WS2 | Teams / Zoom / Meet live audio, Graph transcripts, auto-join, outbound voice, Jira/ADO/SharePoint | **Deferred** | `workstream-2-integration-contract.md` |

## Verification run (this delivery)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && pytest` | **125 passed** |
| Lint / format | `ruff check app tests alembic`, `ruff format --check` | clean |
| Types | `mypy app` (strict) | no issues (69 files) |
| Migrations | `alembic upgrade head` / `downgrade base` / `alembic check` | ok, no drift |
| Python deps | `pip-audit` | no known vulnerabilities |
| Frontend | `npm run lint`, `npm run typecheck`, `npm test` (7), `npm run build` | clean / pass |
| Node deps | `npm audit --omit=dev` | 0 vulnerabilities (5 high in dev-only ESLint toolchain, see risks) |
| E2E | `npx playwright test` (3 specs) | **3 passed** against local servers and against Docker Compose |

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

## Prioritized Workstream 2 backlog

1. Microsoft Teams: Entra app + Graph transcript retrieval (post-meeting), mapped to meetings via join URL; change-notification webhook → `ingest_event`.
2. Production OIDC hardening: test with Entra tenant, group → role mapping, session revocation on IdP logout.
3. Zoom RTMS connector (live transcript) + cloud-recording VTT fetch.
4. Google Meet transcripts via Meet REST API / Workspace Events.
5. Hierarchical (map-reduce) memo generation for long meetings.
6. Redis-backed rate limiter and job notifications (SSE/WebSocket) for multi-replica deployments.
7. Live interim captions UX (show `is_final=false` without persisting).
8. Additional providers (Azure OpenAI, Anthropic, Gemini) via the adapter interface; per-project provider policy.
9. Jira / Azure DevOps action-item sync; SharePoint export of approved memos.
10. DOCX/PDF server-side export; English/Japanese UI locales; nonce-based CSP.
11. Outbound translated voice (TTS) and automatic meeting joining (bot) — requires platform approvals.
