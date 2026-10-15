from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.deps import DB, Auth, AuthContext, ai_rate_limit
from app.api.v1.serializers import action_items_out, memo_out
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import utcnow
from app.models import (
    ActionItem,
    Decision,
    Issue,
    Job,
    Meeting,
    Memo,
    MemoItemSource,
    Project,
    ProjectMembership,
    Risk,
    TranscriptEntry,
)
from app.models.enums import (
    ActionStatus,
    JobKind,
    MeetingStatus,
    MemoStatus,
    Priority,
    VerificationStatus,
)
from app.schemas.api import (
    ActionItemIn,
    ActionItemOut,
    ActionItemPatch,
    DecisionIn,
    DecisionPatch,
    IssueIn,
    IssuePatch,
    JobOut,
    MemoOut,
    MemoUpdate,
    ReviewIn,
    RiskIn,
    RiskPatch,
)
from app.schemas.common import Page, PageParams
from app.services import jobs as job_service
from app.services.audit import record_audit
from app.services.authz import (
    AccessLevel,
    ProjectAccess,
    accessible_project_ids,
    can_edit_meeting_content,
    load_meeting,
    require_edit_meeting,
)
from app.services.export import memo_to_html, memo_to_json, memo_to_markdown

router = APIRouter(tags=["memos"])
GenerateAuth = Annotated[AuthContext, Depends(ai_rate_limit("memo"))]
EDITABLE = (MemoStatus.draft, MemoStatus.in_review, MemoStatus.rejected)


def _memo_ctx(
    db: DB, auth: AuthContext, memo_id: uuid.UUID, level: AccessLevel = AccessLevel.summary
) -> tuple[Memo, Meeting, Project, ProjectAccess]:
    memo = db.get(Memo, memo_id)
    if memo is None:
        raise NotFound("Memo not found")
    meeting, access = load_meeting(db, auth.user, memo.meeting_id, level)
    project = db.get(Project, meeting.project_id)
    assert project is not None
    return memo, meeting, project, access


def _render(
    db: DB, auth: AuthContext, memo: Memo, meeting: Meeting, project: Project, access: ProjectAccess
) -> MemoOut:
    db.refresh(memo)
    return memo_out(db, memo, meeting, project, access, auth.user)


def _require_editable(memo: Memo, access: ProjectAccess, meeting: Meeting, auth: AuthContext) -> None:
    require_edit_meeting(access, meeting, auth.user)
    if memo.status not in EDITABLE:
        raise Conflict(f"The memo cannot be edited while it is '{memo.status.value}'")


def _validate_entry_ids(db: DB, meeting: Meeting, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Source references must point to entries of this meeting (prevents
    linking — and later disclosing — another meeting's transcript lines)."""
    if not ids:
        return []
    found = set(
        db.scalars(
            select(TranscriptEntry.id).where(TranscriptEntry.meeting_id == meeting.id, TranscriptEntry.id.in_(ids))
        )
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise ValidationFailed("Source references must belong to this meeting", details={"invalid": missing[:10]})
    return list(dict.fromkeys(ids))


@router.get("/meetings/{meeting_id}/memo", response_model=MemoOut)
def get_memo(meeting_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.summary)
    memo = db.scalar(select(Memo).where(Memo.meeting_id == meeting.id))
    if memo is None:
        raise NotFound("No memo has been generated for this meeting")
    project = db.get(Project, meeting.project_id)
    assert project is not None
    return memo_out(db, memo, meeting, project, access, auth.user)


@router.post("/meetings/{meeting_id}/memo/generate", response_model=JobOut, status_code=202)
def generate_memo(meeting_id: uuid.UUID, auth: GenerateAuth, db: DB) -> Job:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    if not db.scalar(select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id)):
        raise Conflict("Import a transcript before generating a memo")
    memo = db.scalar(select(Memo).where(Memo.meeting_id == meeting.id))
    if memo is not None and memo.status == MemoStatus.approved:
        raise Conflict("The memo is approved; reopen it before regenerating")
    if memo is not None and memo.status == MemoStatus.generating:
        raise Conflict("The memo is already being generated")
    if memo is None:
        memo = Memo(
            meeting_id=meeting.id,
            language=meeting.memo_language,
            status=MemoStatus.generating,
            created_by_id=auth.user.id,
        )
        db.add(memo)
    memo.status = MemoStatus.generating
    memo.language = meeting.memo_language
    memo.generation_error = None
    job = job_service.enqueue(
        db,
        kind=JobKind.generate_memo,
        user_id=auth.user.id,
        session_id=auth.session.id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        params={},
    )
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.generate",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return job


@router.put("/memos/{memo_id}", response_model=MemoOut)
def update_memo(memo_id: uuid.UUID, body: MemoUpdate, auth: Auth, db: DB) -> MemoOut:
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.contribute)
    _require_editable(memo, access, meeting, auth)

    def ids(v: list[uuid.UUID]) -> list[str]:
        return [str(i) for i in _validate_entry_ids(db, meeting, v)]

    if body.executive_summary is not None:
        memo.executive_summary = body.executive_summary
    if body.discussion is not None:
        memo.discussion = [
            {"topic": t.topic, "points": t.points, "source_entry_ids": ids(t.source_entry_ids)} for t in body.discussion
        ]
    if body.open_questions is not None:
        memo.open_questions = [
            {"question": q.question, "source_entry_ids": ids(q.source_entry_ids)} for q in body.open_questions
        ]
    if body.clear_next_meeting:
        memo.next_meeting = None
    elif body.next_meeting is not None:
        memo.next_meeting = {
            "when_text": body.next_meeting.when_text,
            "agenda": body.next_meeting.agenda,
            "source_entry_ids": ids(body.next_meeting.source_entry_ids),
        }
    if body.pm_view is not None:
        pm: dict[str, Any] = {}
        for key in ("schedule", "scope", "quality", "cost", "customer_satisfaction", "escalation"):
            val = getattr(body.pm_view, key)
            pm[key] = (
                None
                if val is None
                else {"assessment": val.assessment, "basis": val.basis, "source_entry_ids": ids(val.source_entry_ids)}
            )
        memo.pm_view = pm
    if memo.status == MemoStatus.rejected:
        memo.status = MemoStatus.draft
    memo.updated_by_id = auth.user.id
    memo.updated_at = utcnow()
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.edit",
        resource_type="memo",
        resource_id=memo.id,
        project_id=meeting.project_id,
        details={"fields": sorted(body.model_fields_set)},
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


@router.post("/memos/{memo_id}/submit", response_model=MemoOut)
def submit_memo(memo_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    if memo.status not in (MemoStatus.draft, MemoStatus.rejected):
        raise Conflict("Only draft or rejected memos can be submitted for review")
    memo.status = MemoStatus.in_review
    memo.submitted_at = utcnow()
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.submit",
        resource_type="memo",
        resource_id=memo.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


def _review(memo_id: uuid.UUID, auth: AuthContext, db: DB, approve: bool, comment: str | None) -> MemoOut:
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.manage)
    if memo.status not in (MemoStatus.draft, MemoStatus.in_review):
        raise Conflict(f"A memo in status '{memo.status.value}' cannot be reviewed")
    # Approval is a human act: it requires an authenticated project manager
    # session. No code path lets the AI pipeline set 'approved'.
    memo.status = MemoStatus.approved if approve else MemoStatus.rejected
    memo.reviewed_by_id = auth.user.id
    memo.reviewed_at = utcnow()
    memo.review_comment = comment
    if approve:
        meeting.status = MeetingStatus.completed
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.approve" if approve else "memo.reject",
        resource_type="memo",
        resource_id=memo.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


@router.post("/memos/{memo_id}/approve", response_model=MemoOut)
def approve_memo(memo_id: uuid.UUID, auth: Auth, db: DB, body: ReviewIn | None = None) -> MemoOut:
    return _review(memo_id, auth, db, True, body.comment if body else None)


@router.post("/memos/{memo_id}/reject", response_model=MemoOut)
def reject_memo(memo_id: uuid.UUID, auth: Auth, db: DB, body: ReviewIn | None = None) -> MemoOut:
    return _review(memo_id, auth, db, False, body.comment if body else None)


@router.post("/memos/{memo_id}/reopen", response_model=MemoOut)
def reopen_memo(memo_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.manage)
    if memo.status != MemoStatus.approved:
        raise Conflict("Only approved memos can be reopened")
    memo.status = MemoStatus.draft
    meeting.status = MeetingStatus.memo_draft
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.reopen",
        resource_type="memo",
        resource_id=memo.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


@router.get("/memos/{memo_id}/export")
def export_memo(memo_id: uuid.UUID, auth: Auth, db: DB, format: Literal["md", "html", "json"] = "md") -> Response:
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.summary)
    if memo.status != MemoStatus.approved:
        raise Conflict("Only approved memos can be exported")
    out = memo_out(db, memo, meeting, project, access, auth.user)
    content, media, ext = {
        "md": (memo_to_markdown, "text/markdown; charset=utf-8", "md"),
        "html": (memo_to_html, "text/html; charset=utf-8", "html"),
        "json": (memo_to_json, "application/json", "json"),
    }[format]
    record_audit(
        db,
        actor_id=auth.user.id,
        action="memo.export",
        resource_type="memo",
        resource_id=memo.id,
        project_id=meeting.project_id,
        details={"format": format},
        ip=auth.ip,
    )
    db.commit()
    return Response(
        content(out),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="memo-{meeting.id}.{ext}"'},
    )


# ---- Extracted items --------------------------------------------------------


@dataclass(frozen=True)
class ItemKind:
    path: str
    model: Any
    prefix: str
    fk: str  # MemoItemSource column


KINDS = {
    "decisions": ItemKind("decisions", Decision, "D", "decision_id"),
    "action-items": ItemKind("action-items", ActionItem, "A", "action_item_id"),
    "issues": ItemKind("issues", Issue, "I", "issue_id"),
    "risks": ItemKind("risks", Risk, "R", "risk_id"),
}


def _set_sources(db: DB, kind: ItemKind, item: Any, meeting: Meeting, ids: list[uuid.UUID]) -> None:
    valid = _validate_entry_ids(db, meeting, ids)
    item.source_links = [MemoItemSource(transcript_entry_id=i, **{kind.fk: item.id}) for i in valid]


def _next_code(db: DB, kind: ItemKind, memo: Memo) -> tuple[str, int]:
    n = (db.scalar(select(func.count()).select_from(kind.model).where(kind.model.memo_id == memo.id)) or 0) + 1
    existing = set(db.scalars(select(kind.model.code).where(kind.model.memo_id == memo.id)))
    while f"{kind.prefix}-{n}" in existing:
        n += 1
    return f"{kind.prefix}-{n}", n


def _create_item(kind_key: str, memo_id: uuid.UUID, body: Any, auth: AuthContext, db: DB) -> MemoOut:
    kind = KINDS[kind_key]
    memo, meeting, project, access = _memo_ctx(db, auth, memo_id, AccessLevel.contribute)
    _require_editable(memo, access, meeting, auth)
    data = body.model_dump(exclude={"source_entry_ids"})
    code, order = _next_code(db, kind, memo)
    # Items entered by a person are human-verified by definition.
    item = kind.model(
        id=uuid.uuid4(),
        memo_id=memo.id,
        meeting_id=meeting.id,
        project_id=meeting.project_id,
        code=code,
        sort_order=order,
        ai_generated=False,
        verification_status=VerificationStatus.confirmed,
        **data,
    )
    if kind_key == "action-items" and body.related_decision_id:
        _check_decision(db, memo, body.related_decision_id)
    db.add(item)
    db.flush()
    _set_sources(db, kind, item, meeting, body.source_entry_ids)
    record_audit(
        db,
        actor_id=auth.user.id,
        action=f"{kind.model.__tablename__}.create",
        resource_type=kind.model.__tablename__,
        resource_id=item.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


def _check_decision(db: DB, memo: Memo, decision_id: uuid.UUID) -> None:
    d = db.get(Decision, decision_id)
    if d is None or d.memo_id != memo.id:
        raise ValidationFailed("Related decision must belong to the same memo")


TRACKING_FIELDS = {"status"}
ASSIGNMENT_FIELDS = {
    "owner_text",
    "owner_user_id",
    "due_date",
    "due_text",
    "due_needs_confirmation",
    "priority",
    "verification_status",
    "review_note",
}


def _patch_item(kind_key: str, item_id: uuid.UUID, body: Any, auth: AuthContext, db: DB) -> Any:
    kind = KINDS[kind_key]
    item = db.get(kind.model, item_id)
    if item is None:
        raise NotFound("Item not found")
    memo, meeting, project, access = _memo_ctx(db, auth, item.memo_id, AccessLevel.summary)
    changes = body.model_dump(exclude_unset=True)
    fields = set(changes)
    editor = can_edit_meeting_content(access, meeting, auth.user)
    is_owner = getattr(item, "owner_user_id", None) == auth.user.id
    if kind_key == "action-items" and fields <= TRACKING_FIELDS:
        # Action owners can update the status of their own tasks.
        if not (editor or is_owner):
            raise Forbidden("Only the action owner, meeting creator or project manager can update this action")
    else:
        if not editor:
            raise Forbidden("Only the meeting creator or a project manager can edit this item")
        content_fields = fields - TRACKING_FIELDS - (ASSIGNMENT_FIELDS if kind_key == "action-items" else set())
        if memo.status not in EDITABLE and content_fields:
            raise Conflict("The memo is approved or generating; reopen it to edit item content")
    if (
        changes.get("owner_user_id") is not None
        and db.scalar(
            select(ProjectMembership.id).where(
                ProjectMembership.project_id == meeting.project_id,
                ProjectMembership.user_id == changes["owner_user_id"],
            )
        )
        is None
    ):
        raise ValidationFailed("Owner must be a member of the project")
    if kind_key == "action-items" and changes.get("related_decision_id"):
        _check_decision(db, memo, changes["related_decision_id"])
    source_ids = changes.pop("source_entry_ids", None)
    for key, value in changes.items():
        setattr(item, key, value)
    if kind_key == "action-items" and "status" in changes:
        item.completed_at = utcnow() if changes["status"] == ActionStatus.done else None
    if (
        kind_key == "action-items"
        and "due_date" in changes
        and changes["due_date"]
        and "due_needs_confirmation" not in changes
    ):
        item.due_needs_confirmation = False  # a person set the date explicitly
    if source_ids is not None:
        _set_sources(db, kind, item, meeting, source_ids)
    record_audit(
        db,
        actor_id=auth.user.id,
        action=f"{kind.model.__tablename__}.update",
        resource_type=kind.model.__tablename__,
        resource_id=item.id,
        project_id=meeting.project_id,
        details={
            "fields": sorted(fields),
            **({"verification": str(changes["verification_status"])} if "verification_status" in changes else {}),
        },
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


def _delete_item(kind_key: str, item_id: uuid.UUID, auth: AuthContext, db: DB) -> MemoOut:
    kind = KINDS[kind_key]
    item = db.get(kind.model, item_id)
    if item is None:
        raise NotFound("Item not found")
    memo, meeting, project, access = _memo_ctx(db, auth, item.memo_id, AccessLevel.contribute)
    _require_editable(memo, access, meeting, auth)
    db.delete(item)
    record_audit(
        db,
        actor_id=auth.user.id,
        action=f"{kind.model.__tablename__}.delete",
        resource_type=kind.model.__tablename__,
        resource_id=item_id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return _render(db, auth, memo, meeting, project, access)


@router.post("/memos/{memo_id}/decisions", response_model=MemoOut, status_code=201)
def create_decision(memo_id: uuid.UUID, body: DecisionIn, auth: Auth, db: DB) -> MemoOut:
    return _create_item("decisions", memo_id, body, auth, db)


@router.post("/memos/{memo_id}/action-items", response_model=MemoOut, status_code=201)
def create_action(memo_id: uuid.UUID, body: ActionItemIn, auth: Auth, db: DB) -> MemoOut:
    return _create_item("action-items", memo_id, body, auth, db)


@router.post("/memos/{memo_id}/issues", response_model=MemoOut, status_code=201)
def create_issue(memo_id: uuid.UUID, body: IssueIn, auth: Auth, db: DB) -> MemoOut:
    return _create_item("issues", memo_id, body, auth, db)


@router.post("/memos/{memo_id}/risks", response_model=MemoOut, status_code=201)
def create_risk(memo_id: uuid.UUID, body: RiskIn, auth: Auth, db: DB) -> MemoOut:
    return _create_item("risks", memo_id, body, auth, db)


@router.patch("/decisions/{item_id}", response_model=MemoOut)
def patch_decision(item_id: uuid.UUID, body: DecisionPatch, auth: Auth, db: DB) -> MemoOut:
    return _patch_item("decisions", item_id, body, auth, db)  # type: ignore[no-any-return]


@router.patch("/action-items/{item_id}", response_model=MemoOut)
def patch_action(item_id: uuid.UUID, body: ActionItemPatch, auth: Auth, db: DB) -> MemoOut:
    return _patch_item("action-items", item_id, body, auth, db)  # type: ignore[no-any-return]


@router.patch("/issues/{item_id}", response_model=MemoOut)
def patch_issue(item_id: uuid.UUID, body: IssuePatch, auth: Auth, db: DB) -> MemoOut:
    return _patch_item("issues", item_id, body, auth, db)  # type: ignore[no-any-return]


@router.patch("/risks/{item_id}", response_model=MemoOut)
def patch_risk(item_id: uuid.UUID, body: RiskPatch, auth: Auth, db: DB) -> MemoOut:
    return _patch_item("risks", item_id, body, auth, db)  # type: ignore[no-any-return]


@router.delete("/decisions/{item_id}", response_model=MemoOut)
def delete_decision(item_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    return _delete_item("decisions", item_id, auth, db)


@router.delete("/action-items/{item_id}", response_model=MemoOut)
def delete_action(item_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    return _delete_item("action-items", item_id, auth, db)


@router.delete("/issues/{item_id}", response_model=MemoOut)
def delete_issue(item_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    return _delete_item("issues", item_id, auth, db)


@router.delete("/risks/{item_id}", response_model=MemoOut)
def delete_risk(item_id: uuid.UUID, auth: Auth, db: DB) -> MemoOut:
    return _delete_item("risks", item_id, auth, db)


# ---- Action tracker -----------------------------------------------------------


@router.get("/action-items", response_model=Page[ActionItemOut])
def list_action_items(
    auth: Auth,
    db: DB,
    pg: PageParams = Depends(),
    project_id: uuid.UUID | None = None,
    meeting_id: uuid.UUID | None = None,
    status: Annotated[list[ActionStatus] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    verification: Annotated[list[VerificationStatus] | None, Query()] = None,
    owner: Annotated[str | None, Query(max_length=200)] = None,
    mine: bool = False,
    due_from: date | None = None,
    due_to: date | None = None,
    overdue: bool = False,
    include_rejected: bool = False,
) -> Page[ActionItemOut]:
    stmt = (
        select(ActionItem)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(
            Meeting.deleted_at.is_(None),
            ActionItem.project_id.in_(accessible_project_ids(auth.user, AccessLevel.summary)),
        )
    )
    if not include_rejected:
        stmt = stmt.where(ActionItem.verification_status != VerificationStatus.rejected)
    if project_id:
        stmt = stmt.where(ActionItem.project_id == project_id)
    if meeting_id:
        stmt = stmt.where(ActionItem.meeting_id == meeting_id)
    if status:
        stmt = stmt.where(ActionItem.status.in_(status))
    if priority:
        stmt = stmt.where(ActionItem.priority.in_(priority))
    if verification:
        stmt = stmt.where(ActionItem.verification_status.in_(verification))
    if owner:
        stmt = stmt.where(ActionItem.owner_text.ilike(f"%{owner}%"))
    if mine:
        stmt = stmt.where(ActionItem.owner_user_id == auth.user.id)
    if due_from:
        stmt = stmt.where(ActionItem.due_date >= due_from)
    if due_to:
        stmt = stmt.where(ActionItem.due_date <= due_to)
    if overdue:
        stmt = stmt.where(
            ActionItem.due_date < date.today(), ActionItem.status.not_in([ActionStatus.done, ActionStatus.cancelled])
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(ActionItem.due_date.asc().nulls_last(), ActionItem.created_at.desc())
            .offset(pg.offset)
            .limit(pg.page_size)
        )
    )
    meeting_ids = {a.meeting_id for a in rows}
    project_ids = {a.project_id for a in rows}
    titles = (
        dict(db.execute(select(Meeting.id, Meeting.title).where(Meeting.id.in_(meeting_ids))).all()) if rows else {}
    )
    names = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).all()) if rows else {}
    # Excerpts only where the viewer has transcript access.
    transcript_ok = set(db.scalars(accessible_project_ids(auth.user, AccessLevel.transcript)))
    items: list[ActionItemOut] = []
    for a in rows:
        items.extend(action_items_out(db, [a], a.project_id in transcript_ok, titles, names))
    return Page(items=items, total=total, page=pg.page, page_size=pg.page_size)
