# Workstream 2 integration contract (as implemented)

This replaces the WS1 draft contract. Code lives in `backend/app/integrations/`. A connector is a thin
adapter: it talks to one provider and emits canonical events; storage, translation, memo, review and
action tracking are the unchanged Workstream 1 services.

```
Meeting source ─▶ Connector ─▶ CanonicalEvent ─▶ normalization (dedup, ordering)
   ─▶ services.ingestion.ingest_event ─▶ TranscriptEntry ─▶ translate_entries ─▶ live feed / workspace
   ─▶ memo generation ─▶ review ─▶ action tracker
```

## 1. Connector contract (`integrations/base.py`)

| Method | Purpose |
|---|---|
| `configuration_problems()` / `is_configured()` | Server-side prerequisites (env vars). Unconfigured → *Not Configured* |
| `get_capabilities(scopes, connected)` | Returns a `CapabilityState` for **every** `Capability` (contract test enforces it) |
| `requested_scopes()` / `authorization_params()` / `begin_authorization(state, challenge, redirect_uri)` | Authorization-code + PKCE (S256) URL |
| `complete_authorization(code, verifier, redirect_uri)` / `refresh_credentials(rt)` / `revoke(tokens)` | Token lifecycle (`TokenSet`) |
| `fetch_account(token)` / `health_check(token, scopes)` | Connection test |
| `list_available_meetings(token)` | Optional (capability `list_meetings`) |
| `resolve_meeting(token, reference)` | Join URL / id / code → `ResolvedMeeting` (validates access through the provider) |
| `fetch_transcript(token, ref)` | → `TranscriptFetchResult(status, events, message)`; status `available` / `pending` / `not_available` |
| `subscribe_to_meeting_events`, `start/stop_realtime_ingestion` | Raise `unsupported` unless the provider implements them (Zoom RTMS lives in `zoom/rtms.py` + `orchestration/connection_manager.py`) |

Provider errors are mapped to `IntegrationError(category, message, retry_after, provider_code)`;
categories (`integrations/errors.py`): `not_configured, not_connected, invalid_credentials, token_expired,
consent_revoked, insufficient_scope, admin_approval_required, unsupported_account, unsupported,
meeting_not_found, no_meeting_access, transcript_unavailable, transcript_pending, rate_limited,
provider_unavailable, invalid_signature, invalid_request, invalid_response`. Non-retryable categories are
never retried.

## 2. Capabilities (`integrations/capabilities.py`)

Capabilities: `transcript_import, list_meetings, post_meeting_transcript, live_transcript, live_audio,
speaker_metadata, meeting_event_notifications, recovery_after_disconnect`.
Status: `available, requires_configuration, requires_user_consent, requires_admin_approval, not_supported,
temporarily_unavailable` + `message`, `remediation`, `verified_live` (always `false` in this delivery).
The API refuses an operation whose capability is not `available` (`409 integration_unsupported` /
`integration_admin_approval_required` …).

## 3. Canonical event (`integrations/models.py`)

```python
class CanonicalEvent(BaseModel):  # extra fields forbidden
    event_id: str; provider: str; provider_meeting_id: str | None; meeting_id: UUID | None
    event_type: transcript_segment | meeting_started | meeting_ended | connection_status
                | transcript_available | ingestion_error
    entry_id: str | None            # provider id of the segment
    speaker_id: str | None; speaker_display_name: str | None     # None if not supplied — never invented
    start_timestamp_ms: int | None; end_timestamp_ms: int | None # None if not supplied — never invented
    source_language: ja | vi | en | None; original_text: str | None
    translation_status: str | None; source_metadata: dict; received_at: datetime
    provider_sequence: int | None; is_final: bool = True; is_demo: bool = False
```

## 4. Dedup, ordering, idempotency

* Dedup key = SHA-256 of the first available of `entry_id` → `provider_sequence` →
  `(start_ms, speaker, text)`; no key when none exist (legitimate repeats are kept).
  Enforced by `uq_transcript_entry_dedup(meeting_id, dedup_key)` + savepoint on conflict.
* Live events pass through `OrderingBuffer(max_items=50, max_delay_s=1.5)`; late events are kept and
  flagged `late=true`, never dropped.
* Webhooks are recorded in `provider_events` with a unique `(provider, dedup_key)` → replays are no-ops.
* Retrieval jobs use bounded exponential backoff with full jitter, honour `Retry-After`, and stop after
  `INTEGRATION_FETCH_MAX_ATTEMPTS`.

## 5. Authorization of ingestion

Events are written only to the meeting a permitted user explicitly linked
(`external_meeting_refs`, unique per meeting and per provider meeting). Webhooks for unlinked meetings are
recorded and ignored. RTMS streams are joined only for meetings armed via *live/start*.

## 6. Adding a provider

1. Add a `PlatformProvider` value and a `Connector` subclass under `integrations/<provider>/`.
2. Register it in `integrations/registry.py`.
3. Add fake-provider scenarios in `tests/fakes/fake_providers.py`; the contract tests in
   `test_integrations_unit.py` run against every registered connector automatically.
4. Document it in `docs/integrations/<provider>.md` with verification date and status per capability.
