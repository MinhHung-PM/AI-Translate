from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, text

from app.api.deps import DB, Auth
from app.connectors.registry import list_connector_statuses
from app.core.errors import NotFound
from app.models import Job
from app.models.enums import MeetingStatus, MemoStatus
from app.schemas.api import ConnectorStatusOut, JobOut, ProfileUpdate, UsageSummaryOut, UserOut
from app.services.authz import AccessLevel, load_meeting
from app.services.dashboard import dashboard
from app.services.usage import summarize_usage

router = APIRouter(tags=["misc"])

COST_NOTE = (
    "Estimated Cost is computed from token counts and configured prices. With your own API key (BYOK), "
    "actual billing happens on your provider account and may differ; this application cannot see it."
)


@router.get("/users/me", response_model=UserOut, tags=["users"])
def get_me(auth: Auth) -> Any:
    return auth.user


@router.patch("/users/me", response_model=UserOut, tags=["users"])
def update_me(body: ProfileUpdate, auth: Auth, db: DB) -> Any:
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(auth.user, key, value)
    db.commit()
    return auth.user


@router.get("/dashboard", tags=["dashboard"])
def get_dashboard(
    auth: Auth,
    db: DB,
    project_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    meeting_status: MeetingStatus | None = None,
    memo_status: MemoStatus | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    return dashboard(
        db,
        auth.user,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        meeting_status=meeting_status,
        memo_status=memo_status,
        owner=owner,
    )


@router.get("/usage/summary", response_model=UsageSummaryOut, tags=["usage"])
def usage_summary(
    auth: Auth,
    db: DB,
    project_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> UsageSummaryOut:
    data = summarize_usage(db, auth.user, project_id=project_id, date_from=date_from, date_to=date_to)
    return UsageSummaryOut(**data, cost_note=COST_NOTE)


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def get_job(job_id: uuid.UUID, auth: Auth, db: DB) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.meeting_id is None:
        raise NotFound("Job not found")
    load_meeting(db, auth.user, job.meeting_id, AccessLevel.summary)
    return job


@router.get("/meetings/{meeting_id}/jobs", response_model=list[JobOut], tags=["jobs"])
def meeting_jobs(meeting_id: uuid.UUID, auth: Auth, db: DB) -> list[Job]:
    load_meeting(db, auth.user, meeting_id, AccessLevel.summary)
    return list(db.scalars(select(Job).where(Job.meeting_id == meeting_id).order_by(Job.created_at.desc()).limit(20)))


@router.get("/connectors", response_model=list[ConnectorStatusOut], tags=["connectors"])
def connectors(auth: Auth) -> list[Any]:
    return list_connector_statuses()


health_router = APIRouter(tags=["health"])


@health_router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready")
def ready(db: DB) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
