"""Single entry point for connector events into the transcript store."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import TranscriptEvent
from app.core.config import get_settings
from app.models import Meeting, TranscriptEntry
from app.models.enums import MeetingStatus
from app.services.transcripts.importer import next_sequence
from app.services.transcripts.normalize import clean_text, detect_language


def ingest_event(db: Session, meeting: Meeting, event: TranscriptEvent) -> TranscriptEntry | None:
    """Store one final event as a TranscriptEntry. Idempotent on external_id.
    Interim results are ignored (returns None)."""
    if not event.is_final:
        return None
    if event.external_id:
        existing = db.scalar(
            select(TranscriptEntry).where(
                TranscriptEntry.meeting_id == meeting.id,
                TranscriptEntry.source_metadata["external_id"].astext == event.external_id,
            )
        )
        if existing is not None:
            return existing
    text = clean_text(event.text)[: get_settings().max_entry_chars]
    if not text:
        return None
    entry = TranscriptEntry(
        meeting_id=meeting.id,
        sequence=next_sequence(db, meeting),
        speaker_label=clean_text(event.speaker)[:200] if event.speaker else None,
        start_ms=event.start_ms,
        end_ms=event.end_ms,
        original_text=text,
        source_language=event.language or detect_language(text) or meeting.source_language,
        source_metadata={
            **event.metadata,
            "connector": event.connector,
            "is_demo": event.is_demo,
            **({"external_id": event.external_id} if event.external_id else {}),
        },
    )
    db.add(entry)
    if meeting.status == MeetingStatus.planned:
        meeting.status = MeetingStatus.transcript_ready
    db.flush()
    return entry
