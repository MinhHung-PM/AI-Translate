# Workstream 2 integration contract

Workstream 1 ships the Product Core. Live meeting integrations (Microsoft Teams, Zoom RTMS, Google Meet)
are **not implemented**; the UI reports them as "Integration not configured" and offers transcript import.
This document fixes the interfaces those connectors must use, so they plug in without changing the core.

## 1. Normalized event (`backend/app/connectors/base.py`)

```python
class TranscriptEvent(BaseModel):          # extra fields are rejected
    connector: str          # "teams" | "zoom" | "google_meet" | "replay"
    is_demo: bool           # True only for replay; the UI labels demo sessions
    external_id: str | None # stable id from the source → ingestion is idempotent
    speaker: str | None     # only if the platform provides it — never inferred
    start_ms: int | None    # offset from meeting start, if provided
    end_ms: int | None
    text: str               # final recognized text (≤ 20 000 chars)
    language: "ja"|"vi"|"en"|None
    is_final: bool = True   # interim/partial results are ignored by ingestion
    metadata: dict          # source-specific ids (e.g. Graph transcript id, RTMS stream id)
```

## 2. Ingestion entry point

```python
from app.services.ingestion import ingest_event
entry = ingest_event(db, meeting, event)   # → TranscriptEntry | None; caller commits
```

* Assigns the next `sequence`, cleans text, detects language if absent, stores connector metadata.
* Idempotent on `external_id` (re-delivered webhooks do not duplicate entries).
* After ingesting, a connector may call `translate_entries(...)` for low-latency translation (as the
  replay demo does) or enqueue a `translation` job for batches.
* The UI's live view polls `GET /api/v1/meetings/{id}/live?after_sequence=N`; nothing else changes.

## 3. Connector interface

```python
class MeetingConnector(Protocol):
    key: str
    def status(self) -> ConnectorStatus: ...          # available | demo | not_configured + message
    def start(self, meeting_id: str, options: dict) -> str: ...   # returns live_session id
    def stop(self, live_session_id: str) -> None: ...
```

Register the connector in `connectors/registry.py` and flip its status from `not_configured` only when
credentials/permissions are verified at runtime. A `live_sessions` row (`connector`, `is_demo=false`,
status, counters) must be created per live session.

## 4. Platform notes (to be validated in Workstream 2)

| Platform | Likely mechanism | Prerequisites (blockers for WS1) |
|---|---|---|
| Microsoft Teams | Microsoft Graph online-meeting transcripts (`/onlineMeetings/{id}/transcripts`, change notifications) for post-meeting/near-real-time; real-time media requires a hosted media bot | Entra app registration, `OnlineMeetingTranscript.Read.All` (application) + admin consent, application access policy, webhook endpoint |
| Zoom | Realtime Media Streams (RTMS) for live transcript/audio; cloud recording transcript (VTT) for post-meeting | Zoom Marketplace app, RTMS entitlement, webhook validation secret |
| Google Meet | Meet REST API transcripts (post-meeting, Google Docs) and Workspace Events subscriptions | Google Workspace edition with transcripts, OAuth consent, domain-wide policy |

Until then: export the transcript (VTT/TXT) from the platform and import it — fully supported.

## 5. Security requirements for connectors

* Platform credentials live in a secret manager, never in the database in plaintext; reuse
  `core/crypto.KeyRing` if they must be stored.
* Webhooks must verify signatures/validation tokens before calling `ingest_event`.
* A connector may only ingest into meetings of projects for which the meeting owner has access; resolve
  the meeting by an explicit mapping (meeting URL/ID recorded on `meetings.meeting_url` or metadata),
  never by guessing from titles.
* Audio is out of scope for storage in WS1; if WS2 stores audio, extend retention (`services/retention.py`).
