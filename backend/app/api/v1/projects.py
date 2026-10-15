from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, Auth
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import utcnow
from app.models import Division, GlossaryEntry, Project, ProjectMembership, User
from app.models.enums import GlobalRole, ProjectRole
from app.schemas.api import (
    GlossaryIn,
    GlossaryOut,
    GlossaryUpdate,
    MemberIn,
    MemberOut,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
)
from app.schemas.common import Page, PageParams
from app.services.audit import record_audit
from app.services.authz import (
    AccessLevel,
    ProjectAccess,
    accessible_project_ids,
    get_project_access,
    load_project,
    require_admin,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _permissions(access: ProjectAccess) -> dict[str, bool]:
    return {
        "view_summary": access.allows(AccessLevel.summary),
        "view_transcript": access.allows(AccessLevel.transcript),
        "contribute": access.allows(AccessLevel.contribute),
        "manage": access.allows(AccessLevel.manage),
        "admin": access.is_admin,
    }


def project_out(db: DB, user: User, project: Project, access: ProjectAccess | None = None) -> ProjectOut:
    access = access or get_project_access(db, user, project)
    out = ProjectOut.model_validate(project)
    out.my_role = ProjectRole.manager if access.is_manager else ProjectRole.member if access.is_member else None
    out.permissions = _permissions(access)
    return out


def _require_manage_or_admin(access: ProjectAccess) -> None:
    if not (access.is_manager or access.is_admin):
        raise Forbidden("Project manager or administrator role required")


@router.get("", response_model=Page[ProjectOut])
def list_projects(auth: Auth, db: DB, pg: PageParams = Depends(), q: str | None = None) -> Page[ProjectOut]:
    stmt = select(Project).where(Project.id.in_(accessible_project_ids(auth.user, AccessLevel.metadata)))
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q[:100]}%") | Project.code.ilike(f"%{q[:100]}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Project.name).offset(pg.offset).limit(pg.page_size))
    return Page(items=[project_out(db, auth.user, p) for p in rows], total=total, page=pg.page, page_size=pg.page_size)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, auth: Auth, db: DB) -> ProjectOut:
    if auth.user.role not in (GlobalRole.admin, GlobalRole.project_manager):
        raise Forbidden("Only project managers and administrators can create projects")
    if body.division_id and db.get(Division, body.division_id) is None:
        raise ValidationFailed("Division not found")
    project = Project(**body.model_dump(), created_by_id=auth.user.id)
    project.code = body.code.upper()
    db.add(project)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A project with this code already exists") from None
    if auth.user.role == GlobalRole.project_manager:
        db.add(ProjectMembership(project_id=project.id, user_id=auth.user.id, role=ProjectRole.manager))
    record_audit(
        db,
        actor_id=auth.user.id,
        action="project.create",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        ip=auth.ip,
    )
    db.commit()
    return project_out(db, auth.user, project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, auth: Auth, db: DB) -> ProjectOut:
    project, access = load_project(db, auth.user, project_id, AccessLevel.metadata)
    return project_out(db, auth.user, project, access)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: uuid.UUID, body: ProjectUpdate, auth: Auth, db: DB) -> ProjectOut:
    project, access = load_project(db, auth.user, project_id, AccessLevel.metadata)
    _require_manage_or_admin(access)
    changes = body.model_dump(exclude_unset=True)
    if "division_id" in changes and changes["division_id"] and db.get(Division, changes["division_id"]) is None:
        raise ValidationFailed("Division not found")
    for key, value in changes.items():
        setattr(project, key, value)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="project.update",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"fields": sorted(changes)},
        ip=auth.ip,
    )
    db.commit()
    return project_out(db, auth.user, project, access)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, auth: Auth, db: DB) -> None:
    require_admin(auth.user)
    project, _ = load_project(db, auth.user, project_id, AccessLevel.metadata)
    project.deleted_at = utcnow()
    record_audit(
        db,
        actor_id=auth.user.id,
        action="project.delete",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        ip=auth.ip,
    )
    db.commit()


# ---- Members ------------------------------------------------------------------


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: uuid.UUID, auth: Auth, db: DB) -> list[MemberOut]:
    load_project(db, auth.user, project_id, AccessLevel.metadata)
    rows = db.execute(
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(ProjectMembership.project_id == project_id)
        .order_by(User.display_name)
    )
    return [MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role) for m, u in rows]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=201)
def add_member(project_id: uuid.UUID, body: MemberIn, auth: Auth, db: DB) -> MemberOut:
    project, access = load_project(db, auth.user, project_id, AccessLevel.metadata)
    _require_manage_or_admin(access)
    user = (
        db.get(User, body.user_id)
        if body.user_id
        else (db.scalar(select(User).where(User.email == body.email.lower())) if body.email else None)
    )
    if user is None or not user.is_active:
        raise NotFound("User not found")
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id
        )
    )
    if membership is None:
        membership = ProjectMembership(project_id=project.id, user_id=user.id, role=body.role)
        db.add(membership)
    else:
        membership.role = body.role
    record_audit(
        db,
        actor_id=auth.user.id,
        action="project.member_upsert",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"user_id": str(user.id), "role": body.role.value},
        ip=auth.ip,
    )
    db.commit()
    return MemberOut(user_id=user.id, email=user.email, display_name=user.display_name, role=membership.role)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: uuid.UUID, user_id: uuid.UUID, auth: Auth, db: DB) -> None:
    project, access = load_project(db, auth.user, project_id, AccessLevel.metadata)
    _require_manage_or_admin(access)
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user_id
        )
    )
    if membership is None:
        raise NotFound("Membership not found")
    if membership.role == ProjectRole.manager:
        managers = db.scalar(
            select(func.count()).where(
                ProjectMembership.project_id == project.id, ProjectMembership.role == ProjectRole.manager
            )
        )
        if managers == 1 and not access.is_admin:
            raise Conflict("A project must keep at least one manager")
    db.delete(membership)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="project.member_remove",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"user_id": str(user_id)},
        ip=auth.ip,
    )
    db.commit()


# ---- Glossary -----------------------------------------------------------------


@router.get("/{project_id}/glossary", response_model=list[GlossaryOut])
def list_glossary(project_id: uuid.UUID, auth: Auth, db: DB) -> list[GlossaryEntry]:
    load_project(db, auth.user, project_id, AccessLevel.summary)
    return list(
        db.scalars(
            select(GlossaryEntry)
            .where(GlossaryEntry.project_id == project_id)
            .order_by(GlossaryEntry.source_language, GlossaryEntry.source_term)
        )
    )


@router.post("/{project_id}/glossary", response_model=GlossaryOut, status_code=201)
def create_glossary(project_id: uuid.UUID, body: GlossaryIn, auth: Auth, db: DB) -> GlossaryEntry:
    load_project(db, auth.user, project_id, AccessLevel.manage)
    if body.source_language == body.target_language:
        raise ValidationFailed("Source and target languages must differ")
    entry = GlossaryEntry(project_id=project_id, created_by_id=auth.user.id, **body.model_dump())
    db.add(entry)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("This term already exists for the language pair") from None
    record_audit(
        db,
        actor_id=auth.user.id,
        action="glossary.create",
        resource_type="glossary_entry",
        resource_id=entry.id,
        project_id=project_id,
        ip=auth.ip,
    )
    db.commit()
    return entry


@router.patch("/{project_id}/glossary/{entry_id}", response_model=GlossaryOut)
def update_glossary(
    project_id: uuid.UUID, entry_id: uuid.UUID, body: GlossaryUpdate, auth: Auth, db: DB
) -> GlossaryEntry:
    load_project(db, auth.user, project_id, AccessLevel.manage)
    entry = db.get(GlossaryEntry, entry_id)
    if entry is None or entry.project_id != project_id:
        raise NotFound("Glossary entry not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    db.commit()
    return entry


@router.delete("/{project_id}/glossary/{entry_id}", status_code=204)
def delete_glossary(project_id: uuid.UUID, entry_id: uuid.UUID, auth: Auth, db: DB) -> None:
    load_project(db, auth.user, project_id, AccessLevel.manage)
    entry = db.get(GlossaryEntry, entry_id)
    if entry is None or entry.project_id != project_id:
        raise NotFound("Glossary entry not found")
    db.delete(entry)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="glossary.delete",
        resource_type="glossary_entry",
        resource_id=entry_id,
        project_id=project_id,
        ip=auth.ip,
    )
    db.commit()
