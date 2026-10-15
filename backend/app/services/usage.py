"""UsageMeter: records every AI operation and summarizes estimated cost.

Costs are always *estimates* from configured prices × token counts. For
BYOK keys, actual billing happens on the user's provider account and is not
visible to this application.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import ColumnElement, and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from app.ai.base import TokenUsage
from app.ai.catalog import estimate_cost
from app.models import Meeting, Project, UsageRecord, User
from app.models.enums import GlobalRole
from app.services.authz import AccessLevel, accessible_project_ids


@dataclass
class UsageContext:
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    meeting_id: uuid.UUID | None
    job_id: uuid.UUID | None
    provider: str
    model: str
    key_source: str


class UsageMeter(Protocol):
    def record(
        self,
        ctx: UsageContext,
        operation: str,
        usage: TokenUsage,
        *,
        duration_ms: int,
        success: bool,
        retry_count: int = 0,
        error_code: str | None = None,
    ) -> UsageRecord: ...


class DbUsageMeter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        ctx: UsageContext,
        operation: str,
        usage: TokenUsage,
        *,
        duration_ms: int,
        success: bool,
        retry_count: int = 0,
        error_code: str | None = None,
    ) -> UsageRecord:
        rec = UsageRecord(
            user_id=ctx.user_id,
            project_id=ctx.project_id,
            meeting_id=ctx.meeting_id,
            job_id=ctx.job_id,
            operation=operation,
            provider=ctx.provider,
            model=ctx.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tokens_reported_by_provider=usage.reported_by_provider,
            estimated_cost_usd=estimate_cost(ctx.provider, ctx.model, usage.input_tokens, usage.output_tokens),
            duration_ms=duration_ms,
            success=success,
            retry_count=retry_count,
            error_code=error_code,
            key_source=ctx.key_source,
        )
        self._db.add(rec)
        return rec


def usage_scope(user: User) -> ColumnElement[bool]:
    """Admins see all usage; division managers see their divisions' projects;
    project managers see managed projects; everyone sees their own usage."""
    if user.role == GlobalRole.admin:
        return true()
    conds: list[ColumnElement[bool]] = [UsageRecord.user_id == user.id]
    conds.append(UsageRecord.project_id.in_(accessible_project_ids(user, AccessLevel.manage)))
    if user.role == GlobalRole.division_manager:
        conds.append(UsageRecord.project_id.in_(accessible_project_ids(user, AccessLevel.summary)))
    return or_(*conds)


def summarize_usage(
    db: Session, user: User, *, project_id: uuid.UUID | None, date_from: datetime | None, date_to: datetime | None
) -> dict[str, Any]:
    filters: list[ColumnElement[bool]] = [usage_scope(user)]
    if project_id:
        filters.append(UsageRecord.project_id == project_id)
    if date_from:
        filters.append(UsageRecord.created_at >= date_from)
    if date_to:
        filters.append(UsageRecord.created_at <= date_to)
    where = and_(*filters)
    cost = func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0)

    totals = db.execute(
        select(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            cost,
            func.coalesce(func.sum(case((UsageRecord.success.is_(False), 1), else_=0)), 0),
            func.coalesce(func.sum(UsageRecord.duration_ms), 0),
            func.coalesce(func.sum(case((UsageRecord.tokens_reported_by_provider.is_(False), 1), else_=0)), 0),
        ).where(where)
    ).one()

    def rows(stmt: Any) -> list[dict[str, Any]]:
        return [dict(r._mapping) for r in db.execute(stmt)]

    by_model = rows(
        select(
            UsageRecord.provider, UsageRecord.model, func.count().label("requests"), cost.label("estimated_cost_usd")
        )
        .where(where)
        .group_by(UsageRecord.provider, UsageRecord.model)
        .order_by(cost.desc())
    )
    by_operation = rows(
        select(
            UsageRecord.operation,
            func.count().label("requests"),
            func.sum(case((UsageRecord.success.is_(False), 1), else_=0)).label("failed"),
            cost.label("estimated_cost_usd"),
        )
        .where(where)
        .group_by(UsageRecord.operation)
    )
    by_project = rows(
        select(
            Project.id.label("project_id"),
            Project.name.label("project_name"),
            func.count().label("requests"),
            cost.label("estimated_cost_usd"),
        )
        .join(Project, Project.id == UsageRecord.project_id)
        .where(where)
        .group_by(Project.id, Project.name)
        .order_by(cost.desc())
        .limit(20)
    )
    by_meeting = rows(
        select(
            Meeting.id.label("meeting_id"),
            Meeting.title.label("meeting_title"),
            func.count().label("requests"),
            cost.label("estimated_cost_usd"),
        )
        .join(Meeting, Meeting.id == UsageRecord.meeting_id)
        .where(where)
        .group_by(Meeting.id, Meeting.title)
        .order_by(cost.desc())
        .limit(20)
    )
    return {
        "total_requests": int(totals[0]),
        "input_tokens": int(totals[1]),
        "output_tokens": int(totals[2]),
        "estimated_cost_usd": Decimal(totals[3]),
        "failed_requests": int(totals[4]),
        "processing_ms": int(totals[5]),
        "requests_with_estimated_tokens": int(totals[6]),
        "by_model": by_model,
        "by_operation": by_operation,
        "by_project": by_project,
        "by_meeting": by_meeting,
    }
