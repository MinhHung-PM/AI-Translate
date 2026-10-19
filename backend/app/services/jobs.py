"""Database-backed job queue.

PostgreSQL ``SELECT ... FOR UPDATE SKIP LOCKED`` gives safe concurrent
claiming without adding Redis. The API enqueues and returns 202; the worker
(``python -m app.worker``) executes. Job status is exposed at
``GET /api/v1/jobs/{id}``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict
from app.db.base import utcnow
from app.models import Job
from app.models.enums import JobKind, JobStatus

ACTIVE = (JobStatus.queued, JobStatus.running)


def find_active_job(db: Session, kind: JobKind, meeting_id: uuid.UUID) -> Job | None:
    return db.scalar(select(Job).where(Job.kind == kind, Job.meeting_id == meeting_id, Job.status.in_(ACTIVE)).limit(1))


def enqueue(
    db: Session,
    *,
    kind: JobKind,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    project_id: uuid.UUID,
    meeting_id: uuid.UUID,
    params: dict[str, Any],
    allow_parallel: bool = False,
) -> Job:
    if not allow_parallel and find_active_job(db, kind, meeting_id) is not None:
        raise Conflict("A job of this type is already running for this meeting")
    job = Job(
        id=uuid.uuid4(),
        kind=kind,
        status=JobStatus.queued,
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        meeting_id=meeting_id,
        params=params,
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, worker_id: str) -> Job | None:
    job = db.scalar(
        select(Job)
        .where(Job.status == JobStatus.queued, or_(Job.run_after.is_(None), Job.run_after <= utcnow()))
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = JobStatus.running
    job.locked_by = worker_id
    job.attempts += 1
    job.started_at = job.started_at or utcnow()
    job.heartbeat_at = utcnow()
    db.commit()
    return job


def heartbeat(db: Session, job: Job, done: int | None = None, total: int | None = None) -> None:
    if done is not None:
        job.progress_done = done
    if total is not None:
        job.progress_total = total
    job.heartbeat_at = utcnow()


def finish(db: Session, job: Job, result: dict[str, Any]) -> None:
    job.status = JobStatus.succeeded
    job.result = result
    job.finished_at = utcnow()


def fail(db: Session, job: Job, code: str, message: str) -> None:
    job.status = JobStatus.failed
    job.error_code = code[:64]
    job.error_message = message[:500]
    job.finished_at = utcnow()
    if job.kind == JobKind.generate_memo and job.meeting_id is not None:
        # Otherwise the memo would stay "generating" and could never be regenerated or edited.
        from app.models import Memo
        from app.models.enums import MemoStatus

        memo = db.scalar(select(Memo).where(Memo.meeting_id == job.meeting_id))
        if memo is not None and memo.status == MemoStatus.generating:
            memo.status = MemoStatus.failed
            memo.generation_error = message[:500]


def requeue_stale(db: Session, stale_after: timedelta = timedelta(minutes=10)) -> int:
    """Jobs whose worker died mid-run are retried up to max_attempts, then failed."""
    cutoff = utcnow() - stale_after
    stale = list(db.scalars(select(Job).where(Job.status == JobStatus.running, Job.heartbeat_at < cutoff)))
    for job in stale:
        if job.attempts < job.max_attempts:
            job.status = JobStatus.queued
        else:
            fail(db, job, "worker_lost", "The worker stopped while processing this job")
    db.commit()
    return len(stale)


def cancel_for_meeting(db: Session, meeting_id: uuid.UUID) -> None:
    db.execute(
        update(Job)
        .where(Job.meeting_id == meeting_id, Job.status == JobStatus.queued)
        .values(status=JobStatus.cancelled, finished_at=utcnow())
    )
