"""Zoom webhook + RTMS live ingestion (MOCKED: signed webhook built locally,
fake SDK client substituted via ``connection_manager.rtms_client_factory``).
Not verified against a live RTMS-enabled Zoom account."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.integrations.orchestration import connection_manager
from app.models import Job, LiveSession, ProviderEvent
from app.models.enums import JobKind
from tests.conftest import ApiClient, connect_platform, create_meeting, run_jobs
from tests.fakes.fake_providers import ZOOM_MEETING_ID, ZOOM_UUID

SECRET = "zoom-webhook-secret"


def signed(payload: dict[str, Any], *, ts: int | None = None, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    ts = ts if ts is not None else int(time.time() * 1000)
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{raw.decode()}".encode(), hashlib.sha256).hexdigest()
    return raw, {"x-zm-request-timestamp": str(ts), "x-zm-signature": sig, "content-type": "application/json"}


def post_webhook(payload: dict[str, Any], **kw: Any) -> Any:
    raw, headers = signed(payload, **kw)
    return ApiClient(None).client.post("/api/v1/integrations/zoom/webhook", content=raw, headers=headers)


class FakeRtmsClient:
    """Mimics the documented callback shapes of the official SDK: transcript
    callbacks receive (data: bytes, size, timestamp, metadata.userId/userName)."""

    instances: list[FakeRtmsClient] = []
    script: list[tuple[str, str, str, int]] = []

    def __init__(self) -> None:
        self.on_tx = None
        self.on_lv = None
        self.join_kwargs: dict[str, Any] = {}
        self.sent = False
        FakeRtmsClient.instances.append(self)

    def on_transcript_data(self, cb: Any) -> None:
        self.on_tx = cb

    def on_leave(self, cb: Any) -> None:
        self.on_lv = cb

    def join(self, **kwargs: Any) -> bool:
        self.join_kwargs = kwargs
        return True

    def poll(self) -> None:
        if self.sent:
            return
        self.sent = True
        for user_id, name, text, ts in self.script:
            meta = SimpleNamespace(userId=user_id, userName=name)
            self.on_tx(text.encode(), len(text), ts, meta)  # type: ignore[misc]
        self.on_lv(0)  # type: ignore[misc]  # Zoom ends the stream

    def leave(self) -> None:
        pass


@pytest.fixture
def zoom_linked(pm, fake, monkeypatch):
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    r = pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    assert r.status_code == 201
    FakeRtmsClient.instances = []
    monkeypatch.setattr(connection_manager, "rtms_client_factory", FakeRtmsClient)
    return meeting


def rtms_started(stream: str = "stream-abc") -> dict[str, Any]:
    return {
        "event": "meeting.rtms_started",
        "event_ts": int(time.time() * 1000),
        "payload": {"meeting_uuid": ZOOM_UUID, "rtms_stream_id": stream, "server_urls": "wss://rtms.example/ws"},
    }


def wait_for(predicate: Any, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def test_url_validation_challenge(fake):
    r = post_webhook(
        {"event": "endpoint.url_validation", "payload": {"plainToken": "qgg8vlvZRS6UYooatFL8Aw"}, "event_ts": 1}
    )
    assert r.status_code == 200
    expected = hmac.new(SECRET.encode(), b"qgg8vlvZRS6UYooatFL8Aw", hashlib.sha256).hexdigest()
    assert r.json() == {"plainToken": "qgg8vlvZRS6UYooatFL8Aw", "encryptedToken": expected}


def test_webhook_signature_and_replay_protection(fake, zoom_linked, db):
    bad_sig = post_webhook(rtms_started(), secret="wrong-secret")
    assert bad_sig.status_code == 401 and bad_sig.json()["error"]["code"] == "integration_invalid_signature"
    stale = post_webhook(rtms_started(), ts=int(time.time() * 1000) - 10 * 60 * 1000)
    assert stale.status_code == 401
    unsigned = ApiClient(None).client.post("/api/v1/integrations/zoom/webhook", json=rtms_started())
    assert unsigned.status_code == 401
    big = ApiClient(None).client.post(
        "/api/v1/integrations/zoom/webhook", content=b"x" * 70_000, headers={"content-type": "application/json"}
    )
    assert big.status_code == 413
    # Not armed yet → event recorded but ignored.
    payload = rtms_started()
    first = post_webhook(payload)
    assert first.status_code == 200 and first.json()["status"] == "ignored"
    replay = post_webhook(payload)
    assert replay.json()["status"] == "duplicate"
    assert db.scalar(select(ProviderEvent).where(ProviderEvent.event_type == "meeting.rtms_started")) is not None


def test_events_for_unlinked_meetings_are_ignored(fake, zoom_linked):
    payload = rtms_started()
    payload["payload"]["meeting_uuid"] = "someone-elses-meeting=="
    r = post_webhook(payload)
    assert r.json()["status"] == "ignored" and "No meeting" in r.json()["detail"]


def test_live_rtms_ingestion_end_to_end(pm, fake, zoom_linked, db):
    meeting = zoom_linked
    FakeRtmsClient.script = [
        ("16778240", "Sarah Johnson", "Thanks everyone, let's confirm the release plan.", 1_760_000_000_000),
        ("16779264", "Kenji Watanabe", "We agreed to move go-live to November 15.", 1_760_000_004_000),
        ("16778240", "Sarah Johnson", "Kenji will prepare the migration plan by next Friday.", 1_760_000_009_500),
    ]
    live = pm.post(f"/meetings/{meeting['id']}/external-source/live/start")
    assert live.status_code == 202 and live.json()["status"] == "waiting" and live.json()["is_demo"] is False
    r = post_webhook(rtms_started())
    assert r.json()["status"] == "processed"
    job = db.scalar(select(Job).where(Job.kind == JobKind.realtime_ingest))
    assert job is not None and job.params["meeting_uuid"] == ZOOM_UUID
    run_jobs()
    wait_for(lambda: pm.get(f"/meetings/{meeting['id']}/live").json()["session"]["status"] == "completed")
    feed = pm.get(f"/meetings/{meeting['id']}/live").json()
    client = FakeRtmsClient.instances[0]
    assert client.join_kwargs["rtms_stream_id"] == "stream-abc" and client.join_kwargs["client"] == "zoom-client"
    entries = feed["entries"]
    assert [e["speaker_label"] for e in entries] == ["Sarah Johnson", "Kenji Watanabe", "Sarah Johnson"]
    assert [e["start_ms"] for e in entries] == [0, 4000, 9500]
    assert all(
        e["source_metadata"]["connector"] == "zoom" and e["source_metadata"]["is_demo"] is False for e in entries
    )
    assert entries[0]["source_metadata"]["speaker_id"] == "16778240"
    assert all(e["translation"] and e["translation"]["status"] == "done" for e in entries)
    assert feed["session"]["entries_emitted"] == 3
    # Memo generation over live-ingested segments.
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    assert pm.get(f"/meetings/{meeting['id']}/memo").json()["status"] == "draft"


def test_live_stop_and_rtms_stopped(pm, fake, zoom_linked, db):
    meeting = zoom_linked
    pm.post(f"/meetings/{meeting['id']}/external-source/live/start")
    assert pm.post(f"/meetings/{meeting['id']}/external-source/live/stop").json() == {"stopped": 1}
    r = post_webhook(rtms_started("stream-2"))
    assert r.json()["status"] == "ignored"  # disarmed: no ingestion starts
    pm.post(f"/meetings/{meeting['id']}/external-source/live/start")
    r = post_webhook(
        {"event": "meeting.rtms_stopped", "event_ts": 5, "payload": {"meeting_uuid": ZOOM_UUID, "rtms_stream_id": "s"}}
    )
    assert r.json()["status"] == "processed"
    db.expire_all()
    assert all(s.status.value in ("stopped", "completed") for s in db.scalars(select(LiveSession)))


def test_transcript_completed_webhook_queues_retrieval(pm, fake, zoom_linked, db):
    r = post_webhook(
        {
            "event": "recording.transcript_completed",
            "event_ts": 7,
            "payload": {"object": {"id": int(ZOOM_MEETING_ID), "uuid": ZOOM_UUID}},
        }
    )
    assert r.json()["status"] == "processed"
    run_jobs()
    assert pm.get(f"/meetings/{zoom_linked['id']}/external-source").json()["transcript_status"] == "imported"


def test_live_requires_capability(pm, fake, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "zoom_rtms_enabled", False)
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    r = pm.post(f"/meetings/{meeting['id']}/external-source/live/start")
    assert r.status_code == 409 and "RTMS" in r.json()["error"]["message"]


def test_teams_live_is_never_offered(pm, fake):
    from tests.fakes.fake_providers import TEAMS_JOIN_URL

    connect_platform(pm, fake, "teams")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    r = pm.post(f"/meetings/{meeting['id']}/external-source/live/start")
    assert r.status_code == 409 and r.json()["error"]["code"] == "integration_unsupported"
