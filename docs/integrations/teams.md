# Microsoft Teams integration

**Verification date:** 2026-10-16 · **Verified against a real tenant:** **No** (no Entra tenant in the build
environment). Every automated test runs against a mocked Graph built from the official API reference.

## Status per capability

| Capability | Status | Evidence |
|---|---|---|
| Transcript file import (VTT export) | **Implemented, works** | WS1 parsers; `tests/test_unit_transcripts.py` |
| List meetings (`/me/calendarView`) | Implemented · tested with mocks | `test_teams_scope_driven_capabilities` |
| Post-meeting transcript (Graph) | Implemented · tested with mocks · **requires admin approval** | `test_teams_oauth_link_fetch_translate_memo`, `test_teams_without_admin_consent_degrades_to_import`, `test_teams_admin_consent_denied_at_authorization`, `test_teams_tenant_disabled_transcripts` |
| Live transcript | **Not supported** | Requires application `Calls.AccessMedia.All` + a hosted media bot (out of scope); never advertised. `test_teams_live_is_never_offered` |
| Live audio | **Not supported** | Same as above |
| Speaker identification | Implemented (VTT `<v Name>`), falls back to unattributed if the tenant disables attribution | `test_teams_speaker_attribution_disabled_falls_back` |
| Event notifications | **Not implemented** — transcript change notifications need application permissions | — |
| Recovery | Idempotent re-fetch + bounded backoff | `test_teams_no_transcript_yet_is_pending_with_bounded_retry`, `test_backoff_bounded_with_jitter` |

## Account type and app registration

* Work or school account in a Microsoft 365 tenant with Teams transcription enabled. Personal
  (consumer) Microsoft accounts are not supported for transcript APIs.
* Register an app in **Entra ID → App registrations**:
  * Supported account types: *Accounts in any organizational directory* (multi-tenant) or single tenant
    (then set `TEAMS_TENANT_ID` to the tenant id).
  * Platform **Web**, redirect URI exactly `{PUBLIC_BASE_URL}/api/v1/integrations/teams/oauth/callback`.
  * Create a client secret (store it in your secret manager → `TEAMS_CLIENT_SECRET`).
  * API permissions (**Delegated** only):

| Permission | Admin consent | Used for |
|---|---|---|
| `openid`, `profile`, `offline_access`, `User.Read` | No | Sign-in, refresh token, account label |
| `Calendars.Read` | No | Listing the user's Teams meetings |
| `OnlineMeetings.Read` | No | Resolving a join URL / meeting id to an online meeting |
| `OnlineMeetingTranscript.Read.All` | **Yes** | Reading transcripts of meetings the user can access |

Application permissions are **not** used. The app never bypasses tenant restrictions or consent.

## Admin approval

If the tenant has not consented to `OnlineMeetingTranscript.Read.All`, the authorization returns
`consent_required` / `AADSTS65001` and the card shows **Admin Approval Required**. Options:

1. A tenant administrator grants admin consent for the app (Entra → Enterprise applications →
   Permissions → *Grant admin consent*).
2. Or set `TEAMS_REQUEST_TRANSCRIPT_SCOPE=false`: users can connect without admin consent; the card then
   shows *post-meeting transcript: requires admin approval* and **file import remains the path**.

Tenants can also block transcript access entirely (Graph error `GraphAccessToTranscriptsDisabled`) →
mapped to *Admin Approval Required* with the provider code shown in diagnostics.

## Environment variables

```
PUBLIC_BASE_URL=https://memohub.example.com       # https required in production
TEAMS_CLIENT_ID=...
TEAMS_CLIENT_SECRET=...                           # secret manager
TEAMS_TENANT_ID=organizations                     # or your tenant id
TEAMS_REQUEST_TRANSCRIPT_SCOPE=true
```

## Setup and test procedure

1. Configure the variables above and restart the API.
2. *Tích hợp nền tảng* → Microsoft Teams → **Kết nối** → wizard → **Mở trang cấp quyền**.
3. After consent you return to `/integrations?provider=teams&result=connected`; the card lists the granted
   capabilities. **Kiểm tra kết nối** calls `GET /me` with the stored token.
4. Open a meeting → *Nguồn cuộc họp* → paste the Teams join link (`https://teams.microsoft.com/l/meetup-join/...`)
   or the numeric meeting id → **Liên kết** → **Lấy transcript sau cuộc họp**.
5. Expected outcomes: entries imported with speakers; or *pending* (meeting ended < 24 h ago, retried with
   backoff); or *not available*; or *Admin Approval Required*.

## Limitations

* Only meetings the signed-in user organised or can access through Graph are retrievable.
* Transcripts exist only if someone started transcription in the meeting.
* Several transcripts for one meeting are merged onto one timeline in order.
* No live transcript; use import or post-meeting retrieval.

## Recovery

Retrieval runs as a `fetch_transcript` job with bounded exponential backoff
(`INTEGRATION_FETCH_MAX_ATTEMPTS`, base/max delay). Imports are idempotent (dedup key = Graph transcript id
+ VTT cue id), so retries never duplicate entries. Expired/revoked tokens move the card to
*Temporarily Disconnected* or *Error* with the category shown; reconnecting rotates tokens.

## Official references

* Graph `callTranscript` / list transcripts / get content:
  <https://learn.microsoft.com/graph/api/onlinemeeting-list-transcripts>,
  <https://learn.microsoft.com/graph/api/calltranscript-get>
* Permissions reference: <https://learn.microsoft.com/graph/permissions-reference>
* Source actually read (docs site blocked from the build environment):
  <https://github.com/microsoftgraph/microsoft-graph-docs-contrib> (`api-reference/v1.0/api/calltranscript-get.md`,
  `onlinemeeting-list-transcripts.md`, `concepts/permissions-reference.md`)

## Unresolved

* Behaviour with real tenant policies (meeting policy *transcription* off, retention) — not verified live.
* Whether `OnlineMeetings.Read` resolves meetings the user only attended (not organised) in every tenant
  configuration — documented as organiser-scoped in places; verify on a real tenant.
