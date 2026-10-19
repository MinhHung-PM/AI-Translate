"""Single entry point for connector events into the transcript store.

Used by every source: the replay demo, post-meeting retrieval (Teams, Zoom,
Google Meet) and live streams (Zoom RTMS). Idempotent: a provider event whose
dedup key already exists for the meeting returns the existing entry (enforced by
the ``uq_transcript_entry_dedup`` constraint, so concurrent deliveries are safe).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.models import CanonicalEvent
from app.integrations.normalization.event_deduplicator import dedup_key
from app.models import Meeting, TranscriptEntry
from app.models.enums import MeetingStatus
from app.services.transcripts.importer import lock_meeting_transcript, next_sequence
from app.services.transcripts.normalize import clean_text, detect_language


def ingest_event(db: Session, meeting: Meeting, event: CanonicalEvent) -> tuple[TranscriptEntry | None, bool]:
    """Store one final transcript segment. Returns ``(entry, created)``.
    Non-transcript and interim events are ignored (``(None, False)``)."""
    if not event.is_transcript or not event.is_final or not event.original_text:
        return None, False
    text = clean_text(event.original_text)[: get_settings().max_entry_chars]
    if not text:
        return None, False
    lock_meeting_transcript(db, meeting.id)  # also makes the dedup check below race-free
    key = dedup_key(event)
    if key:
        existing = db.scalar(
            select(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id, TranscriptEntry.dedup_key == key)
        )
        if existing is not None:
            return existing, False
    speaker = clean_text(event.speaker_display_name)[:200] if event.speaker_display_name else None
    metadata = {
        **event.source_metadata,
        "connector": event.provider,
        "is_demo": event.is_demo,
        "event_id": event.event_id,
        **({"provider_meeting_id": event.provider_meeting_id} if event.provider_meeting_id else {}),
        **({"entry_id": event.entry_id} if event.entry_id else {}),
        **({"speaker_id": event.speaker_id} if event.speaker_id else {}),
        **({"provider_sequence": event.provider_sequence} if event.provider_sequence is not None else {}),
        "received_at": event.received_at.isoformat(),
    }
    savepoint = db.begin_nested()
    try:
        entry = TranscriptEntry(
            meeting_id=meeting.id,
            sequence=next_sequence(db, meeting),
            speaker_label=speaker or None,
            start_ms=event.start_timestamp_ms,
            end_ms=event.end_timestamp_ms,
            original_text=text,
            source_language=event.source_language or detect_language(text) or meeting.source_language,
            source_metadata=metadata,
            dedup_key=key,
        )
        db.add(entry)
        db.flush()
        savepoint.commit()
    except IntegrityError:
        # A concurrent delivery stored the same event (or took the sequence number) first.
        savepoint.rollback()
        if key:
            existing = db.scalar(
                select(TranscriptEntry).where(
                    TranscriptEntry.meeting_id == meeting.id, TranscriptEntry.dedup_key == key
                )
            )
            if existing is not None:
                return existing, False
        raise
    if meeting.status == MeetingStatus.planned:
        meeting.status = MeetingStatus.transcript_ready
    return entry, True
