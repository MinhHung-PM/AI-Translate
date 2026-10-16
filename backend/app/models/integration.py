"""Workstream 2 models: platform connections, encrypted credentials, OAuth
state, links between app meetings and provider meetings, and the provider
event log used for webhook replay protection and diagnostics.

Platform tokens live only in ``platform_credentials`` (AES-256-GCM via the
existing keyring). They are never placed in meeting/transcript rows or in the
user's AI provider configuration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import (
    ConnectionState,
    ExternalTranscriptStatus,
    PlatformProvider,
    ProviderEventStatus,
    db_enum,
)


class PlatformConnection(UUIDPk, Timestamps, Base):
    """One user's authorization of one platform (delegated/user-level OAuth)."""

    __tablename__ = "platform_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_platform_connection_user_provider"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[PlatformProvider] = mapped_column(db_enum(PlatformProvider, "platform_provider"))
    state: Mapped[ConnectionState] = mapped_column(
        db_enum(ConnectionState, "connection_state"), default=ConnectionState.awaiting_authorization
    )
    account_id: Mapped[str | None] = mapped_column(String(255))
    account_display: Mapped[str | None] = mapped_column(String(320))
    granted_scopes: Mapped[str] = mapped_column(Text, default="")
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(500))  # safe, user-facing
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0)

    credential: Mapped[PlatformCredential | None] = relationship(
        back_populates="connection", cascade="all, delete-orphan", uselist=False
    )

    def scopes(self) -> set[str]:
        return {s for s in self.granted_scopes.split() if s}


class PlatformCredential(UUIDPk, Base):
    """Encrypted OAuth tokens. Separate table so no ordinary query or
    serializer of a connection can accidentally include token material."""

    __tablename__ = "platform_credentials"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_connections.id", ondelete="CASCADE"), unique=True
    )
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    connection: Mapped[PlatformConnection] = relationship(back_populates="credential")


class PlatformOAuthState(UUIDPk, Base):
    """Single-use OAuth state bound to the user *and* login session that started it."""

    __tablename__ = "platform_oauth_states"

    state: Mapped[str] = mapped_column(String(128), unique=True)
    provider: Mapped[PlatformProvider] = mapped_column(db_enum(PlatformProvider, "platform_provider"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_sessions.id", ondelete="CASCADE")
    )
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalMeetingReference(UUIDPk, Timestamps, Base):
    """Links an app meeting to a provider meeting. One source per app meeting;
    a provider meeting can be linked to only one app meeting, so webhook
    events can never fan out into other projects."""

    __tablename__ = "external_meeting_refs"
    __table_args__ = (
        UniqueConstraint("meeting_id", name="uq_external_meeting_ref_meeting"),
        UniqueConstraint("provider", "provider_meeting_id", name="uq_external_meeting_ref_provider_meeting"),
        Index("ix_external_meeting_refs_next_check", "transcript_status", "next_check_at"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"))
    provider: Mapped[PlatformProvider] = mapped_column(db_enum(PlatformProvider, "platform_provider"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_connections.id", ondelete="SET NULL")
    )
    linked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Provider identifier: Graph onlineMeeting id (resolved from the join URL),
    # Zoom numeric meeting id, or Meet meeting code / conferenceRecords/{id}.
    provider_meeting_id: Mapped[str] = mapped_column(String(512))
    join_url: Mapped[str | None] = mapped_column(String(2048))
    resolved_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    transcript_status: Mapped[ExternalTranscriptStatus] = mapped_column(
        db_enum(ExternalTranscriptStatus, "external_transcript_status"), default=ExternalTranscriptStatus.unknown
    )
    status_message: Mapped[str | None] = mapped_column(String(500))
    fetch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    live_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class ProviderEvent(UUIDPk, Base):
    """Every inbound provider event (webhook) after signature verification.
    The unique dedup key gives replay protection and idempotency; no
    transcript text or tokens are stored here."""

    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("provider", "dedup_key", name="uq_provider_event_dedup"),
        Index("ix_provider_events_received", "received_at"),
    )

    provider: Mapped[PlatformProvider] = mapped_column(db_enum(PlatformProvider, "platform_provider"))
    dedup_key: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ProviderEventStatus] = mapped_column(
        db_enum(ProviderEventStatus, "provider_event_status"), default=ProviderEventStatus.accepted
    )
    detail: Mapped[str | None] = mapped_column(String(300))  # safe category/message only
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
