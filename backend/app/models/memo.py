from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    ActionStatus,
    Confidence,
    IssueStatus,
    Language,
    Likelihood,
    MemoStatus,
    Priority,
    VerificationStatus,
    db_enum,
)


class Memo(UUIDPk, Timestamps, Base):
    """The current memo for a meeting.

    Narrative sections (summary, discussion, open questions, next meeting, PM
    view) are JSONB validated by ``app.schemas.memo_content``; trackable items
    (decisions, actions, issues, risks) are relational rows so they can be
    filtered, assigned and linked back to transcript entries.
    """

    __tablename__ = "memos"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), unique=True
    )
    language: Mapped[Language] = mapped_column(db_enum(Language, "language"))
    status: Mapped[MemoStatus] = mapped_column(db_enum(MemoStatus, "memo_status"), index=True)
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    discussion: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    open_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    next_meeting: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pm_view: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generation_error: Mapped[str | None] = mapped_column(String(500))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    generation_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class _MemoItem(UUIDPk, Timestamps):
    """Columns shared by all extracted items."""

    memo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memos.id", ondelete="CASCADE"), index=True
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    # Denormalized for project-scoped queries (always equals meeting.project_id).
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(16))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        db_enum(VerificationStatus, "verification_status"), default=VerificationStatus.draft
    )
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[Confidence | None] = mapped_column(db_enum(Confidence, "confidence"))
    review_note: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Owner as literally stated in the meeting; owner_user_id only when a human links it.
    owner_text: Mapped[str | None] = mapped_column(String(200))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Decision(_MemoItem, Base):
    __tablename__ = "decisions"

    statement: Mapped[str] = mapped_column(Text)
    source_links: Mapped[list[MemoItemSource]] = relationship(
        primaryjoin="Decision.id == MemoItemSource.decision_id", cascade="all, delete-orphan", viewonly=False
    )


class Issue(_MemoItem, Base):
    __tablename__ = "issues"

    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IssueStatus] = mapped_column(db_enum(IssueStatus, "issue_status"), default=IssueStatus.open)
    priority: Mapped[Priority] = mapped_column(db_enum(Priority, "priority"), default=Priority.medium)
    follow_up: Mapped[str | None] = mapped_column(Text)
    source_links: Mapped[list[MemoItemSource]] = relationship(
        primaryjoin="Issue.id == MemoItemSource.issue_id", cascade="all, delete-orphan"
    )


class Risk(_MemoItem, Base):
    __tablename__ = "risks"

    description: Mapped[str] = mapped_column(Text)
    probability: Mapped[Likelihood] = mapped_column(db_enum(Likelihood, "probability"), default=Likelihood.unknown)
    impact: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Priority] = mapped_column(db_enum(Priority, "severity"), default=Priority.medium)
    mitigation: Mapped[str | None] = mapped_column(Text)
    source_links: Mapped[list[MemoItemSource]] = relationship(
        primaryjoin="Risk.id == MemoItemSource.risk_id", cascade="all, delete-orphan"
    )


class ActionItem(_MemoItem, Base):
    __tablename__ = "action_items"
    __table_args__ = (Index("ix_action_items_project_status_due", "project_id", "status", "due_date"),)

    description: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    # Original deadline wording ("来週金曜日", "next Friday") is always retained.
    due_text: Mapped[str | None] = mapped_column(String(200))
    due_needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[Priority] = mapped_column(db_enum(Priority, "priority"), default=Priority.medium)
    status: Mapped[ActionStatus] = mapped_column(db_enum(ActionStatus, "action_status"), default=ActionStatus.open)
    related_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id", ondelete="SET NULL")
    )
    related_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_links: Mapped[list[MemoItemSource]] = relationship(
        primaryjoin="ActionItem.id == MemoItemSource.action_item_id", cascade="all, delete-orphan"
    )


class MemoItemSource(UUIDPk, Base):
    """Link from an extracted item to the transcript entries that support it.
    Exactly one item FK is set (enforced by a CHECK constraint)."""

    __tablename__ = "memo_item_sources"
    __table_args__ = (
        CheckConstraint(
            "(decision_id IS NOT NULL)::int + (action_item_id IS NOT NULL)::int"
            " + (issue_id IS NOT NULL)::int + (risk_id IS NOT NULL)::int = 1",
            name="exactly_one_item",
        ),
    )

    transcript_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_entries.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id", ondelete="CASCADE"), index=True
    )
    action_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("action_items.id", ondelete="CASCADE"), index=True
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    risk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"), index=True
    )
