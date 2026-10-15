from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import GlobalRole, db_enum


class Division(UUIDPk, Timestamps, Base):
    __tablename__ = "divisions"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[GlobalRole] = mapped_column(db_enum(GlobalRole, "global_role"), default=GlobalRole.member)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    locale: Mapped[str] = mapped_column(String(8), default="vi")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    division_assignments: Mapped[list[DivisionAssignment]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class DivisionAssignment(UUIDPk, Timestamps, Base):
    """Grants a Division Manager visibility over the projects of a division."""

    __tablename__ = "division_assignments"
    __table_args__ = (UniqueConstraint("user_id", "division_id", name="uq_division_assignment"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    division_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("divisions.id", ondelete="CASCADE"), index=True
    )
    # Detailed transcript content is visible only with this explicit flag.
    can_view_transcripts: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="division_assignments")
    division: Mapped[Division] = relationship()


class UserSession(UUIDPk, Base):
    """Server-side session. The cookie carries a random token; only its
    SHA-256 hash is stored, so a database leak does not yield live sessions."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_expires_at", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))

    user: Mapped[User] = relationship()


class OidcLoginState(UUIDPk, Base):
    """Short-lived state/nonce/PKCE verifier for an in-flight OIDC login."""

    __tablename__ = "oidc_login_states"

    state: Mapped[str] = mapped_column(String(128), unique=True)
    nonce: Mapped[str] = mapped_column(String(128))
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
