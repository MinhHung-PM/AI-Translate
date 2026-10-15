from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import (
    Language,
    LiveSessionStatus,
    MeetingPlatform,
    MeetingStatus,
    MeetingType,
    TranscriptFormat,
    TranslationStatus,
    db_enum,
)
from app.models.project import Project


class Meeting(UUIDPk, Timestamps, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_project_scheduled", "project_id", "scheduled_at"),
        Index("ix_meetings_title", "title"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    meeting_type: Mapped[MeetingType] = mapped_column(db_enum(MeetingType, "meeting_type"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    platform: Mapped[MeetingPlatform] = mapped_column(db_enum(MeetingPlatform, "meeting_platform"))
    meeting_url: Mapped[str | None] = mapped_column(String(2048))
    objective: Mapped[str | None] = mapped_column(Text)
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    # None => auto-detect at import time.
    source_language: Mapped[Language | None] = mapped_column(db_enum(Language, "source_language"))
    detected_language: Mapped[Language | None] = mapped_column(db_enum(Language, "detected_language"))
    target_language: Mapped[Language] = mapped_column(db_enum(Language, "target_language"))
    memo_language: Mapped[Language] = mapped_column(db_enum(Language, "memo_language"))
    status: Mapped[MeetingStatus] = mapped_column(
        db_enum(MeetingStatus, "meeting_status"), default=MeetingStatus.planned, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    participants: Mapped[list[MeetingParticipant]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="MeetingParticipant.sort_order"
    )

    @property
    def effective_source_language(self) -> Language | None:
        return self.source_language or self.detected_language


class MeetingParticipant(UUIDPk, Timestamps, Base):
    __tablename__ = "meeting_participants"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200))
    role_label: Mapped[str | None] = mapped_column(String(100))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped[Meeting] = relationship(back_populates="participants")


class TranscriptImport(UUIDPk, Base):
    __tablename__ = "transcript_imports"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[TranscriptFormat] = mapped_column(db_enum(TranscriptFormat, "transcript_format"))
    filename: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    encoding: Mapped[str] = mapped_column(String(32))
    entry_count: Mapped[int] = mapped_column(Integer)
    detected_language: Mapped[Language | None] = mapped_column(db_enum(Language, "detected_language"))
    is_replay: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TranscriptEntry(UUIDPk, Timestamps, Base):
    """One normalized utterance. Speaker and timestamps are nullable and are
    never synthesized when the source does not contain them."""

    __tablename__ = "transcript_entries"
    __table_args__ = (UniqueConstraint("meeting_id", "sequence", name="uq_transcript_entry_seq"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_imports.id", ondelete="SET NULL")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    speaker_label: Mapped[str | None] = mapped_column(String(200))
    start_ms: Mapped[int | None] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger)
    original_text: Mapped[str] = mapped_column(Text)
    source_language: Mapped[Language | None] = mapped_column(db_enum(Language, "source_language"))
    original_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    translations: Mapped[list[Translation]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class Translation(UUIDPk, Timestamps, Base):
    """AI (or user-corrected) translation, stored separately so the original
    transcript text is never overwritten."""

    __tablename__ = "translations"
    __table_args__ = (
        UniqueConstraint("entry_id", "target_language", name="uq_translation_entry_lang"),
        Index("ix_translations_status", "status"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_entries.id", ondelete="CASCADE")
    )
    target_language: Mapped[Language] = mapped_column(db_enum(Language, "target_language"))
    text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TranslationStatus] = mapped_column(
        db_enum(TranslationStatus, "translation_status"), default=TranslationStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(String(500))
    ambiguity_note: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))

    entry: Mapped[TranscriptEntry] = relationship(back_populates="translations")


class LiveSession(UUIDPk, Base):
    """A live-style transcript feed. In Workstream 1 the only connector is
    ``replay`` and every session is flagged ``is_demo``."""

    __tablename__ = "live_sessions"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    connector: Mapped[str] = mapped_column(String(32))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[LiveSessionStatus] = mapped_column(
        db_enum(LiveSessionStatus, "live_session_status"), default=LiveSessionStatus.running
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    entries_total: Mapped[int] = mapped_column(Integer, default=0)
    entries_emitted: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
