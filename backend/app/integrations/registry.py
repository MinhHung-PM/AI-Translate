from __future__ import annotations

from functools import lru_cache

from app.core.errors import NotFound
from app.integrations.base import Connector
from app.integrations.google_meet.connector import GoogleMeetConnector
from app.integrations.teams.connector import TeamsConnector
from app.integrations.zoom.connector import ZoomConnector
from app.models.enums import PlatformProvider


@lru_cache
def _connectors() -> dict[PlatformProvider, Connector]:
    return {c.provider: c for c in (TeamsConnector(), ZoomConnector(), GoogleMeetConnector())}


def all_connectors() -> list[Connector]:
    return list(_connectors().values())


def get_connector(provider: str) -> Connector:
    try:
        return _connectors()[PlatformProvider(provider)]
    except (ValueError, KeyError):
        raise NotFound("Unknown platform") from None
