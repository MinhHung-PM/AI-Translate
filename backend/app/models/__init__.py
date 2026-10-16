"""Import all models so that metadata is complete for Alembic and tests."""

from app.models.audio import AudioSpeakerProfile
from app.models.identity import Division, DivisionAssignment, OidcLoginState, User, UserSession
from app.models.integration import (
    ExternalMeetingReference,
    PlatformConnection,
    PlatformCredential,
    PlatformOAuthState,
    ProviderEvent,
)
from app.models.meeting import (
    LiveSession,
    Meeting,
    MeetingParticipant,
    TranscriptEntry,
    TranscriptImport,
    Translation,
)
from app.models.memo import ActionItem, Decision, Issue, Memo, MemoItemSource, Risk
from app.models.ops import AIProviderConfiguration, AuditEvent, Job, SessionSecret, UsageRecord
from app.models.project import GlossaryEntry, Project, ProjectMembership

__all__ = [
    "AudioSpeakerProfile",
    "ExternalMeetingReference",
    "PlatformConnection",
    "PlatformCredential",
    "PlatformOAuthState",
    "ProviderEvent",
    "AIProviderConfiguration",
    "ActionItem",
    "AuditEvent",
    "Decision",
    "Division",
    "DivisionAssignment",
    "GlossaryEntry",
    "Issue",
    "Job",
    "LiveSession",
    "Meeting",
    "MeetingParticipant",
    "Memo",
    "MemoItemSource",
    "OidcLoginState",
    "Project",
    "ProjectMembership",
    "Risk",
    "SessionSecret",
    "TranscriptEntry",
    "TranscriptImport",
    "Translation",
    "UsageRecord",
    "User",
    "UserSession",
]
