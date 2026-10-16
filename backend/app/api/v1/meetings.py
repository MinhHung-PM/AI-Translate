from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.deps import DB, Auth
from app.api.v1.serializers import meeting_out
from app.core.errors import Forbidden
from app.db.base import utcnow
from app.models import ExternalMeetingReference, Meeting, MeetingParticipant, Memo, Project, TranscriptEntry
from app.models.enums import MeetingPlatform, MeetingStatus, MemoStatus
from app.schemas.api import MeetingIn, MeetingOut, MeetingUpdate
from app.schemas.common import Page, PageParams
from app.services import jobs as job_service
from app.services.audit import record_audit
from app.services.authz import (
    AccessLevel,
    ProjectAccess,
    accessible_project_ids,
    get_project_access,
    load_meeting,
    load_project,
    require_edit_meeting,
)
from app.services.export import export_meeting_record

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("", response_model=Page[MeetingOut])
def list_meetings(
    auth: Auth,
    db: DB,
    pg: PageParams = Depends(),
    q: str | None = Query(default=None, max_length=200),
    project_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: MeetingStatus | None = None,
    memo_status: MemoStatus | None = None,
    platform: MeetingPlatform | None = None,
    sort: Literal["scheduled_desc", "scheduled_asc", "title"] = "scheduled_desc",
) -> Page[MeetingOut]:
    """Meeting history: database-backed pagination, restricted to projects
    the caller may view at summary level."""
    stmt = (
        select(Meeting, Project.name, Memo.status)
        .join(Project, Project.id == Meeting.project_id)
        .outerjoin(Memo, Memo.meeting_id == Meeting.id)
        .where(
            Meeting.deleted_at.is_(None), Meeting.project_id.in_(accessible_project_ids(auth.user, AccessLevel.summary))
        )
    )
    if q:
        stmt = stmt.where(Meeting.title.ilike(f"%{q}%"))
    if project_id:
        stmt = stmt.where(Meeting.project_id == project_id)
    if date_from:
        stmt = stmt.where(Meeting.scheduled_at >= date_from)
    if date_to:
        stmt = stmt.where(Meeting.scheduled_at <= date_to)
    if status:
        stmt = stmt.where(Meeting.status == status)
    if memo_status:
        stmt = stmt.where(Memo.status == memo_status)
    if platform:
        stmt = stmt.where(Meeting.platform == platform)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order: Any = {
        "scheduled_desc": Meeting.scheduled_at.desc(),
        "scheduled_asc": Meeting.scheduled_at.asc(),
        "title": Meeting.title.asc(),
    }[sort]
    rows = db.execute(stmt.order_by(order, Meeting.id).offset(pg.offset).limit(pg.page_size)).all()
    ids = [m.id for m, _, _ in rows]
    counts = (
        dict(
            db.execute(
                select(TranscriptEntry.meeting_id, func.count())
                .where(TranscriptEntry.meeting_id.in_(ids))
                .group_by(TranscriptEntry.meeting_id)
            ).all()
        )
        if ids
        else {}
    )
    linked_ids = (
        set(
            db.scalars(
                select(ExternalMeetingReference.meeting_id).where(ExternalMeetingReference.meeting_id.in_(ids))
            ).all()
        )
        if ids
        else set()
    )
    access_cache: dict[uuid.UUID, ProjectAccess] = {}
    items = []
    for meeting, project_name, m_status in rows:
        if meeting.project_id not in access_cache:
            access_cache[meeting.project_id] = get_project_access(db, auth.user, meeting.project)
        items.append(
            meeting_out(
                db,
                meeting,
                access_cache[meeting.project_id],
                auth.user,
                project_name=project_name,
                memo_status=m_status,
                entry_count=counts.get(meeting.id, 0),
                linked=meeting.id in linked_ids,
            )
        )
    return Page(items=items, total=total, page=pg.page, page_size=pg.page_size)


@router.post("", response_model=MeetingOut, status_code=201)
def create_meeting(body: MeetingIn, auth: Auth, db: DB) -> MeetingOut:
    project, access = load_project(db, auth.user, body.project_id, AccessLevel.contribute)
    data = body.model_dump(exclude={"participants", "meeting_url"})
    meeting = Meeting(
        **data,
        meeting_url=str(body.meeting_url) if body.meeting_url else None,
        created_by_id=auth.user.id,
        status=MeetingStatus.planned,
    )
    meeting.participants = [MeetingParticipant(**p.model_dump(), sort_order=i) for i, p in enumerate(body.participants)]
    db.add(meeting)
    db.flush()
    record_audit(
        db,
        actor_id=auth.user.id,
        action="meeting.create",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=project.id,
        details={"platform": body.platform.value},
        ip=auth.ip,
    )
    db.commit()
    return meeting_out(db, meeting, access, auth.user)


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: uuid.UUID, auth: Auth, db: DB) -> MeetingOut:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.summary)
    return meeting_out(db, meeting, access, auth.user)


@router.patch("/{meeting_id}", response_model=MeetingOut)
def update_meeting(meeting_id: uuid.UUID, body: MeetingUpdate, auth: Auth, db: DB) -> MeetingOut:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    changes = body.model_dump(exclude_unset=True, exclude={"participants", "meeting_url"})
    for key, value in changes.items():
        setattr(meeting, key, value)
    if "meeting_url" in body.model_fields_set:
        meeting.meeting_url = str(body.meeting_url) if body.meeting_url else None
    if body.participants is not None:
        meeting.participants = [
            MeetingParticipant(**p.model_dump(), sort_order=i) for i, p in enumerate(body.participants)
        ]
    record_audit(
        db,
        actor_id=auth.user.id,
        action="meeting.update",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"fields": sorted(body.model_fields_set)},
        ip=auth.ip,
    )
    db.commit()
    db.refresh(meeting)
    return meeting_out(db, meeting, access, auth.user)


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: uuid.UUID, auth: Auth, db: DB) -> None:
    """Soft delete; content is hard-deleted by the retention job after a grace period."""
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    if not (access.is_manager or meeting.created_by_id == auth.user.id):
        raise Forbidden("Only the meeting creator or a project manager can delete this meeting")
    meeting.deleted_at = utcnow()
    meeting.status = MeetingStatus.archived
    job_service.cancel_for_meeting(db, meeting.id)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="meeting.delete",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()


@router.get("/{meeting_id}/export")
def export_meeting(meeting_id: uuid.UUID, auth: Auth, db: DB, format: Literal["md", "csv", "json"] = "md") -> Response:
    """Export the meeting record (metadata, transcript, translations). Requires transcript access."""
    meeting, _ = load_meeting(db, auth.user, meeting_id, AccessLevel.transcript)
    content, media_type, ext = export_meeting_record(db, meeting, format)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="meeting.export",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"format": format},
        ip=auth.ip,
    )
    db.commit()
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="meeting-{meeting.id}.{ext}"'},
    )
