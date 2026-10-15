from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ActionItem,
    Decision,
    Issue,
    Meeting,
    Memo,
    MemoItemSource,
    Project,
    Risk,
    TranscriptEntry,
    User,
)
from app.models.enums import ActionStatus, MeetingPlatform, MemoStatus, VerificationStatus
from app.schemas.api import (
    ActionItemOut,
    DecisionOut,
    IssueOut,
    MeetingInfoOut,
    MeetingOut,
    MemoOut,
    ParticipantOut,
    RiskOut,
    SourceRefOut,
)
from app.services.authz import AccessLevel, ProjectAccess, can_edit_meeting_content

PLATFORM_STATUS = {
    MeetingPlatform.manual_import: "available",
    MeetingPlatform.teams: "not_configured",
    MeetingPlatform.zoom: "not_configured",
    MeetingPlatform.google_meet: "not_configured",
}


def meeting_out(
    db: Session,
    meeting: Meeting,
    access: ProjectAccess,
    user: User,
    *,
    project_name: str | None = None,
    memo_status: MemoStatus | None = None,
    entry_count: int | None = None,
    with_counts: bool = True,
) -> MeetingOut:
    out = MeetingOut.model_validate(meeting)
    out.participants = [ParticipantOut.model_validate(p) for p in meeting.participants]
    out.platform_status = PLATFORM_STATUS[meeting.platform]
    out.project_name = project_name or (meeting.project.name if meeting.project else None)
    if with_counts:
        if memo_status is None:
            memo_status = db.scalar(select(Memo.status).where(Memo.meeting_id == meeting.id))
        if entry_count is None:
            entry_count = (
                db.scalar(
                    select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id)
                )
                or 0
            )
    out.memo_status = memo_status
    out.entry_count = entry_count or 0
    editable = can_edit_meeting_content(access, meeting, user)
    out.permissions = {
        "view_transcript": access.allows(AccessLevel.transcript),
        "edit": editable,
        "approve": access.is_manager,
        "delete": access.is_manager or (editable and meeting.created_by_id == user.id),
    }
    return out


def _sources(
    db: Session, column: Any, ids: Sequence[uuid.UUID], with_text: bool
) -> dict[uuid.UUID, list[SourceRefOut]]:
    if not ids:
        return {}
    rows = db.execute(
        select(column, TranscriptEntry)
        .join(TranscriptEntry, TranscriptEntry.id == MemoItemSource.transcript_entry_id)
        .where(column.in_(ids))
        .order_by(TranscriptEntry.sequence)
    )
    out: dict[uuid.UUID, list[SourceRefOut]] = {}
    for item_id, entry in rows:
        out.setdefault(item_id, []).append(
            SourceRefOut(
                entry_id=entry.id,
                sequence=entry.sequence,
                speaker_label=entry.speaker_label,
                start_ms=entry.start_ms,
                # Summary-only viewers (division managers without the transcript
                # flag) see the reference but not the transcript text.
                excerpt=entry.original_text[:300] if with_text else None,
            )
        )
    return out


def action_items_out(
    db: Session,
    actions: Sequence[ActionItem],
    with_text: bool,
    meeting_titles: dict[uuid.UUID, str] | None = None,
    project_names: dict[uuid.UUID, str] | None = None,
) -> list[ActionItemOut]:
    srcs = _sources(db, MemoItemSource.action_item_id, [a.id for a in actions], with_text)
    today = date.today()
    result = []
    for a in actions:
        out = ActionItemOut.model_validate(a)
        out.sources = srcs.get(a.id, [])
        out.is_overdue = bool(
            a.due_date and a.due_date < today and a.status not in (ActionStatus.done, ActionStatus.cancelled)
        )
        if meeting_titles:
            out.meeting_title = meeting_titles.get(a.meeting_id)
        if project_names:
            out.project_name = project_names.get(a.project_id)
        result.append(out)
    return result


def memo_out(db: Session, memo: Memo, meeting: Meeting, project: Project, access: ProjectAccess, user: User) -> MemoOut:
    with_text = access.allows(AccessLevel.transcript)

    def load(model: Any) -> list[Any]:
        return list(
            db.scalars(select(model).where(model.memo_id == memo.id).order_by(model.sort_order, model.created_at))
        )

    decisions: list[Decision] = load(Decision)
    actions: list[ActionItem] = load(ActionItem)
    issues: list[Issue] = load(Issue)
    risks: list[Risk] = load(Risk)
    d_src = _sources(db, MemoItemSource.decision_id, [d.id for d in decisions], with_text)
    i_src = _sources(db, MemoItemSource.issue_id, [i.id for i in issues], with_text)
    r_src = _sources(db, MemoItemSource.risk_id, [r.id for r in risks], with_text)

    def with_sources(schema: Any, rows: Sequence[Any], srcs: dict[uuid.UUID, list[SourceRefOut]]) -> list[Any]:
        return [schema.model_validate(r).model_copy(update={"sources": srcs.get(r.id, [])}) for r in rows]

    all_items: list[Any] = [*decisions, *actions, *issues, *risks]
    unreviewed = sum(
        1
        for item in all_items
        if item.verification_status in (VerificationStatus.draft, VerificationStatus.needs_review)
    )
    editable = can_edit_meeting_content(access, meeting, user)
    locked = memo.status in (MemoStatus.approved, MemoStatus.generating)
    return MemoOut(
        id=memo.id,
        meeting_id=memo.meeting_id,
        language=memo.language,
        status=memo.status,
        executive_summary=memo.executive_summary,
        discussion=memo.discussion or [],
        open_questions=memo.open_questions or [],
        next_meeting=memo.next_meeting,
        pm_view=memo.pm_view,
        generation_error=memo.generation_error,
        prompt_version=memo.prompt_version,
        provider=memo.provider,
        model=memo.model,
        generated_at=memo.generated_at,
        generation_count=memo.generation_count,
        reviewed_by_id=memo.reviewed_by_id,
        reviewed_at=memo.reviewed_at,
        review_comment=memo.review_comment,
        updated_at=memo.updated_at,
        meeting_info=MeetingInfoOut(
            title=meeting.title,
            project_name=project.name,
            scheduled_at=meeting.scheduled_at,
            timezone=meeting.timezone,
            participants=[p.display_name for p in meeting.participants],
            objective=meeting.objective,
            source_language=meeting.effective_source_language,
            memo_language=memo.language,
        ),
        decisions=with_sources(DecisionOut, decisions, d_src),
        action_items=action_items_out(db, actions, with_text),
        issues=with_sources(IssueOut, issues, i_src),
        risks=with_sources(RiskOut, risks, r_src),
        unreviewed_items=unreviewed,
        permissions={
            "edit": editable and not locked,
            "submit": editable and memo.status in (MemoStatus.draft, MemoStatus.rejected),
            "approve": access.is_manager and memo.status in (MemoStatus.draft, MemoStatus.in_review),
            "reject": access.is_manager and memo.status in (MemoStatus.draft, MemoStatus.in_review),
            "reopen": access.is_manager and memo.status == MemoStatus.approved,
            "export": memo.status == MemoStatus.approved,
            "regenerate": editable and memo.status not in (MemoStatus.approved, MemoStatus.generating),
            "track_actions": editable,
        },
    )
