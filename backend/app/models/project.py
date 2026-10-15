from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import Language, ProjectRole, ProjectStatus, db_enum
from app.models.identity import Division, User


class Project(UUIDPk, Timestamps, Base):
    __tablename__ = "projects"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(String(200))
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("divisions.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ProjectStatus] = mapped_column(
        db_enum(ProjectStatus, "project_status"), default=ProjectStatus.active
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    default_source_language: Mapped[Language] = mapped_column(
        db_enum(Language, "default_source_language"), default=Language.ja
    )
    default_target_language: Mapped[Language] = mapped_column(
        db_enum(Language, "default_target_language"), default=Language.vi
    )
    default_memo_language: Mapped[Language] = mapped_column(
        db_enum(Language, "default_memo_language"), default=Language.vi
    )
    translation_instructions: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    division: Mapped[Division | None] = relationship()
    memberships: Mapped[list[ProjectMembership]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMembership(UUIDPk, Timestamps, Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ProjectRole] = mapped_column(db_enum(ProjectRole, "project_role"), default=ProjectRole.member)

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()


class GlossaryEntry(UUIDPk, Timestamps, Base):
    __tablename__ = "glossary_entries"
    __table_args__ = (
        Index("ix_glossary_lookup", "project_id", "source_language", "target_language", "is_active"),
        UniqueConstraint("project_id", "source_language", "target_language", "source_term", name="uq_glossary_term"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    source_term: Mapped[str] = mapped_column(String(200))
    preferred_translation: Mapped[str] = mapped_column(String(200))
    source_language: Mapped[Language] = mapped_column(db_enum(Language, "source_language"))
    target_language: Mapped[Language] = mapped_column(db_enum(Language, "target_language"))
    context: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
