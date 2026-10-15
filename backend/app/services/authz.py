"""Central authorization policy.

Every protected query goes through this module, so the access rules exist
in exactly one place:

* Project members see project content; project managers (membership role
  ``manager``) additionally manage meetings, approve memos and confirm
  actions.
* Division managers see summaries (memos, decisions, actions, issues, risks)
  for projects in their assigned divisions. Transcript text and translations
  require the explicit ``can_view_transcripts`` flag on the assignment.
* Administrators manage users, projects and memberships and see audit and
  usage data, but do NOT see meeting content unless they are also a member.

Resources outside a user's access are reported as 404 (not 403) so that
existence of other projects' meetings is not disclosed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.models import DivisionAssignment, Meeting, Project, ProjectMembership, User
from app.models.enums import GlobalRole, ProjectRole


class AccessLevel(StrEnum):
    metadata = "metadata"  # project name/code, membership
    summary = "summary"  # meetings, memos, extracted items
    transcript = "transcript"  # transcript text and translations
    contribute = "contribute"  # create meetings, import, translate, generate/edit own memos
    manage = "manage"  # approve memos, manage any meeting, glossary, settings


@dataclass(frozen=True)
class ProjectAccess:
    project_id: uuid.UUID
    is_member: bool
    is_manager: bool
    division_view: bool
    division_transcripts: bool
    is_admin: bool

    def allows(self, level: AccessLevel) -> bool:
        match level:
            case AccessLevel.metadata:
                return self.is_member or self.division_view or self.is_admin
            case AccessLevel.summary:
                return self.is_member or self.division_view
            case AccessLevel.transcript:
                return self.is_member or self.division_transcripts
            case AccessLevel.contribute:
                return self.is_member
            case AccessLevel.manage:
                return self.is_manager


def get_project_access(db: Session, user: User, project: Project) -> ProjectAccess:
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id
        )
    )
    division_view = False
    division_transcripts = False
    if user.role == GlobalRole.division_manager and project.division_id is not None:
        assignment = db.scalar(
            select(DivisionAssignment).where(
                DivisionAssignment.user_id == user.id, DivisionAssignment.division_id == project.division_id
            )
        )
        if assignment is not None:
            division_view = True
            division_transcripts = assignment.can_view_transcripts
    return ProjectAccess(
        project_id=project.id,
        is_member=membership is not None,
        is_manager=membership is not None and membership.role == ProjectRole.manager,
        division_view=division_view,
        division_transcripts=division_transcripts,
        is_admin=user.role == GlobalRole.admin,
    )


def accessible_project_ids(user: User, level: AccessLevel) -> Select[Any]:
    """A SELECT of project ids the user may access at ``level`` — used as a
    subquery filter on every list endpoint to prevent cross-project leakage."""
    member_q = select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
    if level == AccessLevel.manage:
        member_q = member_q.where(ProjectMembership.role == ProjectRole.manager)
    conditions = [Project.id.in_(member_q)]

    if level in (AccessLevel.metadata, AccessLevel.summary, AccessLevel.transcript) and (
        user.role == GlobalRole.division_manager
    ):
        div_q = select(DivisionAssignment.division_id).where(DivisionAssignment.user_id == user.id)
        if level == AccessLevel.transcript:
            div_q = div_q.where(DivisionAssignment.can_view_transcripts.is_(True))
        conditions.append(Project.division_id.in_(div_q))

    if level == AccessLevel.metadata and user.role == GlobalRole.admin:
        return select(Project.id).where(Project.deleted_at.is_(None))
    return select(Project.id).where(Project.deleted_at.is_(None), or_(*conditions))


def load_project(db: Session, user: User, project_id: uuid.UUID, level: AccessLevel) -> tuple[Project, ProjectAccess]:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise NotFound("Project not found")
    access = get_project_access(db, user, project)
    if not access.allows(AccessLevel.metadata):
        raise NotFound("Project not found")
    if not access.allows(level):
        raise Forbidden("You do not have permission for this action on the project")
    return project, access


def load_meeting(db: Session, user: User, meeting_id: uuid.UUID, level: AccessLevel) -> tuple[Meeting, ProjectAccess]:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None:
        raise NotFound("Meeting not found")
    project = db.get(Project, meeting.project_id)
    assert project is not None
    access = get_project_access(db, user, project)
    if project.deleted_at is not None or not access.allows(AccessLevel.summary):
        raise NotFound("Meeting not found")
    if not access.allows(level):
        raise Forbidden("You do not have permission for this action on the meeting")
    return meeting, access


def can_edit_meeting_content(access: ProjectAccess, meeting: Meeting, user: User) -> bool:
    """Members edit meetings they created; managers edit any meeting in the project."""
    return access.is_manager or (access.is_member and meeting.created_by_id == user.id)


def require_edit_meeting(access: ProjectAccess, meeting: Meeting, user: User) -> None:
    if not can_edit_meeting_content(access, meeting, user):
        raise Forbidden("Only the meeting creator or a project manager can modify this meeting")


def require_admin(user: User) -> None:
    if user.role != GlobalRole.admin:
        raise Forbidden("Administrator role required")
