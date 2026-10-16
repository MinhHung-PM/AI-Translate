"""Connector contract shared by Teams, Zoom and Google Meet.

Operations a connector does not support raise ``IntegrationError(unsupported)``
— callers must consult ``get_capabilities`` first; the UI disables actions
that are not ``available``.
"""

from __future__ import annotations

import json
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.integrations.capabilities import CapabilityState
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.http import ProviderHttp
from app.integrations.models import CanonicalEvent
from app.models.enums import ExternalTranscriptStatus, PlatformProvider


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scopes: set[str]


@dataclass
class AccountInfo:
    account_id: str
    display: str


@dataclass
class AvailableMeeting:
    provider_meeting_id: str
    title: str
    start: datetime | None
    end: datetime | None
    join_url: str | None = None
    has_transcript: bool | None = None  # None = unknown until fetched


@dataclass
class ResolvedMeeting:
    provider_meeting_id: str
    join_url: str | None
    title: str | None
    resolved_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class TranscriptFetchResult:
    status: ExternalTranscriptStatus
    events: list[CanonicalEvent]
    message: str
    speaker_attribution: bool = True


@dataclass
class HealthResult:
    ok: bool
    message: str
    capabilities: list[CapabilityState]


class Connector(ABC):
    provider: PlatformProvider
    display_name: str
    #: default real endpoints; keys are logical names
    default_endpoints: dict[str, str] = {}
    supports_pkce: bool = True

    def __init__(self) -> None:
        self.http = ProviderHttp(self.map_error)

    # ---- configuration -------------------------------------------------
    @abstractmethod
    def configuration_problems(self) -> list[str]:
        """Missing operator configuration (empty list = configured)."""

    def is_configured(self) -> bool:
        return not self.configuration_problems()

    def override_base(self, raw: str | None = None) -> str | None:
        raw = (get_settings().integration_endpoint_overrides if raw is None else raw).strip()
        if not raw:
            return None
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError:
            return None
        value = mapping.get(self.provider.value) if isinstance(mapping, dict) else None
        return str(value).rstrip("/") if value else None

    def is_sandbox(self) -> bool:
        return self.override_base() is not None

    def endpoint(self, name: str) -> str:
        base = self.override_base()
        return f"{base}/{name}" if base else self.default_endpoints[name]

    def map_error(self, resp: Any) -> IntegrationError:
        from app.integrations.http import default_error

        return default_error(resp)

    # ---- capabilities ----------------------------------------------------
    @abstractmethod
    def get_capabilities(self, scopes: set[str] | None, connected: bool) -> list[CapabilityState]: ...

    # ---- authorization ---------------------------------------------------
    @abstractmethod
    def requested_scopes(self) -> list[str]: ...

    def authorization_params(self) -> dict[str, str]:
        return {}

    def begin_authorization(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            **self.authorization_params(),
        }
        scopes = self.requested_scopes()
        if scopes:
            params["scope"] = " ".join(scopes)
        if self.supports_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        # Sandbox only: the browser may need a different host for the fake provider than the API does.
        browser_base = self.override_base(get_settings().integration_browser_endpoint_overrides)
        authorize = f"{browser_base}/authorize" if browser_base and self.is_sandbox() else self.endpoint("authorize")
        return f"{authorize}?{urllib.parse.urlencode(params)}"

    @abstractmethod
    def client_id(self) -> str: ...

    @abstractmethod
    def client_secret(self) -> str: ...

    def token_request_auth(self) -> tuple[str, str] | None:
        return None  # credentials in form body by default

    def _token_call(self, form: dict[str, str]) -> TokenSet:
        auth = self.token_request_auth()
        if auth is None:
            form = {**form, "client_id": self.client_id(), "client_secret": self.client_secret()}
        resp = self.http.request("POST", self.endpoint("token"), data=form, auth=auth)
        try:
            body = resp.json()
            access = str(body["access_token"])
        except (ValueError, KeyError, TypeError):
            raise IntegrationError(
                ErrorCategory.invalid_response, "Token endpoint returned an invalid response"
            ) from None
        scope_raw = body.get("scope")
        scopes = set(str(scope_raw).replace(",", " ").split()) if scope_raw else set()
        expires = body.get("expires_in")
        return TokenSet(
            access_token=access,
            refresh_token=body.get("refresh_token"),
            expires_in=int(expires) if expires is not None else None,
            scopes=scopes,
        )

    def complete_authorization(self, code: str, code_verifier: str, redirect_uri: str) -> TokenSet:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        if self.supports_pkce:
            form["code_verifier"] = code_verifier
        return self._token_call(form)

    def refresh_credentials(self, refresh_token: str) -> TokenSet:
        return self._token_call({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(self, tokens: TokenSet) -> bool:
        """Best-effort provider-side revocation. Returns False when unsupported."""
        return False

    @abstractmethod
    def fetch_account(self, access_token: str) -> AccountInfo: ...

    # ---- operations --------------------------------------------------------
    def health_check(self, access_token: str, scopes: set[str]) -> HealthResult:
        account = self.fetch_account(access_token)
        return HealthResult(True, f"Connected as {account.display}", self.get_capabilities(scopes, True))

    def list_available_meetings(self, access_token: str) -> list[AvailableMeeting]:
        raise IntegrationError(ErrorCategory.unsupported, "Listing meetings is not supported for this platform")

    @abstractmethod
    def resolve_meeting(self, access_token: str, reference: str) -> ResolvedMeeting: ...

    @abstractmethod
    def fetch_transcript(self, access_token: str, ref: ResolvedMeeting) -> TranscriptFetchResult: ...

    def subscribe_to_meeting_events(self, *_: Any) -> None:
        raise IntegrationError(ErrorCategory.unsupported, "Event subscriptions are not supported for this platform")

    def start_realtime_ingestion(self, *_: Any) -> None:
        raise IntegrationError(ErrorCategory.unsupported, "Live ingestion is not supported for this platform")

    def stop_realtime_ingestion(self, *_: Any) -> None:
        raise IntegrationError(ErrorCategory.unsupported, "Live ingestion is not supported for this platform")
