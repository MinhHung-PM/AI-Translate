"""Canonical internal event model. Every connector (and the replay demo)
emits these; provider-specific shapes never leave the connector module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Language


class EventType(StrEnum):
    transcript_segment = "transcript_segment"
    meeting_started = "meeting_started"
    meeting_ended = "meeting_ended"
    connection_status = "connection_status"
    transcript_available = "transcript_available"
    ingestion_error = "ingestion_error"


def _now() -> datetime:
    return datetime.now(UTC)


class CanonicalEvent(BaseModel):
    """Provider-independent event. Speaker and timestamps are ``None`` when the
    provider does not supply them — they are never synthesized."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=200)
    provider: str = Field(max_length=32)  # teams | zoom | google_meet | replay
    provider_meeting_id: str | None = Field(default=None, max_length=512)
    meeting_id: uuid.UUID | None = None  # app meeting, set by orchestration after authorization
    event_type: EventType = EventType.transcript_segment
    entry_id: str | None = Field(default=None, max_length=300)  # provider's id for this segment
    speaker_id: str | None = Field(default=None, max_length=300)
    speaker_display_name: str | None = Field(default=None, max_length=200)
    start_timestamp_ms: int | None = Field(default=None, ge=0)  # offset from meeting/transcript start
    end_timestamp_ms: int | None = Field(default=None, ge=0)
    source_language: Language | None = None
    original_text: str | None = Field(default=None, max_length=20_000)
    translation_status: str | None = None  # filled when published to the UI
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=_now)
    provider_sequence: int | None = None
    is_final: bool = True  # interim (partial) segments are never persisted
    is_demo: bool = False  # replay demo only

    @property
    def is_transcript(self) -> bool:
        return self.event_type == EventType.transcript_segment
