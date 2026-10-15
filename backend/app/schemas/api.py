"""Request/response schemas for the v1 REST API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, HttpUrl, field_validator

from app.ai.base import Capability
from app.models.enums import (
    ActionStatus,
    Confidence,
    GlobalRole,
    IssueStatus,
    JobKind,
    JobStatus,
    KeyStorage,
    Language,
    Likelihood,
    LiveSessionStatus,
    MeetingPlatform,
    MeetingStatus,
    MeetingType,
    MemoStatus,
    Priority,
    ProjectRole,
    ProjectStatus,
    TranscriptFormat,
    TranslationStatus,
    VerificationStatus,
)
from app.schemas.common import ApiModel, InModel, LongText, Name, ShortText

_TIMEZONES = available_timezones()

# ---- Auth / users ------------------------------------------------------------


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: GlobalRole
    is_active: bool
    locale: str


class SessionInfo(ApiModel):
    user: UserOut
    csrf_token: str
    auth_mode: str
    expires_at: datetime
    features: dict[str, bool]


class DevLoginIn(InModel):
    email: EmailStr


class DevUserOut(ApiModel):
    email: str
    display_name: str
    role: GlobalRole


class ProfileUpdate(InModel):
    display_name: Name | None = None
    locale: Literal["vi", "en", "ja"] | None = None


class AdminUserCreate(InModel):
    email: EmailStr
    display_name: Name
    role: GlobalRole = GlobalRole.member


class AdminUserUpdate(InModel):
    display_name: Name | None = None
    role: GlobalRole | None = None
    is_active: bool | None = None


class DivisionIn(InModel):
    name: Name
    description: LongText | None = None


class DivisionOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None


class DivisionAssignmentIn(InModel):
    user_id: uuid.UUID
    division_id: uuid.UUID
    can_view_transcripts: bool = False


class DivisionAssignmentOut(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    division_id: uuid.UUID
    can_view_transcripts: bool


class AuditEventOut(ApiModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    project_id: uuid.UUID | None
    details: dict[str, Any]
    created_at: datetime


# ---- Projects -------------------------------------------------------------


class ProjectIn(InModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
    name: Name
    description: LongText | None = None
    client_name: Name | None = None
    division_id: uuid.UUID | None = None
    retention_days: int = Field(default=365, ge=1, le=3650)
    default_source_language: Language = Language.ja
    default_target_language: Language = Language.vi
    default_memo_language: Language = Language.vi
    translation_instructions: LongText | None = None


class ProjectUpdate(InModel):
    name: Name | None = None
    description: LongText | None = None
    client_name: Name | None = None
    division_id: uuid.UUID | None = None
    status: ProjectStatus | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    default_source_language: Language | None = None
    default_target_language: Language | None = None
    default_memo_language: Language | None = None
    translation_instructions: LongText | None = None


class ProjectOut(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    client_name: str | None
    division_id: uuid.UUID | None
    status: ProjectStatus
    retention_days: int
    default_source_language: Language
    default_target_language: Language
    default_memo_language: Language
    translation_instructions: str | None
    created_at: datetime
    my_role: ProjectRole | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)


class MemberIn(InModel):
    user_id: uuid.UUID | None = None
    email: EmailStr | None = None
    role: ProjectRole = ProjectRole.member


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: ProjectRole


class GlossaryIn(InModel):
    source_term: Name
    preferred_translation: Name
    source_language: Language
    target_language: Language
    context: LongText | None = None
    is_active: bool = True


class GlossaryUpdate(InModel):
    source_term: Name | None = None
    preferred_translation: Name | None = None
    context: LongText | None = None
    is_active: bool | None = None


class GlossaryOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_term: str
    preferred_translation: str
    source_language: Language
    target_language: Language
    context: str | None
    is_active: bool


# ---- Meetings -------------------------------------------------------------


class ParticipantIn(InModel):
    display_name: Name
    organization: Name | None = None
    role_label: str | None = Field(default=None, max_length=100)


class ParticipantOut(ApiModel):
    id: uuid.UUID
    display_name: str
    organization: str | None
    role_label: str | None


class MeetingIn(InModel):
    project_id: uuid.UUID
    title: ShortText
    meeting_type: MeetingType = MeetingType.client_meeting
    scheduled_at: datetime
    timezone: str = "Asia/Tokyo"
    platform: MeetingPlatform = MeetingPlatform.manual_import
    meeting_url: HttpUrl | None = None
    objective: LongText | None = None
    custom_instructions: str | None = Field(default=None, max_length=2000)
    source_language: Language | None = None  # None => auto-detect
    target_language: Language = Language.vi
    memo_language: Language = Language.vi
    participants: list[ParticipantIn] = Field(default_factory=list, max_length=100)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v not in _TIMEZONES:
            raise ValueError("Unknown IANA timezone")
        return v

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v


class MeetingUpdate(InModel):
    title: ShortText | None = None
    meeting_type: MeetingType | None = None
    scheduled_at: datetime | None = None
    timezone: str | None = None
    meeting_url: HttpUrl | None = None
    objective: LongText | None = None
    custom_instructions: str | None = Field(default=None, max_length=2000)
    source_language: Language | None = None
    target_language: Language | None = None
    memo_language: Language | None = None
    participants: list[ParticipantIn] | None = Field(default=None, max_length=100)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and v not in _TIMEZONES:
            raise ValueError("Unknown IANA timezone")
        return v


class MeetingOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    title: str
    meeting_type: MeetingType
    scheduled_at: datetime
    timezone: str
    platform: MeetingPlatform
    platform_status: str = "available"
    meeting_url: str | None
    objective: str | None
    custom_instructions: str | None
    source_language: Language | None
    detected_language: Language | None
    target_language: Language
    memo_language: Language
    status: MeetingStatus
    created_by_id: uuid.UUID | None
    created_at: datetime
    content_purged_at: datetime | None
    participants: list[ParticipantOut] = Field(default_factory=list)
    memo_status: MemoStatus | None = None
    entry_count: int = 0
    permissions: dict[str, bool] = Field(default_factory=dict)


# ---- Transcript -------------------------------------------------------------


class TextImportIn(InModel):
    text: str = Field(min_length=1)
    format: TranscriptFormat = TranscriptFormat.text
    source_language: Language | None = None
    replace: bool = False


class ImportOut(ApiModel):
    id: uuid.UUID
    format: TranscriptFormat
    filename: str | None
    byte_size: int
    encoding: str
    entry_count: int
    detected_language: Language | None
    created_at: datetime


class TranslationOut(ApiModel):
    id: uuid.UUID
    target_language: Language
    text: str | None
    status: TranslationStatus
    error_message: str | None
    ambiguity_note: str | None
    provider: str | None
    model: str | None
    is_user_edited: bool
    updated_at: datetime


class EntryOut(ApiModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    sequence: int
    speaker_label: str | None
    start_ms: int | None
    end_ms: int | None
    original_text: str
    source_language: Language | None
    original_edited: bool
    source_metadata: dict[str, Any]
    translation: TranslationOut | None = None


class EntryUpdate(InModel):
    original_text: str | None = Field(default=None, min_length=1, max_length=20_000)
    speaker_label: str | None = Field(default=None, max_length=200)
    source_language: Language | None = None


class TranslationUpdate(InModel):
    text: str = Field(min_length=1, max_length=20_000)
    target_language: Language


class TranslateIn(InModel):
    target_language: Language | None = None
    entry_ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)
    only_failed: bool = False
    force: bool = False


class TranslationStats(ApiModel):
    total: int
    done: int
    failed: int
    pending: int
    processing: int


class JobOut(ApiModel):
    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    meeting_id: uuid.UUID | None
    progress_done: int
    progress_total: int
    attempts: int
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ReplayIn(InModel):
    text: str | None = None
    format: TranscriptFormat = TranscriptFormat.text
    interval_seconds: float = Field(default=1.5, ge=0, le=10)
    translate: bool = True


class LiveSessionOut(ApiModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    connector: str
    is_demo: bool
    status: LiveSessionStatus
    entries_total: int
    entries_emitted: int
    started_at: datetime
    ended_at: datetime | None
    job_id: uuid.UUID | None


class LiveFeedOut(ApiModel):
    session: LiveSessionOut | None
    entries: list[EntryOut]


# ---- Memo ------------------------------------------------------------------


class SourceRefOut(ApiModel):
    entry_id: uuid.UUID
    sequence: int
    speaker_label: str | None
    start_ms: int | None
    excerpt: str | None  # None when the viewer lacks transcript access


class _ItemOutBase(ApiModel):
    id: uuid.UUID
    memo_id: uuid.UUID
    meeting_id: uuid.UUID
    project_id: uuid.UUID
    code: str
    verification_status: VerificationStatus
    ai_generated: bool
    confidence: Confidence | None
    review_note: str | None
    owner_text: str | None
    owner_user_id: uuid.UUID | None
    sort_order: int
    sources: list[SourceRefOut] = Field(default_factory=list)


class DecisionOut(_ItemOutBase):
    statement: str


class IssueOut(_ItemOutBase):
    description: str
    impact: str | None
    status: IssueStatus
    priority: Priority
    follow_up: str | None


class RiskOut(_ItemOutBase):
    description: str
    probability: Likelihood
    impact: str | None
    severity: Priority
    mitigation: str | None


class ActionItemOut(_ItemOutBase):
    description: str
    due_date: date | None
    due_text: str | None
    due_needs_confirmation: bool
    priority: Priority
    status: ActionStatus
    related_decision_id: uuid.UUID | None
    related_issue_id: uuid.UUID | None
    completed_at: datetime | None
    is_overdue: bool = False
    meeting_title: str | None = None
    project_name: str | None = None


class _ItemInBase(InModel):
    owner_text: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None
    source_entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    review_note: str | None = Field(default=None, max_length=2000)


class DecisionIn(_ItemInBase):
    statement: str = Field(min_length=1, max_length=2000)


class DecisionPatch(InModel):
    statement: str | None = Field(default=None, min_length=1, max_length=2000)
    owner_text: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None
    verification_status: VerificationStatus | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    source_entry_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class ActionItemIn(_ItemInBase):
    description: str = Field(min_length=1, max_length=2000)
    due_date: date | None = None
    due_text: str | None = Field(default=None, max_length=200)
    priority: Priority = Priority.medium
    related_decision_id: uuid.UUID | None = None


class ActionItemPatch(InModel):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    owner_text: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None
    due_text: str | None = Field(default=None, max_length=200)
    due_needs_confirmation: bool | None = None
    priority: Priority | None = None
    status: ActionStatus | None = None
    verification_status: VerificationStatus | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    related_decision_id: uuid.UUID | None = None
    source_entry_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class IssueIn(_ItemInBase):
    description: str = Field(min_length=1, max_length=2000)
    impact: str | None = Field(default=None, max_length=1000)
    status: IssueStatus = IssueStatus.open
    priority: Priority = Priority.medium
    follow_up: str | None = Field(default=None, max_length=1000)


class IssuePatch(InModel):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    impact: str | None = Field(default=None, max_length=1000)
    owner_text: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None
    status: IssueStatus | None = None
    priority: Priority | None = None
    follow_up: str | None = Field(default=None, max_length=1000)
    verification_status: VerificationStatus | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    source_entry_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class RiskIn(_ItemInBase):
    description: str = Field(min_length=1, max_length=2000)
    probability: Likelihood = Likelihood.unknown
    impact: str | None = Field(default=None, max_length=1000)
    severity: Priority = Priority.medium
    mitigation: str | None = Field(default=None, max_length=1000)


class RiskPatch(InModel):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    probability: Likelihood | None = None
    impact: str | None = Field(default=None, max_length=1000)
    severity: Priority | None = None
    mitigation: str | None = Field(default=None, max_length=1000)
    owner_text: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None
    verification_status: VerificationStatus | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    source_entry_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class DiscussionTopicIO(InModel):
    topic: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(default_factory=list, max_length=50)
    source_entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class OpenQuestionIO(InModel):
    question: str = Field(min_length=1, max_length=1000)
    source_entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class NextMeetingIO(InModel):
    when_text: str | None = Field(default=None, max_length=200)
    agenda: list[str] = Field(default_factory=list, max_length=30)
    source_entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class PMAssessmentIO(InModel):
    assessment: str = Field(min_length=1, max_length=1000)
    basis: Literal["evidence", "ai_suggestion", "human"]
    source_entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class PMViewIO(InModel):
    schedule: PMAssessmentIO | None = None
    scope: PMAssessmentIO | None = None
    quality: PMAssessmentIO | None = None
    cost: PMAssessmentIO | None = None
    customer_satisfaction: PMAssessmentIO | None = None
    escalation: PMAssessmentIO | None = None


class MemoUpdate(InModel):
    executive_summary: str | None = Field(default=None, max_length=10_000)
    discussion: list[DiscussionTopicIO] | None = Field(default=None, max_length=50)
    open_questions: list[OpenQuestionIO] | None = Field(default=None, max_length=100)
    next_meeting: NextMeetingIO | None = None
    pm_view: PMViewIO | None = None
    clear_next_meeting: bool = False


class ReviewIn(InModel):
    comment: str | None = Field(default=None, max_length=2000)


class MeetingInfoOut(ApiModel):
    title: str
    project_name: str
    scheduled_at: datetime
    timezone: str
    participants: list[str]
    objective: str | None
    source_language: Language | None
    memo_language: Language


class MemoOut(ApiModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    language: Language
    status: MemoStatus
    executive_summary: str
    discussion: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    next_meeting: dict[str, Any] | None
    pm_view: dict[str, Any] | None
    generation_error: str | None
    prompt_version: str | None
    provider: str | None
    model: str | None
    generated_at: datetime | None
    generation_count: int
    reviewed_by_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    updated_at: datetime
    meeting_info: MeetingInfoOut
    decisions: list[DecisionOut]
    action_items: list[ActionItemOut]
    issues: list[IssueOut]
    risks: list[RiskOut]
    unreviewed_items: int
    permissions: dict[str, bool]


# ---- Providers / usage / dashboard ------------------------------------------


class ProviderModelOut(ApiModel):
    id: str
    label: str | None
    input_per_1m: Decimal | None
    output_per_1m: Decimal | None


class ProviderCatalogOut(ApiModel):
    key: str
    display_name: str
    requires_api_key: bool
    allow_custom_base_url: bool
    allow_custom_model: bool
    dev_only: bool
    capabilities: list[Capability]
    models: list[ProviderModelOut]


class ProviderSettingsOut(ApiModel):
    providers: list[ProviderCatalogOut]
    secret_storage_available: bool
    remember_key_supported: bool


class ProviderConfigIn(InModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    # Write-only. Never echoed back.
    api_key: str | None = Field(default=None, max_length=512, repr=False)
    remember: bool = False
    make_default: bool = True


class ProviderConfigOut(ApiModel):
    id: uuid.UUID
    provider: str
    model: str
    base_url: str | None
    is_default: bool
    key_storage: KeyStorage
    key_hint: str | None
    has_usable_key: bool = False
    key_updated_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    last_tested_at: datetime | None


class ConnectionTestOut(ApiModel):
    ok: bool
    message: str
    models: list[str] | None = None


class UsageSummaryOut(ApiModel):
    total_requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    failed_requests: int
    processing_ms: int
    requests_with_estimated_tokens: int
    by_model: list[dict[str, Any]]
    by_operation: list[dict[str, Any]]
    by_project: list[dict[str, Any]]
    by_meeting: list[dict[str, Any]]
    cost_note: str


class ConnectorStatusOut(ApiModel):
    key: str
    display_name: str
    state: str
    message: str
    supports_live: bool
    supports_transcript_import: bool
