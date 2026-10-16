# Google Meet integration

**Verification date:** 2026-10-16 · **Verified against a real Workspace account:** **No**. Tests use
fixtures built from the official Meet REST API v2 protos (`googleapis/googleapis`, `google/apps/meet/v2`).

## Status per capability

| Capability | Status | Evidence |
|---|---|---|
| Transcript file import (Docs export → TXT) | **Implemented, works** | WS1 parsers |
| List meetings (`conferenceRecords`) | Implemented · tested with mocks | mock fixtures (`conferenceRecords`) |
| Post-meeting transcript (`transcripts/*/entries`) | Implemented · tested with mocks | `test_google_meet_transcript_entries_with_pagination_and_participants` |
| Live transcript | **Not supported** — the Meet Media API is developer preview, requires every participant enrolled, and provides no transcripts | Never advertised |
| Live audio | **Not supported** | — |
| Speaker identification | Participant resource: `signedinUser` / `anonymousUser` / `phoneUser` display names; `None` when unavailable (never invented) | `test_google_meet_transcript_entries_with_pagination_and_participants` |
| Event notifications | **Not implemented** (Workspace Events API needs Pub/Sub); bounded polling instead | — |
| Recovery | Idempotent re-fetch with bounded backoff while transcript state ≠ `FILE_GENERATED` | `test_google_meet_pending_expired_and_ongoing` |

## Account type and OAuth client

* Google Workspace edition with Meet transcripts; the user must have access to the conference.
* Google Cloud project → enable **Google Meet REST API** → OAuth consent screen → OAuth client *Web
  application* with redirect URI `{PUBLIC_BASE_URL}/api/v1/integrations/google_meet/oauth/callback`.
* Scopes: `openid`, `email`, `https://www.googleapis.com/auth/meetings.space.readonly`. Depending on the
  consent screen configuration this scope may require Google app verification for external users, and a
  Workspace admin may restrict third-party app access (→ *Admin Approval Required*).

## Environment variables

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...   # secret manager
```

## Setup and test procedure

1. Configure, restart, *Tích hợp nền tảng* → Google Meet → **Kết nối** → consent.
2. Meeting → *Nguồn cuộc họp* → paste `https://meet.google.com/abc-mnop-xyz` or the code → **Liên kết**.
3. **Lấy transcript sau cuộc họp**. Outcomes: imported; *pending* (conference ongoing, or transcript
   `STARTED`/`ENDED` but not yet `FILE_GENERATED`); *not available* (no transcript, or records older than
   30 days); *permission denied*.

## Limitations

* Conference records and transcripts expire **30 days** after the conference.
* The same meeting code can have several conference records; the most recent ended record is used.
* Entry pages are bounded (`MAX_ENTRY_PAGES=200`).

## Official references

* Meet REST API: <https://developers.google.com/meet/api/guides/overview>
* Transcripts: <https://developers.google.com/meet/api/guides/artifacts>
* Scopes: <https://developers.google.com/meet/api/guides/authenticate-authorize>
* Media API (preview, not used): <https://developers.google.com/meet/media-api/guides/overview>
* Source actually read: <https://github.com/googleapis/googleapis/tree/master/google/apps/meet/v2>

## Unresolved

* Whether `meetings.space.readonly` is classified as sensitive or restricted for verification purposes in
  every consent-screen configuration.
