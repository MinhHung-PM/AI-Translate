from __future__ import annotations

from enum import StrEnum

import sqlalchemy as sa


def db_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """VARCHAR + CHECK constraint (portable, easy to extend via migration)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class GlobalRole(StrEnum):
    member = "member"
    project_manager = "project_manager"
    division_manager = "division_manager"
    admin = "admin"


class ProjectRole(StrEnum):
    member = "member"
    manager = "manager"


class ProjectStatus(StrEnum):
    active = "active"
    archived = "archived"


class Language(StrEnum):
    ja = "ja"
    vi = "vi"
    en = "en"


class MeetingType(StrEnum):
    client_meeting = "client_meeting"
    internal = "internal"
    requirements = "requirements"
    review = "review"
    steering = "steering"
    standup = "standup"
    other = "other"


class MeetingPlatform(StrEnum):
    manual_import = "manual_import"
    teams = "teams"
    zoom = "zoom"
    google_meet = "google_meet"


class MeetingStatus(StrEnum):
    planned = "planned"
    transcript_ready = "transcript_ready"
    memo_draft = "memo_draft"
    completed = "completed"  # memo approved
    archived = "archived"


class TranscriptFormat(StrEnum):
    text = "text"
    txt = "txt"
    srt = "srt"
    vtt = "vtt"
    json = "json"


class TranslationStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class MemoStatus(StrEnum):
    generating = "generating"
    failed = "failed"
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"


class VerificationStatus(StrEnum):
    draft = "draft"
    needs_review = "needs_review"
    confirmed = "confirmed"
    rejected = "rejected"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ActionStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


class IssueStatus(StrEnum):
    open = "open"
    monitoring = "monitoring"
    resolved = "resolved"


class Likelihood(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class JobKind(StrEnum):
    translation = "translate"
    generate_memo = "generate_memo"
    replay = "replay"
    fetch_transcript = "fetch_transcript"  # WS2: post-meeting retrieval from a platform
    realtime_ingest = "realtime_ingest"  # WS2: live stream (Zoom RTMS)


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class KeyStorage(StrEnum):
    none = "none"
    session = "session"
    persistent = "persistent"


class LiveSessionStatus(StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"
    stopped = "stopped"
    waiting = "waiting"  # WS2: armed, waiting for the provider to start the stream
    interrupted = "interrupted"  # WS2: provider/connection dropped; may reconnect


class PlatformProvider(StrEnum):
    teams = "teams"
    zoom = "zoom"
    google_meet = "google_meet"


class ConnectionState(StrEnum):
    awaiting_authorization = "awaiting_authorization"
    connected = "connected"
    admin_approval_required = "admin_approval_required"
    error = "error"
    temporarily_disconnected = "temporarily_disconnected"


class ExternalTranscriptStatus(StrEnum):
    unknown = "unknown"
    pending = "pending"  # meeting ended / still processing; retried with bounded backoff
    available = "available"
    imported = "imported"
    not_available = "not_available"
    permission_denied = "permission_denied"
    failed = "failed"


class ProviderEventStatus(StrEnum):
    accepted = "accepted"
    processed = "processed"
    ignored = "ignored"
    failed = "failed"
