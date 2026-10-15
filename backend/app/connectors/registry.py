from __future__ import annotations

from app.connectors.base import ConnectorState, ConnectorStatus

# Workstream 1: only manual import and the replay demo are functional.
# Real platforms report "not_configured" until Workstream 2 implements them;
# the UI must never show them as connected.
_STATUSES = [
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
    ConnectorStatus(
        key="teams",
        display_name="Microsoft Teams",
        state=ConnectorState.not_configured,
        message="Integration not configured. Export the meeting transcript (VTT) and import it instead.",
        supports_live=False,
        supports_transcript_import=True,
    ),
    ConnectorStatus(
        key="zoom",
        display_name="Zoom",
        state=ConnectorState.not_configured,
        message="Integration not configured. Download the cloud recording transcript (VTT) and import it.",
        supports_live=False,
        supports_transcript_import=True,
    ),
    ConnectorStatus(
        key="google_meet",
        display_name="Google Meet",
        state=ConnectorState.not_configured,
        message="Integration not configured. Import the transcript exported from Google Docs as TXT.",
        supports_live=False,
        supports_transcript_import=True,
    ),
]


def list_connector_statuses() -> list[ConnectorStatus]:
    return list(_STATUSES)
