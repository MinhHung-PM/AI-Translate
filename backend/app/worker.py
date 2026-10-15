"""Background worker: ``python -m app.worker``.

Claims queued jobs from PostgreSQL and runs them. Also performs periodic
maintenance (expired-session purge, which deletes session-only API keys,
and data-retention enforcement).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import ProviderError
from app.connectors.base import TranscriptEvent
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, log_event
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.models import Job, LiveSession, Meeting, Memo, Project, TranscriptEntry
from app.models.enums import JobKind, JobStatus, Language, LiveSessionStatus, MemoStatus, TranslationStatus
from app.services import jobs as job_service
from app.services.ingestion import ingest_event
from app.services.memo_generation import MemoGenerationFailed, run_memo_generation
from app.services.provider_config import resolve_provider
from app.services.retention import enforce_retention
from app.services.sessions import purge_expired_sessions
from app.services.translation import translate_entries

logger = logging.getLogger("app.worker")


def _load(db: Session, job: Job) -> tuple[Meeting, Project]:
    meeting = db.get(Meeting, job.meeting_id)
    if meeting is None or meeting.deleted_at is not None:
        raise AppError("Meeting no longer exists")
    project = db.get(Project, meeting.project_id)
    assert project is not None
    return meeting, project


def handle_translate(db: Session, job: Job) -> dict[str, Any]:
    meeting, project = _load(db, job)
    assert job.user_id is not None
    target = Language(job.params["target_language"])
    q = select(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id).order_by(TranscriptEntry.sequence)
    entries = list(db.scalars(q))
    selected = set(job.params.get("entry_ids") or [])
    if selected:
        entries = [e for e in entries if str(e.id) in selected]
    if job.params.get("only_failed"):
        entries = [
            e
            for e in entries
            if any(t.target_language == target and t.status == TranslationStatus.failed for t in e.translations)
        ]
    resolved = resolve_provider(db, job.user_id, job.session_id)

    def progress(done: int, total: int) -> None:
        job_service.heartbeat(db, job, done, total)

    job_service.heartbeat(db, job, 0, len(entries))
    db.commit()
    outcome = translate_entries(
        db,
        meeting=meeting,
        project=project,
        entries=entries,
        target=target,
        resolved=resolved,
        user_id=job.user_id,
        job_id=job.id,
        force=bool(job.params.get("force")),
        on_progress=progress,
    )
    job_service.heartbeat(db, job, len(entries), len(entries))
    result = {
        "translated": outcome.translated,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "chunks": outcome.chunks,
        "errors": outcome.errors[:5],
    }
    if outcome.failed and not outcome.translated:
        raise AppError(outcome.errors[0] if outcome.errors else "Translation failed", details=result)
    return result


def handle_generate_memo(db: Session, job: Job) -> dict[str, Any]:
    meeting, project = _load(db, job)
    assert job.user_id is not None
    memo = db.scalar(select(Memo).where(Memo.meeting_id == meeting.id))
    if memo is None:
        raise AppError("Memo placeholder missing")
    try:
        resolved = resolve_provider(db, job.user_id, job.session_id)
    except AppError as exc:
        memo.status = MemoStatus.failed
        memo.generation_error = exc.message[:500]
        db.commit()
        raise
    job_service.heartbeat(db, job, 0, 1)
    run_memo_generation(
        db, memo=memo, meeting=meeting, project=project, resolved=resolved, user_id=job.user_id, job_id=job.id
    )
    job_service.heartbeat(db, job, 1, 1)
    return {"memo_id": str(memo.id)}


def handle_replay(db: Session, job: Job, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Replay (DEMO): emits stored events one by one through the same
    ingestion path that real connectors will use, translating as it goes."""
    meeting, project = _load(db, job)
    assert job.user_id is not None
    live = db.get(LiveSession, uuid.UUID(job.params["live_session_id"]))
    assert live is not None
    interval = float(job.params.get("interval_seconds", 1.0))
    target = Language(job.params["target_language"])
    resolved = None
    translate_note = None
    if job.params.get("translate", True):
        try:
            resolved = resolve_provider(db, job.user_id, job.session_id)
        except AppError as exc:
            translate_note = exc.message
    events = job.params.get("events", [])
    job_service.heartbeat(db, job, 0, len(events))
    db.commit()
    emitted = 0
    for raw in events:
        db.refresh(live)
        if live.status != LiveSessionStatus.running:
            break
        entry = ingest_event(db, meeting, TranscriptEvent.model_validate(raw))
        live.entries_emitted += 1
        emitted += 1
        job_service.heartbeat(db, job, emitted, len(events))
        db.commit()
        if entry is not None and resolved is not None:
            translate_entries(
                db,
                meeting=meeting,
                project=project,
                entries=[entry],
                target=target,
                resolved=resolved,
                user_id=job.user_id,
                job_id=job.id,
            )
        if interval > 0:
            sleep(interval)
    if live.status == LiveSessionStatus.running:
        live.status = LiveSessionStatus.completed
    live.ended_at = utcnow()
    db.commit()
    return {"emitted": emitted, "translation_note": translate_note}


HANDLERS: dict[JobKind, Callable[[Session, Job], dict[str, Any]]] = {
    JobKind.translation: handle_translate,
    JobKind.generate_memo: handle_generate_memo,
    JobKind.replay: handle_replay,
}


def execute(db: Session, job: Job) -> None:
    started = time.monotonic()
    try:
        result = HANDLERS[job.kind](db, job)
        db.refresh(job)
        job_service.finish(db, job, result)
        db.commit()
        log_event(
            logger,
            "job.succeeded",
            job_id=str(job.id),
            kind=job.kind.value,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (AppError, MemoGenerationFailed, ProviderError) as exc:
        db.rollback()
        code = getattr(exc, "code", "error")
        job = db.get(Job, job.id) or job
        job_service.fail(db, job, str(code), getattr(exc, "message", str(exc)))
        _mark_live_failed(db, job)
        db.commit()
        log_event(logger, "job.failed", job_id=str(job.id), kind=job.kind.value, code=str(code))
    except Exception:
        db.rollback()
        logger.exception("Job crashed: %s", job.id)
        job = db.get(Job, job.id) or job
        job_service.fail(db, job, "internal_error", "Unexpected error while processing the job")
        _mark_live_failed(db, job)
        memo = (
            db.scalar(select(Memo).where(Memo.meeting_id == job.meeting_id))
            if job.kind == JobKind.generate_memo
            else None
        )
        if memo is not None and memo.status == MemoStatus.generating:
            memo.status = MemoStatus.failed
            memo.generation_error = "Unexpected error while generating the memo"
        db.commit()


def _mark_live_failed(db: Session, job: Job) -> None:
    if job.kind == JobKind.replay and "live_session_id" in job.params:
        live = db.get(LiveSession, uuid.UUID(job.params["live_session_id"]))
        if live is not None and live.status == LiveSessionStatus.running:
            live.status = LiveSessionStatus.failed
            live.ended_at = utcnow()


def run_pending(db_factory: Callable[[], Session] | None = None, worker_id: str = "inline", limit: int = 100) -> int:
    """Run queued jobs until none remain (used by tests and the embedded worker)."""
    factory = db_factory or get_sessionmaker()
    count = 0
    while count < limit:
        with factory() as db:
            job = job_service.claim_next(db, worker_id)
            if job is None:
                return count
            execute(db, job)
            count += 1
    return count


def maintenance() -> None:
    with get_sessionmaker()() as db:
        purge_expired_sessions(db)
        enforce_retention(db)
        db.commit()
        job_service.requeue_stale(db, timedelta(minutes=10))


class Worker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}"
        self._stop = threading.Event()

    def stop(self, *_: Any) -> None:
        self._stop.set()

    def run(self) -> None:
        settings = get_settings()
        log_event(logger, "worker.started", worker_id=self.worker_id)
        last_maintenance = 0.0
        while not self._stop.is_set():
            if time.monotonic() - last_maintenance > 300:
                try:
                    maintenance()
                except Exception:
                    logger.exception("Maintenance failed")
                last_maintenance = time.monotonic()
            try:
                ran = run_pending(worker_id=self.worker_id, limit=10)
            except Exception:
                logger.exception("Worker loop error")
                ran = 0
            if not ran:
                self._stop.wait(settings.worker_poll_seconds)


def start_embedded_worker() -> Worker:
    worker = Worker()
    threading.Thread(target=worker.run, name="embedded-worker", daemon=True).start()
    return worker


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_environment()
    worker = Worker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":
    main()


__all__ = ["JobStatus", "execute", "main", "run_pending"]
