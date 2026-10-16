"""Typed capability declarations.

A capability's status is computed from what the connector implements, the
operator configuration, the permissions actually granted to the user's
connection, and the current session — never from the provider's name.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Capability(StrEnum):
    transcript_import = "transcript_import"
    list_meetings = "list_meetings"
    post_meeting_transcript = "post_meeting_transcript"
    live_transcript = "live_transcript"
    live_audio = "live_audio"
    speaker_metadata = "speaker_metadata"
    meeting_event_notifications = "meeting_event_notifications"
    recovery_after_disconnect = "recovery_after_disconnect"


class CapabilityStatus(StrEnum):
    available = "available"
    requires_configuration = "requires_configuration"  # operator must configure the app
    requires_user_consent = "requires_user_consent"  # user must connect / re-consent
    requires_admin_approval = "requires_admin_approval"  # tenant/account admin decision
    not_supported = "not_supported"  # not possible with the selected integration method
    temporarily_unavailable = "temporarily_unavailable"


class CapabilityState(BaseModel):
    capability: Capability
    status: CapabilityStatus
    message: str
    remediation: str | None = None
    # True when only exercised against mocks/sandbox, never a real provider.
    verified_live: bool = False


def cap(
    capability: Capability, status: CapabilityStatus, message: str, remediation: str | None = None
) -> CapabilityState:
    return CapabilityState(capability=capability, status=status, message=message, remediation=remediation)
