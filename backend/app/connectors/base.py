"""Meeting connector contract (stable interface for Workstream 2).

Every live source — the Workstream 1 replay demo now, and Microsoft Teams,
Zoom RTMS or Google Meet later — produces ``TranscriptEvent`` objects and
hands them to ``services.ingestion.ingest_event``. Downstream (storage,
translation, memo generation, UI polling) is identical for all sources, so
adding a connector requires no change to the core.

See docs/workstream-2-integration-contract.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Language


class TranscriptEvent(BaseModel):
    """One normalized utterance from a connector."""

    model_config = ConfigDict(extra="forbid")

    connector: str = Field(max_length=32)  # "replay", "teams", "zoom", "google_meet"
    is_demo: bool  # True for replay — the UI must label demo sessions
    external_id: str | None = Field(default=None, max_length=200)  # idempotency key from the source
    speaker: str | None = Field(default=None, max_length=200)  # only if the source provides it
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1, max_length=20_000)
    language: Language | None = None
    is_final: bool = True  # interim (partial) results must not be stored
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorState(StrEnum):
    available = "available"
    demo = "demo"
    not_configured = "not_configured"


class ConnectorStatus(BaseModel):
    key: str
    display_name: str
    state: ConnectorState
    message: str
    supports_live: bool
    supports_transcript_import: bool


class MeetingConnector(Protocol):
    """Implemented by each connector in Workstream 2."""

    key: str

    def status(self) -> ConnectorStatus: ...

    def start(self, meeting_id: str, options: dict[str, Any]) -> str:
        """Begin receiving events for a meeting; returns a live-session id."""
        ...

    def stop(self, live_session_id: str) -> None: ...
