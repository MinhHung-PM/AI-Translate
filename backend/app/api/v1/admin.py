"""Administrator endpoints. Admins manage identities and configuration and
see operational/audit data. They never see plaintext API keys (no endpoint
returns them) and do not see meeting content unless also a project member."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, Auth, AuthContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import AuditEvent, Division, DivisionAssignment, Job, User, UserSession
from app.models.enums import GlobalRole, JobStatus
from app.schemas.api import (
    AdminUserCreate,
    AdminUserUpdate,
    AuditEventOut,
    DivisionAssignmentIn,
    DivisionAssignmentOut,
    DivisionIn,
    DivisionOut,
    UserOut,
)
from app.schemas.common import Page, PageParams
from app.services.audit import record_audit
from app.services.authz import require_admin
from app.services.retention import enforce_retention

router = APIRouter(prefix="/admin", tags=["admin"])


def admin(auth: Auth) -> AuthContext:
    require_admin(auth.user)
    return auth


@router.get("/users", response_model=Page[UserOut])
def list_users(
    db: DB,
    auth: AuthContext = Depends(admin),
    pg: PageParams = Depends(),
    q: str | None = Query(default=None, max_length=200),
) -> Page[UserOut]:
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.display_name).offset(pg.offset).limit(pg.page_size))
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, page=pg.page, page_size=pg.page_size)


@router.get("/users/lookup", response_model=list[UserOut])
def lookup_users(db: DB, auth: Auth, q: str = Query(min_length=2, max_length=200)) -> list[User]:
    """Project managers and admins look up users to add as project members."""
    if auth.user.role not in (GlobalRole.admin, GlobalRole.project_manager):
        require_admin(auth.user)
    return list(
        db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
            .limit(10)
        )
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: AdminUserCreate, db: DB, auth: AuthContext = Depends(admin)) -> User:
    user = User(email=body.email.lower(), display_name=body.display_name, role=body.role)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A user with this email already exists") from None
    record_audit(
        db,
        actor_id=auth.user.id,
        action="admin.user_create",
        resource_type="user",
        resource_id=user.id,
        details={"role": body.role.value},
        ip=auth.ip,
    )
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: AdminUserUpdate, db: DB, auth: AuthContext = Depends(admin)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == auth.user.id and (
        changes.get("role", GlobalRole.admin) != GlobalRole.admin or changes.get("is_active") is False
    ):
        raise ValidationFailed("Administrators cannot remove their own admin access")
    for key, value in changes.items():
        setattr(user, key, value)
    if changes.get("is_active") is False:
        for s in db.scalars(select(UserSession).where(UserSession.user_id == user.id)):
            db.delete(s)  # also destroys session-only API keys
    record_audit(
        db,
        actor_id=auth.user.id,
        action="admin.user_update",
        resource_type="user",
        resource_id=user.id,
        details={k: str(v) for k, v in changes.items()},
        ip=auth.ip,
    )
    db.commit()
    return user


@router.get("/divisions", response_model=list[DivisionOut])
def list_divisions(db: DB, auth: Auth) -> list[Division]:
    return list(db.scalars(select(Division).order_by(Division.name)))


@router.post("/divisions", response_model=DivisionOut, status_code=201)
def create_division(body: DivisionIn, db: DB, auth: AuthContext = Depends(admin)) -> Division:
    division = Division(**body.model_dump())
    db.add(division)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("Division already exists") from None
    record_audit(
        db,
        actor_id=auth.user.id,
        action="admin.division_create",
        resource_type="division",
        resource_id=division.id,
        ip=auth.ip,
    )
    db.commit()
    return division


@router.get("/division-assignments", response_model=list[DivisionAssignmentOut])
def list_assignments(db: DB, auth: AuthContext = Depends(admin)) -> list[DivisionAssignment]:
    return list(db.scalars(select(DivisionAssignment)))


@router.put("/division-assignments", response_model=DivisionAssignmentOut)
def upsert_assignment(body: DivisionAssignmentIn, db: DB, auth: AuthContext = Depends(admin)) -> DivisionAssignment:
    user = db.get(User, body.user_id)
    if user is None or db.get(Division, body.division_id) is None:
        raise NotFound("User or division not found")
    if user.role != GlobalRole.division_manager:
        raise ValidationFailed("Only division managers can be assigned to divisions")
    row = db.scalar(
        select(DivisionAssignment).where(
            DivisionAssignment.user_id == body.user_id, DivisionAssignment.division_id == body.division_id
        )
    )
    if row is None:
        row = DivisionAssignment(user_id=body.user_id, division_id=body.division_id)
        db.add(row)
    row.can_view_transcripts = body.can_view_transcripts
    record_audit(
        db,
        actor_id=auth.user.id,
        action="admin.division_assign",
        resource_type="division",
        resource_id=body.division_id,
        details={"user_id": str(body.user_id), "can_view_transcripts": body.can_view_transcripts},
        ip=auth.ip,
    )
    db.commit()
    return row


@router.delete("/division-assignments/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: uuid.UUID, db: DB, auth: AuthContext = Depends(admin)) -> None:
    row = db.get(DivisionAssignment, assignment_id)
    if row is None:
        raise NotFound("Assignment not found")
    db.delete(row)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="admin.division_unassign",
        resource_type="division",
        resource_id=row.division_id,
        details={"user_id": str(row.user_id)},
        ip=auth.ip,
    )
    db.commit()


@router.get("/audit-events", response_model=Page[AuditEventOut])
def audit_events(
    db: DB,
    auth: AuthContext = Depends(admin),
    pg: PageParams = Depends(),
    action: str | None = Query(default=None, max_length=64),
    actor_user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> Page[AuditEventOut]:
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    if actor_user_id:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if project_id:
        stmt = stmt.where(AuditEvent.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditEvent.created_at.desc()).offset(pg.offset).limit(pg.page_size))
    return Page(
        items=[AuditEventOut.model_validate(r) for r in rows], total=total, page=pg.page, page_size=pg.page_size
    )


@router.get("/health")
def operational_health(db: DB, auth: AuthContext = Depends(admin)) -> dict[str, Any]:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    last_failed = db.execute(
        select(Job.id, Job.kind, Job.error_code, Job.finished_at)
        .where(Job.status == JobStatus.failed)
        .order_by(Job.finished_at.desc())
        .limit(10)
    ).all()
    return {
        "database": "ok",
        "jobs": {s.value: counts.get(s, 0) for s in JobStatus},
        "recent_failures": [
            {"id": str(r[0]), "kind": r[1], "error_code": r[2], "finished_at": r[3]} for r in last_failed
        ],
        "active_sessions": db.scalar(select(func.count()).select_from(UserSession)) or 0,
    }


@router.post("/retention/run")
def run_retention(db: DB, auth: AuthContext = Depends(admin)) -> dict[str, int]:
    result = enforce_retention(db)
    record_audit(
        db, actor_id=auth.user.id, action="admin.retention_run", resource_type="system", details=result, ip=auth.ip
    )
    db.commit()
    return result
