"""Link app meetings to provider meetings and retrieve post-meeting transcripts.

Retrieval runs as a background job (``fetch_transcript``). When the transcript
is not ready yet the job is re-queued with bounded exponential backoff + jitter
(``recovery_service``); permanent failures (permissions, not available) stop
immediately with an actionable status. Manual file import always remains possible.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.core.logging import log_event
from app.db.base import utcnow
from app.integrations import oauth
from app.integrations.base import ResolvedMeeting
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.orchestration.meeting_ingestion_service import ingest_events, translate_new_entries
from app.integrations.orchestration.recovery_service import next_attempt_at
from app.integrations.registry import get_connector
from app.models import ExternalMeetingReference, Job, Meeting, PlatformConnection, User
from app.models.enums import ConnectionState, ExternalTranscriptStatus, JobKind, MeetingPlatform
from app.services import jobs as job_service

logger = logging.getLogger(__name__)

PERMISSION_CATEGORIES = {
    ErrorCategory.admin_approval_required,
    ErrorCategory.insufficient_scope,
    ErrorCategory.no_meeting_access,
}


def connected_connection(db: Session, user_id: uuid.UUID, provider: str) -> PlatformConnection:
    conn = db.scalar(
        select(PlatformConnection).where(PlatformConnection.user_id == user_id, PlatformConnection.provider == provider)
    )
    if conn is None or conn.state not in (ConnectionState.connected, ConnectionState.temporarily_disconnected):
        raise IntegrationError(ErrorCategory.not_connected, "Connect the platform in Integrations first.")
    return conn


def get_ref(db: Session, meeting_id: uuid.UUID) -> ExternalMeetingReference | None:
    return db.scalar(select(ExternalMeetingReference).where(ExternalMeetingReference.meeting_id == meeting_id))


def link(db: Session, meeting: Meeting, user: User, provider: str, reference: str) -> ExternalMeetingReference:
    connector = get_connector(provider)
    conn = connected_connection(db, user.id, provider)
    try:
        resolved = oauth.call_with_token(db, conn, connector, lambda t: connector.resolve_meeting(t, reference[:2048]))
        oauth.mark_success(conn)
    except IntegrationError as err:
        oauth.mark_error(conn, err)
        raise
    if get_ref(db, meeting.id) is not None:
        raise Conflict("This meeting already has a linked source; unlink it first")
    ref = ExternalMeetingReference(
        meeting_id=meeting.id,
        provider=connector.provider,
        connection_id=conn.id,
        linked_by_id=user.id,
        provider_meeting_id=resolved.provider_meeting_id[:512],
        join_url=resolved.join_url,
        resolved_ids=resolved.resolved_ids,
        transcript_status=ExternalTranscriptStatus.unknown,
    )
    savepoint = db.begin_nested()
    try:
        db.add(ref)
        db.flush()
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        # Do not reveal which other meeting/project holds the link.
        raise Conflict("This platform meeting is already linked to another meeting in Memo Hub") from None
    meeting.platform = MeetingPlatform(provider) if provider in MeetingPlatform.__members__ else meeting.platform
    if resolved.join_url and not meeting.meeting_url:
        meeting.meeting_url = resolved.join_url
    return ref


def enqueue_fetch(
    db: Session, ref: ExternalMeetingReference, meeting: Meeting, user_id: uuid.UUID, session_id: uuid.UUID | None
) -> Job:
    ref.transcript_status = ExternalTranscriptStatus.pending
    ref.status_message = "Retrieval queued"
    ref.fetch_attempts = 0
    return job_service.enqueue(
        db,
        kind=JobKind.fetch_transcript,
        user_id=user_id,
        session_id=session_id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        params={"ref_id": str(ref.id)},
    )


def run_fetch(db: Session, job: Job) -> dict[str, Any]:
    """Job handler. Returns a result dict; reschedules itself when the transcript is pending."""
    ref = db.get(ExternalMeetingReference, uuid.UUID(job.params["ref_id"]))
    meeting = db.get(Meeting, job.meeting_id) if job.meeting_id else None
    if ref is None or meeting is None or meeting.deleted_at is not None:
        return {"status": "skipped", "reason": "source unlinked or meeting deleted"}
    assert job.user_id is not None
    connector = get_connector(ref.provider.value)
    ref.fetch_attempts += 1
    ref.last_checked_at = utcnow()
    resolved = ResolvedMeeting(ref.provider_meeting_id, ref.join_url, None, dict(ref.resolved_ids or {}))
    try:
        conn = connected_connection(db, job.user_id, ref.provider.value)
        result = oauth.call_with_token(db, conn, connector, lambda t: connector.fetch_transcript(t, resolved))
        oauth.mark_success(conn)
        conn.last_event_at = utcnow()
    except IntegrationError as err:
        return _handle_failure(db, job, ref, err)

    if result.status == ExternalTranscriptStatus.pending:
        when = next_attempt_at(ref.fetch_attempts)
        ref.transcript_status = ExternalTranscriptStatus.pending if when else ExternalTranscriptStatus.not_available
        ref.status_message = (
            result.message
            if when
            else (f"{result.message} Gave up after {ref.fetch_attempts} attempts; retry later or import the file.")
        )
        ref.next_check_at = when
        if when:
            _reschedule(db, job, when)
        return {
            "status": ref.transcript_status.value,
            "message": ref.status_message,
            "next_check_at": when.isoformat() if when else None,
        }
    if result.status != ExternalTranscriptStatus.available:
        ref.transcript_status = result.status
        ref.status_message = result.message
        ref.next_check_at = None
        return {"status": result.status.value, "message": result.message}

    outcome = ingest_events(db, meeting, result.events)
    ref.transcript_status = ExternalTranscriptStatus.imported
    ref.status_message = f"{result.message} {len(outcome.created)} new, {outcome.duplicates} already imported."
    ref.next_check_at = None
    db.commit()
    note = translate_new_entries(
        db, meeting, outcome.created, user_id=job.user_id, session_id=job.session_id, job_id=job.id
    )
    if note:
        ref.status_message = f"{ref.status_message} {note}"
    log_event(
        logger,
        "integration.fetch.imported",
        provider=ref.provider.value,
        meeting_id=str(meeting.id),
        created=len(outcome.created),
        duplicates=outcome.duplicates,
    )
    return {
        "status": "imported",
        "created": len(outcome.created),
        "duplicates": outcome.duplicates,
        "speaker_attribution": result.speaker_attribution,
        "translation_note": note,
    }


def _handle_failure(db: Session, job: Job, ref: ExternalMeetingReference, err: IntegrationError) -> dict[str, Any]:
    conn = db.get(PlatformConnection, ref.connection_id) if ref.connection_id else None
    if conn is not None:
        oauth.mark_error(conn, err)
    when = next_attempt_at(ref.fetch_attempts, err)
    if err.category in PERMISSION_CATEGORIES:
        ref.transcript_status = ExternalTranscriptStatus.permission_denied
    elif when is None:
        ref.transcript_status = ExternalTranscriptStatus.failed
    ref.status_message = err.message + ("" if when else " Use transcript file import as a fallback.")
    ref.next_check_at = when
    if when is not None:
        _reschedule(db, job, when)
        return {"status": "retry_scheduled", "category": err.category.value, "next_check_at": when.isoformat()}
    log_event(
        logger,
        "integration.fetch.failed",
        provider=ref.provider.value,
        category=err.category.value,
        provider_code=err.provider_code or "",
    )
    db.commit()  # keep the actionable status on the reference when the job fails
    raise err


def _reschedule(db: Session, job: Job, when: Any) -> None:
    """Re-queue the same job for later (does not count as a worker crash attempt)."""
    job.run_after = when
    job.params = {**job.params, "rescheduled": int(job.params.get("rescheduled", 0)) + 1}


def unlink(db: Session, ref: ExternalMeetingReference) -> None:
    db.delete(ref)
