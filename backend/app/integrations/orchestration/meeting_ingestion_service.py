"""Ingestion orchestration: validate → authorize → order → deduplicate →
persist → hand off to the existing translation pipeline.

Transcript content is never logged; only counts and identifiers.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import ProviderError
from app.core.errors import AppError
from app.core.logging import log_event
from app.integrations.models import CanonicalEvent
from app.integrations.normalization.ordering import sort_events
from app.models import ExternalMeetingReference, Meeting, Project, TranscriptEntry
from app.models.enums import Language
from app.services.ingestion import ingest_event
from app.services.provider_config import resolve_provider
from app.services.translation import translate_entries

logger = logging.getLogger(__name__)


@dataclass
class IngestionOutcome:
    created: list[TranscriptEntry] = field(default_factory=list)
    duplicates: int = 0
    ignored: int = 0


def authorize_event_target(db: Session, meeting: Meeting, event: CanonicalEvent) -> bool:
    """A provider event may only enter the meeting that is explicitly linked to
    that provider meeting (no guessing by title; no cross-project fan-out)."""
    if event.provider in {"replay"}:
        return True
    ref = db.scalar(select(ExternalMeetingReference).where(ExternalMeetingReference.meeting_id == meeting.id))
    return bool(
        ref
        and ref.provider.value == event.provider
        and (
            event.provider_meeting_id in (None, ref.provider_meeting_id)
            or event.provider_meeting_id in (ref.resolved_ids or {}).values()
        )
    )


def ingest_events(
    db: Session, meeting: Meeting, events: list[CanonicalEvent], *, ordered: bool = True
) -> IngestionOutcome:
    outcome = IngestionOutcome()
    if meeting.deleted_at is not None:
        raise AppError("Meeting no longer exists")
    batch = sort_events(events) if ordered else events
    for event in batch:
        event.meeting_id = meeting.id
        if not authorize_event_target(db, meeting, event):
            outcome.ignored += 1
            continue
        entry, created = ingest_event(db, meeting, event)
        if entry is None:
            outcome.ignored += 1
        elif created:
            outcome.created.append(entry)
        else:
            outcome.duplicates += 1
    db.flush()
    log_event(
        logger,
        "ingestion.batch",
        meeting_id=str(meeting.id),
        created=len(outcome.created),
        duplicates=outcome.duplicates,
        ignored=outcome.ignored,
    )
    return outcome


def translate_new_entries(
    db: Session,
    meeting: Meeting,
    entries: list[TranscriptEntry],
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
) -> str | None:
    """Run the existing translation pipeline for freshly ingested entries.
    Failures never remove the original segments; they stay retryable.
    Returns a safe status note when translation could not run."""
    if not entries:
        return None
    project = db.get(Project, meeting.project_id)
    assert project is not None
    try:
        resolved = resolve_provider(db, user_id, session_id)
    except AppError as exc:
        return f"Translation pending: {exc.message}"
    try:
        translate_entries(
            db,
            meeting=meeting,
            project=project,
            entries=entries,
            target=Language(meeting.target_language),
            resolved=resolved,
            user_id=user_id,
            job_id=job_id,
        )
    except ProviderError as err:
        return f"Translation failed and can be retried: {err.message}"
    return None
