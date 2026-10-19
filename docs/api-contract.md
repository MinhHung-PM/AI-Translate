# API contract (v1)

Base path `/api/v1`. Machine-readable spec: [`docs/openapi.json`](openapi.json) (also served live at
`/api/v1/openapi.json`; Swagger UI at `/api/docs`).

## Conventions

* JSON in/out (except multipart uploads and file exports). Times are ISO-8601 with offsets (UTC stored).
* Auth: session cookie `memohub_session` (HttpOnly). All non-GET requests require header
  `X-CSRF-Token: <csrf_token from GET /auth/me>`.
* Pagination: `?page=1&page_size=20` (max 100; transcript up to 500) → `{items, total, page, page_size}`.
* Errors: `{"error": {"code": "...", "message": "...", "details": {...}}}` with codes
  `not_authenticated` 401, `forbidden` 403, `not_found` 404, `conflict` 409, `payload_too_large` 413,
  `validation_failed` 422, `rate_limited` 429 (`details.retry_after_seconds`), `provider_not_configured` 409,
  `internal_error` 500.
* Long-running work returns **202** with a `Job`; poll `GET /jobs/{id}` (`queued → running → succeeded|failed`,
  `progress_done/progress_total`, `error_code/error_message`, `result`).

## Endpoints

| Area | Method & path | Notes |
|---|---|---|
| Auth | `GET /auth/me` | user, csrf_token, auth_mode, feature flags |
| | `POST /auth/logout` | deletes session and session-only keys |
| | `GET /auth/dev/users`, `POST /auth/dev/login` | only when `AUTH_MODE=dev` (404 otherwise) |
| | `GET /auth/oidc/login`, `GET /auth/oidc/callback` | OIDC code flow + PKCE |
| Users | `GET/PATCH /users/me` | |
| Projects | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` | create: PM/admin; delete: admin (soft) |
| | `GET/POST /projects/{id}/members`, `DELETE /projects/{id}/members/{user_id}` | |
| Glossary | `GET/POST /projects/{id}/glossary`, `PATCH/DELETE /projects/{id}/glossary/{entry_id}` | manage = project manager |
| Meetings / history | `GET /meetings` | filters `q, project_id, date_from, date_to, status, memo_status, platform, sort` |
| | `POST /meetings`, `GET/PATCH/DELETE /meetings/{id}` | delete = soft |
| | `GET /meetings/{id}/export?format=md\|csv\|json` | transcript + translations (transcript access required) |
| Transcript | `POST /meetings/{id}/transcript/upload` | multipart `file` (.txt/.srt/.vtt/.json), `source_language?`, `replace?` |
| | `POST /meetings/{id}/transcript/text` | `{text, format?, source_language?, replace?}` |
| | `GET /meetings/{id}/transcript` | `target_language, q, status, page, page_size`; entries with translation |
| | `GET /meetings/{id}/transcript/stats`, `GET /meetings/{id}/transcript/imports` | |
| | `PATCH /transcript-entries/{id}` | correct source text (original kept in metadata) |
| | `PUT /transcript-entries/{id}/translation` | user correction, marks `is_user_edited` |
| Translation | `POST /meetings/{id}/translations` → 202 Job | `{target_language?, entry_ids?, only_failed?, force?}` (rate-limited) |
| Live / replay | `POST /meetings/{id}/replay` → 202 LiveSession | multipart `file` or `text`, `interval_seconds`, `translate` — **demo** |
| | `GET /meetings/{id}/live?after_sequence=` | polling feed (session + entries) |
| | `POST /live-sessions/{id}/stop` | |
| Memo | `GET /meetings/{id}/memo` | full structured memo incl. items, sources, permissions |
| | `POST /meetings/{id}/memo/generate` → 202 Job | rate-limited; 409 if approved/generating |
| | `PUT /memos/{id}` | narrative sections (summary, discussion, open_questions, next_meeting, pm_view) |
| | `POST /memos/{id}/submit\|approve\|reject\|reopen` | approve/reject/reopen: project manager |
| | `GET /memos/{id}/export?format=md\|html\|json` | approved memos only |
| Items | `POST /memos/{id}/decisions\|action-items\|issues\|risks` | human-created items are `confirmed` |
| | `PATCH/DELETE /decisions/{id}`, `/action-items/{id}`, `/issues/{id}`, `/risks/{id}` | `verification_status` confirm/reject; action owners may update `status` |
| Action tracker | `GET /action-items` | `project_id, meeting_id, status[], priority[], verification[], owner, mine, due_from, due_to, overdue, include_rejected` |
| Jobs | `GET /jobs/{id}`, `GET /meetings/{id}/jobs` | |
| AI providers | `GET /providers` | catalog, capabilities, prices, storage flags |
| | `GET/PUT /providers/configs`, `DELETE /providers/configs/{id}` | key write-only |
| | `POST /providers/configs/{id}/default`, `DELETE /providers/configs/{id}/key`, `POST /providers/configs/{id}/test` | |
| Usage | `GET /usage/summary` | totals, by model/operation/project/meeting, `cost_note` |
| Dashboard | `GET /dashboard` | filters `project_id, date_from, date_to, meeting_status, memo_status, owner` |
| Connectors | `GET /connectors` | per-user platform status summary for the meeting form (derived from the integration view) |
| Platform integrations (WS2) | `GET /integrations`, `GET /integrations/{provider}` | `ConnectionView`: display status, capabilities, sandbox flag, safe error category — never tokens |
| | `POST /integrations/{provider}/connect` | → `{authorization_url}`; server-side state + PKCE |
| | `GET /integrations/{provider}/oauth/callback` | requires the same login session; redirects to `/integrations?provider=&result=connected\|error&category=` |
| | `POST /integrations/{provider}/test` (rate-limited), `DELETE /integrations/{provider}` | disconnect revokes (best effort) and deletes tokens |
| | `GET /integrations/{provider}/meetings`, `GET /integrations/{provider}/diagnostics` | list needs capability `list_meetings`; diagnostics = timestamps, categories, recent jobs/events |
| Meeting source (WS2) | `GET/POST/DELETE /meetings/{id}/external-source` | link `{provider, reference}` (join URL / id / code); 409 if already linked elsewhere (other meeting not revealed) |
| | `POST /meetings/{id}/external-source/fetch` → 202 Job | `fetch_transcript` job with bounded backoff; 409 when the capability is not available |
| | `POST /meetings/{id}/external-source/live/start\|stop` | arms/stops provider live ingestion (Zoom RTMS only, when configured) |
| | `POST /jobs/{id}/retry` | retry a failed retrieval job |
| Live audio | `POST /meetings/{id}/audio-sessions` | `{sources[{id,kind,label,single_speaker}], translate, consent_confirmed, mode?, stt_provider? ("openai" default \| "soniox"; Soniox needs mode streaming/interpret), language_detection? ("auto" default \| "listed"), languages? (listed only), noise_suppression?, caption_latency?}`; one active live session per meeting |
| | `POST /audio-sessions/{id}/chunks` | multipart `source_id, chunk_seq, offset_ms, file` (16-bit mono WAV ≤ 30 s); synchronous → recognised entries; idempotent per `(source_id, chunk_seq)`; creator only; rate-limited |
| | `POST /audio-sessions/{id}/realtime-token` | `{source_id}` → ephemeral OpenAI Realtime client secret (streaming / interpret mode, creator only, rate-limited); `kind: "translation"` + `calls_url` `/v1/realtime/translations/calls` + `target_language` in interpret mode; Soniox sessions: `kind: "soniox"`, `client_secret` = single-use temporary key, `calls_url` = Soniox WebSocket, `session_config` = first WebSocket message (without `api_key`) |
| | `POST /audio-sessions/{id}/segments` | `{source_id, item_id, text, offset_ms, duration_ms?, model?, speaker?, translated_text?}` final streaming utterance → stored + translated; idempotent per item. Interpret mode: `translated_text` (OpenAI's live translation) is stored as-is; ignored in other modes |
| | `GET /audio-sessions/{id}`, `POST /audio-sessions/{id}/stop`, `PATCH /audio-sessions/{id}/speakers/{key}` | speakers (no audio returned); stop deletes voice references; rename relabels existing entries |
| Webhooks (WS2) | `POST /integrations/zoom/webhook` | unauthenticated; HMAC signature + timestamp tolerance, size limit, IP rate limit, replay dedup, URL validation |

Integration errors use code `integration_{category}` (e.g. `integration_admin_approval_required`,
`integration_not_connected`, `integration_invalid_signature`); see
[`workstream-2-integration-contract.md`](workstream-2-integration-contract.md).
| Admin | `GET/POST /admin/users`, `PATCH /admin/users/{id}`, `GET /admin/users/lookup` | |
| | `GET/POST /admin/divisions`, `GET/PUT /admin/division-assignments`, `DELETE /admin/division-assignments/{id}` | |
| | `GET /admin/audit-events`, `GET /admin/health`, `POST /admin/retention/run` | |
| Health | `GET /health/live`, `GET /health/ready` | unauthenticated |

## JSON transcript import schema

```json
{
  "schema_version": "1.0",
  "language": "ja",
  "entries": [
    { "speaker": "田中", "start_ms": 0, "end_ms": 4000, "text": "…", "language": "ja", "metadata": {} }
  ]
}
```

Only `text` is required per entry; unknown keys are rejected; `end_ms >= start_ms`.
