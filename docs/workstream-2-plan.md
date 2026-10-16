# Workstream 2 — plan, module mapping and feasibility

Verification date: 2026-10-16. Sources were read from the providers' **official** repositories because
`learn.microsoft.com`, `developers.zoom.us` and `developers.google.com` are not reachable from the build
environment: `microsoftgraph/microsoft-graph-docs-contrib` (Graph API reference + permissions reference),
`googleapis/googleapis` (`google/apps/meet/v2/*.proto`, the Meet REST API contract), and `zoom/rtms`
(official RTMS SDK + examples). Anything that could not be confirmed there is marked **unresolved**.

## 1. Workstream 1 → Workstream 2 module mapping (reuse, no duplicates)

| WS2 need | Existing WS1 module | Decision |
|---|---|---|
| Transcript storage | `models.TranscriptEntry` (+`source_metadata`) | Reused. Added nullable `dedup_key` + unique `(meeting_id, dedup_key)` |
| Live/connector entry point | `services/ingestion.ingest_event`, `connectors/base.TranscriptEvent` | Generalised to the canonical event (`integrations/models.CanonicalEvent`); replay demo migrated to it |
| Live session state | `models.LiveSession` | Reused; added provider session id, reconnect count, last event, status message |
| File import (Teams/Zoom/Meet exports) | `services/transcripts/*` parsers | Reused unchanged (VTT `<v Speaker>`, `Name: text`, JSON) |
| Translation | `services/translation.translate_entries` + `translation` job | Reused unchanged |
| Memo generation / review / actions | `services/memo_generation`, memo API | Reused unchanged |
| Background work | PostgreSQL job queue (`jobs`, `worker.py`) | Reused; added `run_after` for bounded backoff and kinds `fetch_transcript`, `realtime_ingest` |
| Live UI updates | **No WebSocket exists in WS1** — the live view polls `GET /meetings/{id}/live` | Kept polling (works through the Next.js proxy); provider events use the same feed. No second gateway introduced |
| Auth / sessions / CSRF | `api/deps.get_auth`, server sessions | Reused; OAuth callbacks require the logged-in session |
| Secret encryption | `core/crypto.KeyRing` (AES-256-GCM, rotation) | Reused for platform tokens (separate table, separate AAD) |
| AI API keys | `ai_provider_configurations` | Untouched; platform tokens never stored there |
| Authorization | `services/authz` | Reused for every new endpoint |
| Audit / usage / rate limit / redaction | existing services | Reused |

## 2. Feasibility matrix

| Capability | Teams | Zoom | Google Meet |
|---|---|---|---|
| Transcript file import | **Available** (VTT export) | **Available** (cloud-recording VTT) | **Available** (TXT/JSON) |
| List meetings | Delegated `Calendars.Read` (no admin consent) | OAuth user app: cloud recordings list | `meetings.space.readonly`: conference records |
| Post-meeting transcript API | Delegated `OnlineMeetingTranscript.Read.All` — **admin consent required**; tenant can disable (`GraphAccessToTranscriptsDisabled`) | Cloud recording `TRANSCRIPT` file — needs paid plan + cloud recording + audio transcript enabled; exact granular scope **unresolved** | `conferenceRecords/*/transcripts/*/entries`; transcript must be `FILE_GENERATED`; records expire 30 days after the conference |
| Live transcript | **Not supported** (needs application `Calls.AccessMedia.All` + hosted media bot) | RTMS via official `rtms` SDK — needs RTMS-enabled account/app, webhook `meeting.rtms_started`; **unverified live** | **Not supported** (Meet Media API is developer preview, all participants enrolled, no transcripts) |
| Live audio | Not supported | Not used (RTMS provides transcript text, so no STT) | Not supported |
| Speaker identification | VTT voice tags unless tenant disables (`SpeakerAttributionNotAllowed` → unattributed fallback) | RTMS `userId`/`userName`; VTT `Name:` | Participant resource display name |
| Event notifications | Not implemented (transcript subscriptions need application permissions) | Webhooks (signature `v0:{ts}:{body}`) | Not implemented (Workspace Events needs Pub/Sub); bounded polling instead |
| Recovery | Idempotent re-fetch | Re-fetch; RTMS rejoin only while the stream is active (not lossless) | Idempotent re-fetch with bounded backoff |

**Blockers for real-provider verification:** no Entra tenant / Zoom account / Google Workspace account
credentials in this environment. All provider tests use contract fixtures built from the official schemas
and are labelled *mocked*.

## 3. Minimum useful implementation (delivered)

1. Common framework: connector contract, typed capability states, canonical event, dedup/ordering,
   OAuth (state + PKCE + encrypted tokens), ingestion orchestration, status/diagnostics API.
2. Teams: import (works today) + delegated Graph retrieval that degrades to *Admin Approval Required*.
3. Zoom: OAuth, cloud-recording transcript retrieval, signed webhooks, RTMS adapter on the official SDK.
4. Google Meet: OAuth, conference-record transcript retrieval with bounded backoff.
5. UI: integration settings, connection wizard, diagnostics, meeting source selector, provider-aware live view.
