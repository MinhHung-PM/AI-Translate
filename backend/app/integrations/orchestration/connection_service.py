"""Truthful connection status and capability reporting for the UI.

"Connected" is reported only after the OAuth flow finished *and* an
authenticated API call to the provider succeeded (``complete`` performs it;
``test`` repeats it). Entering client credentials never produces "Connected".
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.integrations import oauth
from app.integrations.base import Connector
from app.integrations.capabilities import Capability, CapabilityState, CapabilityStatus
from app.integrations.errors import IntegrationError
from app.models import PlatformConnection, User
from app.models.enums import ConnectionState


class DisplayStatus(StrEnum):
    not_configured = "not_configured"
    not_connected = "not_connected"
    awaiting_authorization = "awaiting_authorization"
    connected = "connected"
    connected_post_meeting_only = "connected_post_meeting_only"
    admin_approval_required = "admin_approval_required"
    temporarily_disconnected = "temporarily_disconnected"
    error = "error"


class ConnectionView(BaseModel):
    provider: str
    display_name: str
    configured: bool
    configuration_problems: list[str]
    sandbox: bool
    status: DisplayStatus
    account: str | None
    granted_scopes: list[str]
    requested_scopes: list[str]
    capabilities: list[CapabilityState]
    last_attempt_at: str | None
    last_success_at: str | None
    last_event_at: str | None
    last_error_category: str | None
    last_error_message: str | None
    reconnect_count: int
    redirect_uri: str | None


def display_status(connector: Connector, conn: PlatformConnection | None, caps: list[CapabilityState]) -> DisplayStatus:
    if not connector.is_configured():
        return DisplayStatus.not_configured
    if conn is None:
        return DisplayStatus.not_connected
    match conn.state:
        case ConnectionState.awaiting_authorization:
            return DisplayStatus.awaiting_authorization
        case ConnectionState.admin_approval_required:
            return DisplayStatus.admin_approval_required
        case ConnectionState.error:
            return DisplayStatus.error
        case ConnectionState.temporarily_disconnected:
            return DisplayStatus.temporarily_disconnected
    live = next((c for c in caps if c.capability == Capability.live_transcript), None)
    post = next((c for c in caps if c.capability == Capability.post_meeting_transcript), None)
    if post is not None and post.status == CapabilityStatus.requires_admin_approval:
        return DisplayStatus.admin_approval_required
    if live is not None and live.status == CapabilityStatus.available:
        return DisplayStatus.connected
    return DisplayStatus.connected_post_meeting_only


def view(db: Session, user: User, connector: Connector) -> ConnectionView:
    conn = oauth.get_connection(db, user, connector)
    connected = conn is not None and conn.state in (ConnectionState.connected, ConnectionState.temporarily_disconnected)
    scopes = conn.scopes() if conn else set()
    caps = connector.get_capabilities(scopes, connected)
    try:
        redirect = oauth.redirect_uri(connector.provider.value)
    except IntegrationError:
        redirect = None

    def iso(v: object) -> str | None:
        return v.isoformat() if v is not None else None  # type: ignore[attr-defined]

    return ConnectionView(
        provider=connector.provider.value,
        display_name=connector.display_name,
        configured=connector.is_configured(),
        configuration_problems=connector.configuration_problems(),
        sandbox=connector.is_sandbox(),
        status=display_status(connector, conn, caps),
        account=conn.account_display if conn else None,
        granted_scopes=sorted(scopes),
        requested_scopes=connector.requested_scopes(),
        capabilities=caps,
        last_attempt_at=iso(conn.last_attempt_at) if conn else None,
        last_success_at=iso(conn.last_success_at) if conn else None,
        last_event_at=iso(conn.last_event_at) if conn else None,
        last_error_category=conn.last_error_category if conn else None,
        last_error_message=conn.last_error_message if conn else None,
        reconnect_count=conn.reconnect_count if conn else 0,
        redirect_uri=redirect,
    )
