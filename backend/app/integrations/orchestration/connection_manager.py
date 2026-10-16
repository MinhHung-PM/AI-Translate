"""Real-time ingestion (Zoom RTMS) and provider webhook dispatch.

Flow::

  user arms live on a linked meeting  ──►  LiveSession(status=waiting, requested_session_id)
  Zoom: signed webhook meeting.rtms_started ──► API verifies + dedups ──► realtime_ingest job
  worker job ──► RealtimeSession thread ──► RtmsStream (official SDK)
        transcript callback ──► bounded queue ──► processor thread:
             order (bounded buffer) → dedup → persist → translate (existing pipeline)
  UI polls GET /meetings/{id}/live (same feed as the replay demo)

Backpressure: the SDK callback never waits on the AI provider. If the bounded
queue is full, the segment is persisted immediately on the receiving thread
(no loss) and its translation is deferred to the processor's catch-up pass.
Stop requests are written to the database by the API; the session thread
checks them, so control works across processes.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import log_event
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.models import CanonicalEvent
from app.integrations.normalization.ordering import OrderingBuffer
from app.integrations.orchestration.meeting_ingestion_service import ingest_events, translate_new_entries
from app.integrations.zoom.rtms import (
    RtmsClientLike,
    RtmsJoinParams,
    RtmsStream,
    RtmsTranscript,
    default_client_factory,
)
from app.models import (
    ExternalMeetingReference,
    Job,
    LiveSession,
    Meeting,
    ProviderEvent,
    TranscriptEntry,
    User,
    UserSession,
)
from app.models.enums import JobKind, LiveSessionStatus, PlatformProvider, ProviderEventStatus
from app.services import jobs as job_service
from app.services.transcripts.normalize import detect_language

logger = logging.getLogger(__name__)

ACTIVE_LIVE = (LiveSessionStatus.waiting, LiveSessionStatus.running, LiveSessionStatus.interrupted)

# Factory hook for tests (substitutes a fake SDK client).
rtms_client_factory: Callable[[], RtmsClientLike] = default_client_factory


# ---- arming (API process) -------------------------------------------------------


def arm_live(
    db: Session, meeting: Meeting, ref: ExternalMeetingReference, user: User, session: UserSession
) -> LiveSession:
    existing = db.scalar(
        select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status.in_(ACTIVE_LIVE))
    )
    if existing is not None:
        return existing
    ref.live_requested = True
    live = LiveSession(
        id=uuid.uuid4(),
        meeting_id=meeting.id,
        connector=ref.provider.value,
        is_demo=False,
        status=LiveSessionStatus.waiting,
        requested_session_id=session.id,
        created_by_id=user.id,
        status_message="Waiting for the host to start Realtime Media Streams in Zoom.",
    )
    db.add(live)
    db.flush()
    return live


def stop_live(db: Session, meeting: Meeting) -> int:
    ref = db.scalar(select(ExternalMeetingReference).where(ExternalMeetingReference.meeting_id == meeting.id))
    if ref is not None:
        ref.live_requested = False
    count = 0
    for live in db.scalars(
        select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status.in_(ACTIVE_LIVE))
    ):
        live.status = LiveSessionStatus.stopped
        live.ended_at = utcnow()
        live.status_message = "Stopped by user"
        count += 1
    return count


# ---- webhook dispatch (API process) -------------------------------------------------


def record_provider_event(
    db: Session, provider: PlatformProvider, dedup_key: str, event_type: str
) -> ProviderEvent | None:
    """Insert the event log row; returns None when this event was already received (replay)."""
    if db.scalar(
        select(ProviderEvent.id).where(ProviderEvent.provider == provider, ProviderEvent.dedup_key == dedup_key)
    ):
        return None
    ev = ProviderEvent(provider=provider, dedup_key=dedup_key, event_type=event_type[:100])
    db.add(ev)
    db.flush()
    return ev


def _find_zoom_ref(db: Session, body: dict[str, Any]) -> ExternalMeetingReference | None:
    obj = body.get("object") or {}
    meeting_uuid = str(body.get("meeting_uuid") or obj.get("uuid") or "")
    meeting_id = str(obj.get("id") or body.get("meeting_id") or "")
    refs = db.scalars(
        select(ExternalMeetingReference).where(ExternalMeetingReference.provider == PlatformProvider.zoom)
    )
    for ref in refs:
        if (meeting_id and ref.provider_meeting_id == meeting_id) or (
            meeting_uuid and (ref.resolved_ids or {}).get("uuid") == meeting_uuid
        ):
            return ref
    return None


def dispatch_zoom_event(db: Session, payload: dict[str, Any], ev: ProviderEvent) -> str:
    event = str(payload.get("event", ""))
    body = payload.get("payload") or {}
    ref = _find_zoom_ref(db, body)
    if ref is None:
        ev.status = ProviderEventStatus.ignored
        ev.detail = "No meeting in Memo Hub is linked to this Zoom meeting"
        return ev.detail
    ev.meeting_id = ref.meeting_id
    meeting = db.get(Meeting, ref.meeting_id)
    if meeting is None or meeting.deleted_at is not None:
        ev.status = ProviderEventStatus.ignored
        ev.detail = "Linked meeting was deleted"
        return ev.detail
    if event == "meeting.rtms_started":
        live = db.scalar(
            select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status.in_(ACTIVE_LIVE))
        )
        if not ref.live_requested or live is None:
            ev.status = ProviderEventStatus.ignored
            ev.detail = "Live ingestion was not requested for the linked meeting"
            return ev.detail
        stream_id = str(body.get("rtms_stream_id") or "")
        server_urls = str(body.get("server_urls") or "")
        meeting_uuid = str(body.get("meeting_uuid") or "")
        if not (stream_id and server_urls and meeting_uuid):
            ev.status = ProviderEventStatus.failed
            ev.detail = "RTMS start event did not include stream details"
            live.status_message = ev.detail
            return ev.detail
        live.provider_session_id = stream_id[:255]
        live.status_message = "RTMS started by Zoom; connecting…"
        job = job_service.enqueue(
            db,
            kind=JobKind.realtime_ingest,
            user_id=live.created_by_id or ref.linked_by_id,  # type: ignore[arg-type]
            session_id=live.requested_session_id,
            project_id=meeting.project_id,
            meeting_id=meeting.id,
            params={
                "live_session_id": str(live.id),
                "meeting_uuid": meeting_uuid,
                "rtms_stream_id": stream_id,
                "server_urls": server_urls,
            },
            allow_parallel=True,
        )
        live.job_id = job.id
        ev.status = ProviderEventStatus.processed
        ev.detail = "Live ingestion queued"
    elif event == "meeting.rtms_stopped":
        for live in db.scalars(
            select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status.in_(ACTIVE_LIVE))
        ):
            live.status = LiveSessionStatus.completed
            live.ended_at = utcnow()
            live.status_message = "Zoom stopped the RTMS stream"
        ev.status = ProviderEventStatus.processed
        ev.detail = "Live ingestion stopped"
    elif event == "recording.transcript_completed":
        from app.integrations.orchestration.external_source_service import enqueue_fetch

        if ref.linked_by_id is not None:
            enqueue_fetch(db, ref, meeting, ref.linked_by_id, None)
        ev.status = ProviderEventStatus.processed
        ev.detail = "Transcript retrieval queued"
    else:
        ev.status = ProviderEventStatus.ignored
        ev.detail = "Event type not used"
    return ev.detail or ""


# ---- realtime sessions (worker process) -------------------------------------------------

_sessions: dict[uuid.UUID, RealtimeSession] = {}
_lock = threading.Lock()


class RealtimeSession:
    def __init__(
        self,
        live_id: uuid.UUID,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None,
        params: RtmsJoinParams,
        provider_meeting_id: str,
    ) -> None:
        self.live_id = live_id
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.session_id = session_id
        self.provider_meeting_id = provider_meeting_id
        self.queue: queue.Queue[CanonicalEvent] = queue.Queue(maxsize=get_settings().realtime_queue_max)
        self.overflow_entries: list[uuid.UUID] = []
        self._overflow_lock = threading.Lock()
        self._seq = 0
        self._first_ts: int | None = None
        self._stop = threading.Event()
        s = get_settings()
        self.stream = RtmsStream(
            params,
            client_id=s.zoom_client_id,
            client_secret=s.zoom_client_secret,
            on_transcript=self.on_transcript,
            on_state=self.on_state,
            client_factory=rtms_client_factory,
        )
        self.processor = threading.Thread(target=self._process_loop, name=f"rt-proc-{str(live_id)[:8]}", daemon=True)

    # receiving thread (SDK callback): must stay fast
    def on_transcript(self, t: RtmsTranscript) -> None:
        self._seq += 1
        if t.timestamp is not None and self._first_ts is None:
            self._first_ts = t.timestamp
        offset = t.timestamp - self._first_ts if t.timestamp is not None and self._first_ts is not None else None
        event = CanonicalEvent(
            provider="zoom",
            provider_meeting_id=self.provider_meeting_id,
            speaker_id=t.user_id,
            speaker_display_name=t.user_name,
            start_timestamp_ms=offset if offset is not None and offset >= 0 else None,
            original_text=t.text,
            source_language=detect_language(t.text),
            provider_sequence=self._seq,
            source_metadata={"rtms_stream_id": self.stream.params.rtms_stream_id, "sdk_timestamp": t.timestamp},
        )
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            # Backpressure: persist now (fast), translate later. Never drop a segment.
            with get_sessionmaker()() as db:
                meeting = db.get(Meeting, self.meeting_id)
                if meeting is not None:
                    out = ingest_events(db, meeting, [event], ordered=False)
                    db.commit()
                    with self._overflow_lock:
                        self.overflow_entries += [e.id for e in out.created]

    def on_state(self, state: str, message: str) -> None:
        # "ended" is finalised by the processor after it has drained and translated
        # the last segments, so the UI never shows "completed" while data is in flight.
        mapping = {
            "connected": LiveSessionStatus.running,
            "failed": LiveSessionStatus.failed,
            "interrupted": LiveSessionStatus.interrupted,
        }
        with get_sessionmaker()() as db:
            live = db.get(LiveSession, self.live_id)
            if live is None:
                return
            if live.status != LiveSessionStatus.stopped:
                live.status = mapping.get(state, live.status)
            live.status_message = message
            if state == "failed":
                live.ended_at = utcnow()
            db.commit()
        if state in ("ended", "failed", "interrupted"):
            self._stop.set()

    def start(self) -> None:
        self.processor.start()
        self.stream.start()

    def stop(self) -> None:
        self._stop.set()
        self.stream.stop()

    def _stopped_in_db(self, db: Session) -> bool:
        live = db.get(LiveSession, self.live_id)
        return live is None or live.status in (
            LiveSessionStatus.stopped,
            LiveSessionStatus.completed,
            LiveSessionStatus.failed,
        )

    def _process_loop(self) -> None:
        buffer = OrderingBuffer()
        last_check = 0.0
        try:
            while True:
                batch: list[CanonicalEvent] = []
                try:
                    batch += buffer.add(self.queue.get(timeout=0.3))
                    while len(batch) < 20:
                        batch += buffer.add(self.queue.get_nowait())
                except queue.Empty:
                    batch += buffer.release()
                if time.monotonic() - last_check > 2:
                    last_check = time.monotonic()
                    with get_sessionmaker()() as db:
                        if self._stopped_in_db(db):
                            self.stop()
                done = self._stop.is_set() or self.stream.stopped
                if done:  # drain and flush everything still buffered before exiting
                    while not self.queue.empty():
                        batch += buffer.add(self.queue.get_nowait())
                    batch += buffer.flush()
                self._persist_and_translate(batch)
                if done:
                    break
        finally:
            with get_sessionmaker()() as db:
                live = db.get(LiveSession, self.live_id)
                if live is not None and live.status in (LiveSessionStatus.running, LiveSessionStatus.waiting):
                    live.status = LiveSessionStatus.completed
                if live is not None and live.ended_at is None:
                    live.ended_at = utcnow()
                db.commit()
            with _lock:
                _sessions.pop(self.live_id, None)

    def _persist_and_translate(self, batch: list[CanonicalEvent]) -> None:
        with self._overflow_lock:
            deferred, self.overflow_entries = self.overflow_entries, []
        if not batch and not deferred:
            return
        with get_sessionmaker()() as db:
            meeting = db.get(Meeting, self.meeting_id)
            live = db.get(LiveSession, self.live_id)
            if meeting is None or live is None:
                return
            out = ingest_events(db, meeting, batch, ordered=False) if batch else None
            created = list(out.created) if out else []
            live.entries_emitted += len(created)
            live.last_event_at = utcnow()
            db.commit()
            entries = created + [e for e in (db.get(TranscriptEntry, i) for i in deferred) if e is not None]
            note = translate_new_entries(
                db, meeting, entries, user_id=self.user_id, session_id=self.session_id, job_id=None
            )
            if note and live.status_message != note:
                live.status_message = note
            db.commit()


def run_realtime(db: Session, job: Job) -> dict[str, Any]:
    """Worker job handler: start the session thread and return immediately."""
    live = db.get(LiveSession, uuid.UUID(job.params["live_session_id"]))
    if live is None or live.status in (LiveSessionStatus.stopped, LiveSessionStatus.completed):
        return {"status": "skipped"}
    ref = db.scalar(select(ExternalMeetingReference).where(ExternalMeetingReference.meeting_id == live.meeting_id))
    if ref is None:
        raise IntegrationError(ErrorCategory.meeting_not_found, "The meeting is no longer linked to Zoom")
    assert job.user_id is not None
    from app.integrations.registry import get_connector

    problems = get_connector("zoom").live_problems()  # type: ignore[attr-defined]
    if problems:
        live.status = LiveSessionStatus.failed
        live.status_message = "Zoom RTMS is not configured on this server"
        raise IntegrationError(ErrorCategory.not_configured, "Zoom RTMS is not configured on this server")
    with _lock:
        if live.id in _sessions:
            return {"status": "already_running"}
        session = RealtimeSession(
            live.id,
            live.meeting_id,
            job.user_id,
            job.session_id,
            RtmsJoinParams(job.params["meeting_uuid"], job.params["rtms_stream_id"], job.params["server_urls"]),
            ref.provider_meeting_id,
        )
        _sessions[live.id] = session
    if live.status == LiveSessionStatus.interrupted:
        live.reconnect_count += 1
    live.status = LiveSessionStatus.running
    live.status_message = "Connecting to Zoom RTMS…"
    db.commit()
    session.start()
    log_event(logger, "realtime.started", meeting_id=str(live.meeting_id), live_session_id=str(live.id))
    return {"status": "started"}


def active_sessions() -> list[uuid.UUID]:
    with _lock:
        return list(_sessions)


def stop_all() -> None:
    with _lock:
        sessions = list(_sessions.values())
    for s in sessions:
        s.stop()


def recover_interrupted(db: Session) -> int:
    """After a worker restart, sessions that were running in a dead process are
    marked interrupted with an explanation. Zoom does not replay missed segments;
    they can be recovered from the post-meeting transcript."""
    count = 0
    for live in db.scalars(
        select(LiveSession).where(LiveSession.status == LiveSessionStatus.running, LiveSession.connector == "zoom")
    ):
        if live.id not in _sessions:
            live.status = LiveSessionStatus.interrupted
            live.status_message = (
                "The worker restarted; live ingestion stopped. Retrieve the post-meeting transcript to fill any gap."
            )
            count += 1
    return count
