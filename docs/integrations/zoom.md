# Zoom integration

**Verification date:** 2026-10-16 · **Verified against a real Zoom account:** **No**. RTMS behaviour is
tested with a fake client implementing the documented callback signatures of the official SDK.

## Status per capability

| Capability | Status | Evidence |
|---|---|---|
| Transcript file import (cloud-recording VTT) | **Implemented, works** | WS1 parsers |
| List meetings (cloud recordings) | Implemented · tested with mocks | mock fixtures (`users/me/recordings`) |
| Post-meeting transcript | Implemented · tested with mocks | `test_zoom_recording_transcript_and_redirect_without_token_leak`, `test_zoom_processing_reschedules_then_imports`, browser E2E `workstream2-integrations.spec.ts` |
| Live transcript (RTMS) | Implemented · tested with mocks · **requires RTMS provisioning** · not verified live | `test_live_rtms_ingestion_end_to_end`, `test_zoom_live_requires_operator_configuration` |
| Live audio | **Not used** (RTMS already delivers transcript text; no STT added) | — |
| Speaker identification | RTMS `userId` / `userName`; VTT `Name:` prefix | `test_live_rtms_ingestion_end_to_end` |
| Event notifications | Implemented: signed webhooks (`meeting.rtms_started`, `meeting.rtms_stopped`, `recording.transcript_completed`, `endpoint.url_validation`) | `test_webhook_signature_and_replay_protection` |
| Recovery | Post-meeting: idempotent re-fetch. Live: session marked *interrupted*; segments missed during a drop are recovered from the post-meeting transcript (RTMS is not lossless) | `test_zoom_processing_reschedules_then_imports`, `test_live_stop_and_rtms_stopped` |

## Account type and app

* Zoom account with **cloud recording** and *audio transcript* enabled (paid plans) for post-meeting
  transcripts.
* Zoom Marketplace **General app (OAuth, user-managed)**:
  * Redirect URL / allow list: `{PUBLIC_BASE_URL}/api/v1/integrations/zoom/oauth/callback`.
  * Scopes: read user profile, read meetings, read cloud recordings — configure the exact granular scope
    names in `ZOOM_SCOPES` (**unresolved**: scope names could not be verified against Zoom's reference
    from the build environment).
  * Event subscriptions → endpoint `{PUBLIC_BASE_URL}/api/v1/integrations/zoom/webhook`, copy the
    **Secret Token** to `ZOOM_WEBHOOK_SECRET_TOKEN`. Subscribe to `recording.transcript_completed` and,
    for live, `meeting.rtms_started` / `meeting.rtms_stopped`.
* Live (RTMS) additionally needs: RTMS enabled for the account by Zoom, RTMS scopes/events on the app,
  `pip install '.[zoom-rtms]'` (official `rtms==1.1.0` SDK, Linux x86_64 wheels) and
  `ZOOM_RTMS_ENABLED=true`. The host starts the stream in the meeting; Memo Hub only joins streams for
  meetings a user explicitly armed.

## Environment variables

```
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...            # secret manager
ZOOM_WEBHOOK_SECRET_TOKEN=...     # secret manager
ZOOM_SCOPES="..."                 # space-separated, as configured on the app
ZOOM_RTMS_ENABLED=false
```

## Setup and test procedure

1. Configure, restart, then *Tích hợp nền tảng* → Zoom → **Kết nối** → authorize.
2. In Zoom's app page, *Validate* the event endpoint (Memo Hub answers the `endpoint.url_validation`
   challenge with `HMAC-SHA256(secret, plainToken)`).
3. Meeting → *Nguồn cuộc họp* → paste `https://…zoom.us/j/<id>` or the 9–12 digit id → **Liên kết**.
4. After the meeting, **Lấy transcript sau cuộc họp** (or wait for `recording.transcript_completed`).
   Transcript still processing → *pending* with automatic retry.
5. Live: **Bật transcript trực tiếp** (session = *waiting*), the host starts RTMS, Memo Hub receives
   `meeting.rtms_started`, joins with the SDK, and the live page shows *DỮ LIỆU THẬT TỪ NỀN TẢNG* with
   duration, reconnects and last event.

## Webhook security

* Signature: `x-zm-signature = v0=HMAC-SHA256(secret, "v0:{x-zm-request-timestamp}:{raw body}")`,
  constant-time compare; timestamps outside ±`INTEGRATION_WEBHOOK_TOLERANCE_SECONDS` rejected.
* Body size limit `INTEGRATION_WEBHOOK_MAX_BYTES`; per-IP rate limit.
* Replay protection: every event is stored in `provider_events` with a dedup key; duplicates answer
  `{"status":"duplicate"}` and do nothing.
* Events only affect a meeting that was explicitly linked (and, for RTMS, armed) by an authorized user.

## Limitations

* Cloud recording transcripts need a paid plan and recording to the cloud.
* RTMS availability depends on Zoom provisioning; it is not lossless across disconnects.
* Meeting UUIDs starting with `/` or containing `//` are double-encoded as Zoom requires.

## Official references

* RTMS SDK (read): <https://github.com/zoom/rtms> · PyPI <https://pypi.org/project/rtms/>
* Webhook validation / signature: <https://developers.zoom.us/docs/api/webhooks/>
* OAuth: <https://developers.zoom.us/docs/integrations/oauth/>
* Cloud recordings API: <https://developers.zoom.us/docs/api/meetings/#tag/cloud-recording>
* RTMS overview: <https://developers.zoom.us/docs/rtms/>

## Unresolved

* Exact granular scope names (configurable via `ZOOM_SCOPES`).
* RTMS end-to-end against a provisioned account.
