# Security

Status column: **Implemented & tested** = covered by automated tests (`backend/tests/test_security.py`
unless noted); **Implemented** = in code, not covered by an automated test.

| # | Control | Implementation | Status |
|---|---|---|---|
| 1 | Server-side authentication | HttpOnly `SameSite=Lax` session cookie; server-side session rows store only SHA-256 of the token; `Secure` flag required in production | Implemented & tested |
| 2 | Authorization on every resource | `services/authz.py` (single policy); list endpoints filter by `accessible_project_ids`; out-of-scope resources return **404** to avoid disclosure | Implemented & tested |
| 3 | Sessions / OIDC | Dev login (refused in production); OIDC authorization-code flow with PKCE, state, nonce, JWKS-verified ID token (Entra `oid` as subject), JIT provisioning as `member` | Dev: tested. OIDC: implemented, **not tested against a live IdP** (no tenant/credentials) |
| 4 | CSRF | Per-session token; every non-GET request must send `X-CSRF-Token` (constant-time compare) | Implemented & tested |
| 5 | Input validation | Pydantic models with `extra="forbid"`, length limits, IANA timezone and aware-datetime checks, `http(s)` URLs only | Implemented & tested |
| 6 | Upload limits & content validation | `MAX_UPLOAD_BYTES` (2 MB) read-limited; extension allow-list; encoding detection; binary/NUL rejection; strict format parsers; entry/char limits | Implemented & tested |
| 7 | Path traversal / unsafe files | Uploads are parsed in memory and never written to disk; only a sanitized basename is stored | Implemented & tested |
| 8 | Rate limiting | Per-user sliding window on translate / memo / replay / provider-test endpoints (`AI_RATE_LIMIT_PER_MINUTE`) | Implemented & tested (single process — see limitations) |
| 9 | Secret redaction | Logging filter redacts key/token patterns; provider error bodies redacted including the exact key; validation errors never echo input | Implemented & tested |
| 10 | Provider error handling | Normalized `ProviderError` codes; user-safe messages; no fabricated fallback output | Implemented & tested |
| 11 | Audit events | Login/logout, project/membership/glossary changes, imports, translation/memo jobs, edits, approvals, exports, provider key changes, admin actions | Implemented & tested (subset asserted) |
| 12 | Retention & deletion | Per-project retention purge, soft delete + grace hard delete, session-secret purge | Implemented & tested |
| 13 | Dependency scanning | `pip-audit` (0 known vulns at time of writing), `npm audit --omit=dev` (0); CI workflow runs both | Run locally; CI workflow not executed here |
| 14 | CORS & security headers | API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP `default-src 'none'`, HSTS in production, `TrustedHostMiddleware`; CORS off unless `CORS_ALLOWED_ORIGINS`. Web: CSP, frame-ancestors none, Permissions-Policy | Implemented & tested (API headers) |
| 15 | Cross-project leakage | Project filters on every list/aggregate; source references validated to belong to the same meeting; division managers see references without transcript excerpts unless permitted | Implemented & tested |
| — | SSRF on custom provider URLs | HTTPS only, no credentials in URL, DNS-resolved private/loopback/link-local/reserved addresses refused, optional host allow-list, redirects not followed | Implemented & tested |
| — | Export injection | HTML export escapes all content; CSV cells starting with `= + - @` are neutralized | Implemented & tested |

## Roles

| Capability | Member | Project Manager (membership `manager`) | Division Manager | Admin |
|---|---|---|---|---|
| View project meetings / memos / items | own projects | own projects | division projects (summary) | ✗ (metadata only) |
| View transcript & translations | own projects | own projects | only with `can_view_transcripts` | ✗ |
| Create meetings, import, translate, generate memo | ✓ | ✓ | ✗ | ✗ |
| Edit meeting/memo | meetings they created | any in project | ✗ | ✗ |
| Approve / reject / reopen memo | ✗ | ✓ | ✗ | ✗ |
| Update action status | own assigned actions | ✓ | ✗ | ✗ |
| Glossary, project settings, members | ✗ | ✓ | ✗ | settings & members |
| Create projects | ✗ | ✓ (global role `project_manager`) | ✗ | ✓ |
| Usage data | own | own + managed projects | own + division | all |
| Users, divisions, audit, health, retention | ✗ | ✗ | ✗ | ✓ |
| Plaintext API keys | never returned to anyone (no endpoint exposes them) | | | |

**The AI never approves anything.** AI output is stored as `draft`/`needs_review`; `approved` can only be
set by `POST /memos/{id}/approve` from an authenticated project manager session.

## API key handling

* Keys are accepted only in the body of `PUT /api/v1/providers/configs`, over the same-origin proxy.
  The frontend keeps the value in component state only and clears it after saving (never
  `localStorage`/`sessionStorage`, URLs, analytics or logs). No client-side env var contains secrets.
* **Default — session only**: the key is AES-256-GCM-encrypted into `session_secrets`, bound to the
  login session (associated data = config id + user id + session id). Logout, session expiry
  (purged every 5 minutes), account deactivation or key removal delete it.
* **Remember** (opt-in, only if `SECRET_ENCRYPTION_KEYS` is set and `ALLOW_PERSISTENT_API_KEYS=true`):
  ciphertext stored on the configuration row. If secure storage is not configured, the UI disables the
  option and the API refuses keys entirely.
* Responses expose only `key_storage`, `key_hint` (last 4 characters) and `has_usable_key`.
* Background jobs decrypt the key just-in-time from the session id recorded on the job.

### Key rotation

1. Generate a key: `python -m app.cli generate-key` → `k20261015:<base64>`.
2. Prepend it: `SECRET_ENCRYPTION_KEYS=k20261015:<new>,kOLD:<old>` and redeploy (new writes use the new key).
3. Re-encrypt stored secrets: `python -m app.cli rotate-keys`.
4. Remove the old key and redeploy.

Losing all keys makes stored API keys unrecoverable (users re-enter them); no other data is affected.

## Prompt injection

Imported transcripts are untrusted:

* Transcript text is serialized as JSON **data** inside `<transcript>`/`<segments>` blocks with `<`/`>`
  escaped, so it cannot close the block (tested).
* System prompts are constant per version and state that content inside data blocks is never an
  instruction (tested: transcript content never alters the system prompt).
* The model has no tools and receives only the current meeting's data (plus that project's glossary).
* Output must pass a strict schema (`extra="forbid"`, enums, refs that exist in the transcript); a model
  "obeying" an injection (e.g. emitting `status: approved`) is rejected and the memo marked failed (tested).
* Grounding post-checks remove owners not present in the cited lines and refuse unverifiable deadlines.
* Meeting-owner "custom instructions" are appended under the ground rules and cannot change workflow state.

## Data sent to third-party AI providers

Only when a user selects a non-mock provider, and only for the operation they start:

| Operation | Sent to provider | Not sent |
|---|---|---|
| Translation | Entry text and speaker labels of the chunk, 2 preceding lines (context), matching glossary terms, project translation instructions, language pair | Other meetings, user identities/e-mails, API keys of others, audit data |
| Memo generation | Full transcript of the meeting (text, speaker labels, timestamps, ref numbers), meeting title, project name, date/timezone, participant names, objective, custom instructions, glossary | Other meetings/projects, user e-mails, usage/audit data |
| Connection test | A fixed "ping" prompt and the model list request | Any meeting data |

Requests go directly from the worker/API to the provider using the user's own key (BYOK); provider-side
retention is governed by the user's provider account terms. The mock provider sends nothing externally.

## Meeting platform credentials (Workstream 2)

* **Separate from AI keys.** Platform OAuth tokens live in `platform_credentials` (encrypted with the
  same AES-256-GCM keyring, AAD `platform-credential:{connection}:{user}:{kind}`); they are never stored
  in `ai_provider_configurations` and never sent to AI providers (`test_tokens_never_exposed`).
* **Never reach the browser.** The frontend only receives the provider's authorization URL; API
  responses, diagnostics and logs contain account labels, timestamps and error categories only.
* **OAuth:** authorization code + PKCE (S256); server-side single-use `state` bound to user, login session
  and provider with a 10-minute TTL (consumed before validation, so a failed attempt cannot be replayed);
  redirect URI derived only from `PUBLIC_BASE_URL` (HTTPS required in production); post-callback
  redirect is a fixed relative path (no open redirect).
* **Lifecycle:** proactive refresh, refresh-token rotation, one refresh-and-retry on 401, revoke on
  disconnect, invalid grants surface as *consent revoked* — never retried.
* **Least privilege:** delegated scopes only (no Graph application permissions); Teams transcript scope is
  optional (`TEAMS_REQUEST_TRANSCRIPT_SCOPE`). Tenant restrictions and consent are never bypassed; there is
  no scraping or use of undocumented endpoints.
* **Webhooks:** HMAC-SHA256 signature over `v0:{timestamp}:{body}` with constant-time compare, timestamp
  tolerance, body size limit, per-IP rate limit, replay dedup in `provider_events`; events only affect a
  meeting a permitted user explicitly linked/armed.
* **Authorization:** linking, retrieval and live control require edit rights on the meeting *and* the
  caller's own connection; another user's connection is never used.
* **Provider transcript content is data**: it flows into the same prompt-injection-hardened translation
  and memo prompts (`test_transcript_prompt_injection_stays_data`).
* **Sandbox:** `INTEGRATION_ENDPOINT_OVERRIDES` (fake provider server) labels every connection SANDBOX and
  is refused at startup in production; malformed values fail fast.

### Data sent to meeting platforms

Only the OAuth requests, the meeting reference the user entered (to resolve it), and authenticated read
requests for the meeting's metadata and transcript. No AI output, other meetings or user data is sent.

## Live audio capture

See [`audio-capture.md`](audio-capture.md). Participant notice must be confirmed before capture (audited).
Audio is processed in memory and never stored; only short per-speaker voice references are kept, encrypted
(AAD `audio-speaker-ref:{session}:{speaker}`), and deleted when the session stops or goes idle. Only the
user who started a capture can post audio to it. Chunks are size/duration/format-validated and
rate-limited. Audio and voice references are sent to OpenAI with the user's own key; nothing else. The web
`Permissions-Policy` allows `microphone` and `display-capture` for the app's own origin only.
Streaming captions: the server mints a 10-minute OpenAI Realtime **client secret** per source; the browser
uses only that ephemeral key to open a WebRTC connection to OpenAI (CSP `connect-src` adds
`https://api.openai.com`). The user's API key never reaches the browser; audio flows browser → OpenAI.
Soniox (optional speech provider): the user's Soniox key is stored like any provider key (encrypted,
never returned) and can never become the default AI provider. Per source the server mints a **single-use
temporary key** (`POST /v1/auth/temporary-api-key`, `usage_type: transcribe_websocket`, 10-minute expiry,
session length capped by `SONIOX_MAX_SESSION_SECONDS`) and builds the session config itself (model, audio
format, glossary context, translation target); the browser only adds the temporary key and opens
`wss://stt-rt.soniox.com/transcribe-websocket` (CSP `connect-src` adds that host). Audio flows browser → Soniox.

## Logging

Structured JSON logs contain IDs, counts, durations, provider/model names and error codes. Transcript
text, translations and keys are never logged (verified in the Docker run: 0 transcript strings in logs).
