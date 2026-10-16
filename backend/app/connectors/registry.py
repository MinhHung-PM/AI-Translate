"""Platform status summary used by the meeting form. Derived from the
Workstream 2 integration framework so the UI never shows a platform as
available unless the server is configured and the user's connection works."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.connectors.base import ConnectorState, ConnectorStatus
from app.integrations.capabilities import Capability, CapabilityStatus
from app.integrations.orchestration.connection_service import DisplayStatus, view
from app.integrations.registry import all_connectors
from app.models import User

_STATIC = [
    ConnectorStatus(
        key="manual_import",
        display_name="Manual import",
        state=ConnectorState.available,
        message="Upload TXT, SRT, VTT or JSON transcripts, or paste text.",
        supports_live=False,
        supports_transcript_import=True,
    ),
    ConnectorStatus(
        key="replay",
        display_name="Replay (demo)",
        state=ConnectorState.demo,
        message="Replays an imported transcript incrementally. This is a demo, not a live meeting connection.",
        supports_live=True,
        supports_transcript_import=True,
    ),
]

_CONNECTED = {DisplayStatus.connected, DisplayStatus.connected_post_meeting_only}


def list_connector_statuses(db: Session, user: User) -> list[ConnectorStatus]:
    out = list(_STATIC)
    for connector in all_connectors():
        v = view(db, user, connector)
        live = next(c for c in v.capabilities if c.capability == Capability.live_transcript)
        post = next(c for c in v.capabilities if c.capability == Capability.post_meeting_transcript)
        if v.status in _CONNECTED:
            state, msg = (
                ConnectorState.available,
                ("Connected" + (" (SANDBOX — development only)" if v.sandbox else "") + ". " + post.message),
            )
        else:
            state, msg = (
                ConnectorState.not_configured,
                (
                    "Integration not configured. Import the exported transcript file instead."
                    if v.status == DisplayStatus.not_configured
                    else f"{connector.display_name} is not connected ({v.status.value}). Import the transcript file or "
                    "connect it in Integrations."
                ),
            )
        out.append(
            ConnectorStatus(
                key=connector.provider.value,
                display_name=connector.display_name,
                state=state,
                message=msg,
                supports_live=live.status == CapabilityStatus.available,
                supports_transcript_import=True,
            )
        )
    return out
