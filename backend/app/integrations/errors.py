"""Normalized integration errors. ``message`` is always safe to show users:
provider response bodies are never passed through verbatim."""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    not_configured = "not_configured"
    not_connected = "not_connected"
    invalid_credentials = "invalid_credentials"
    token_expired = "token_expired"
    consent_revoked = "consent_revoked"
    insufficient_scope = "insufficient_scope"
    admin_approval_required = "admin_approval_required"
    unsupported_account = "unsupported_account"
    unsupported = "unsupported"
    meeting_not_found = "meeting_not_found"
    no_meeting_access = "no_meeting_access"
    transcript_unavailable = "transcript_unavailable"
    transcript_pending = "transcript_pending"
    rate_limited = "rate_limited"
    provider_unavailable = "provider_unavailable"
    invalid_signature = "invalid_signature"
    invalid_request = "invalid_request"
    invalid_response = "invalid_response"


# Categories that will never succeed by retrying without a human action.
NON_RETRYABLE = {
    ErrorCategory.not_configured,
    ErrorCategory.not_connected,
    ErrorCategory.invalid_credentials,
    ErrorCategory.consent_revoked,
    ErrorCategory.insufficient_scope,
    ErrorCategory.admin_approval_required,
    ErrorCategory.unsupported_account,
    ErrorCategory.unsupported,
    ErrorCategory.meeting_not_found,
    ErrorCategory.no_meeting_access,
    ErrorCategory.transcript_unavailable,
    ErrorCategory.invalid_signature,
    ErrorCategory.invalid_request,
}


class IntegrationError(Exception):
    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        retry_after: float | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.retry_after = retry_after
        # Provider error *code* (e.g. GraphAccessToTranscriptsDisabled) — never a raw body.
        self.provider_code = provider_code

    @property
    def retryable(self) -> bool:
        return self.category not in NON_RETRYABLE
