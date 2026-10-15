"""Dashboard aggregates. Every figure is computed from stored data and is
restricted to projects the caller can view at summary level."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.models import ActionItem, AuditEvent, Issue, Meeting, Memo, Project, Risk, User
from app.models.enums import ActionStatus, MeetingStatus, MemoStatus, Priority, VerificationStatus
from app.services.authz import AccessLevel, accessible_project_ids
from app.services.usage import summarize_usage


def dashboard(
    db: Session,
    user: User,
    *,
    project_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    meeting_status: MeetingStatus | None,
    memo_status: MemoStatus | None,
    owner: str | None,
) -> dict[str, Any]:
    allowed = accessible_project_ids(user, AccessLevel.summary)
    m_filters: list[ColumnElement[bool]] = [Meeting.deleted_at.is_(None), Meeting.project_id.in_(allowed)]
    if project_id:
        m_filters.append(Meeting.project_id == project_id)
    if date_from:
        m_filters.append(Meeting.scheduled_at >= date_from)
    if date_to:
        m_filters.append(Meeting.scheduled_at <= date_to)
    if meeting_status:
        m_filters.append(Meeting.status == meeting_status)
    meeting_where = and_(*m_filters)
    memo_join = select(Meeting.id).outerjoin(Memo, Memo.meeting_id == Meeting.id).where(meeting_where)
    if memo_status:
        memo_join = memo_join.where(Memo.status == memo_status)
    meeting_ids = memo_join.subquery()

    total_meetings = db.scalar(select(func.count()).select_from(meeting_ids)) or 0
    drafts_awaiting = (
        db.scalar(
            select(func.count())
            .select_from(Memo)
            .where(
                Memo.meeting_id.in_(select(meeting_ids.c.id)),
                Memo.status.in_([MemoStatus.draft, MemoStatus.in_review]),
            )
        )
        or 0
    )

    a_filters: list[ColumnElement[bool]] = [
        ActionItem.meeting_id.in_(select(meeting_ids.c.id)),
        ActionItem.verification_status != VerificationStatus.rejected,
        ActionItem.status.not_in([ActionStatus.done, ActionStatus.cancelled]),
    ]
    if owner:
        a_filters.append(ActionItem.owner_text.ilike(f"%{owner[:100]}%"))
    open_actions = db.scalar(select(func.count()).select_from(ActionItem).where(*a_filters)) or 0
    overdue_actions = (
        db.scalar(select(func.count()).select_from(ActionItem).where(*a_filters, ActionItem.due_date < date.today()))
        or 0
    )
    unconfirmed_actions = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(
                *a_filters,
                ActionItem.verification_status.in_([VerificationStatus.draft, VerificationStatus.needs_review]),
            )
        )
        or 0
    )

    high = [Priority.high, Priority.critical]
    issues = db.execute(
        select(Issue.id, Issue.code, Issue.description, Issue.priority, Issue.meeting_id, Meeting.title)
        .join(Meeting, Meeting.id == Issue.meeting_id)
        .where(
            Issue.meeting_id.in_(select(meeting_ids.c.id)),
            Issue.priority.in_(high),
            Issue.verification_status != VerificationStatus.rejected,
            Issue.status != "resolved",
        )
        .order_by(Issue.created_at.desc())
        .limit(10)
    ).all()
    risks = db.execute(
        select(Risk.id, Risk.code, Risk.description, Risk.severity, Risk.meeting_id, Meeting.title)
        .join(Meeting, Meeting.id == Risk.meeting_id)
        .where(
            Risk.meeting_id.in_(select(meeting_ids.c.id)),
            Risk.severity.in_(high),
            Risk.verification_status != VerificationStatus.rejected,
        )
        .order_by(Risk.created_at.desc())
        .limit(10)
    ).all()
    recent = db.execute(
        select(Meeting.id, Meeting.title, Meeting.scheduled_at, Meeting.status, Project.name, Memo.status)
        .join(Project, Project.id == Meeting.project_id)
        .outerjoin(Memo, Memo.meeting_id == Meeting.id)
        .where(Meeting.id.in_(select(meeting_ids.c.id)))
        .order_by(Meeting.scheduled_at.desc())
        .limit(8)
    ).all()
    activity_q = (
        select(
            AuditEvent.action,
            AuditEvent.created_at,
            AuditEvent.resource_type,
            AuditEvent.resource_id,
            Project.name,
            User.display_name,
        )
        .join(Project, Project.id == AuditEvent.project_id)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.project_id.in_(allowed))
    )
    if project_id:
        activity_q = activity_q.where(AuditEvent.project_id == project_id)
    activity = db.execute(activity_q.order_by(AuditEvent.created_at.desc()).limit(10)).all()
    usage = summarize_usage(db, user, project_id=project_id, date_from=date_from, date_to=date_to)

    return {
        "total_meetings": total_meetings,
        "drafts_awaiting_review": drafts_awaiting,
        "open_action_items": open_actions,
        "overdue_action_items": overdue_actions,
        "unconfirmed_action_items": unconfirmed_actions,
        "high_priority_issues": [
            {"id": r[0], "code": r[1], "description": r[2], "priority": r[3], "meeting_id": r[4], "meeting_title": r[5]}
            for r in issues
        ],
        "high_priority_risks": [
            {"id": r[0], "code": r[1], "description": r[2], "severity": r[3], "meeting_id": r[4], "meeting_title": r[5]}
            for r in risks
        ],
        "recent_meetings": [
            {"id": r[0], "title": r[1], "scheduled_at": r[2], "status": r[3], "project_name": r[4], "memo_status": r[5]}
            for r in recent
        ],
        "recent_activity": [
            {
                "action": r[0],
                "created_at": r[1],
                "resource_type": r[2],
                "resource_id": r[3],
                "project_name": r[4],
                "actor": r[5],
            }
            for r in activity
        ],
        "usage": {
            "total_requests": usage["total_requests"],
            "estimated_cost_usd": usage["estimated_cost_usd"],
            "failed_requests": usage["failed_requests"],
        },
    }
