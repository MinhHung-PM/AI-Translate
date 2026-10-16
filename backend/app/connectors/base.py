"""Platform status types for the meeting form. The connector contract and the
canonical event live in ``app.integrations`` (Workstream 2)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel


class ConnectorState(StrEnum):
    available = "available"
    demo = "demo"
    not_configured = "not_configured"


class ConnectorStatus(BaseModel):
    key: str
    display_name: str
    state: ConnectorState
    message: str
    supports_live: bool
    supports_transcript_import: bool


class MeetingConnector(Protocol):
    """Implemented by each connector in Workstream 2."""

    key: str

    def status(self) -> ConnectorStatus: ...

    def start(self, meeting_id: str, options: dict[str, Any]) -> str:
        """Begin receiving events for a meeting; returns a live-session id."""
        ...

    def stop(self, live_session_id: str) -> None: ...
