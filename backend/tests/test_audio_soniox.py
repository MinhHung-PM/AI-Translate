"""Soniox as the live speech provider (HTTP mocked per the contract in app/audio/soniox.py)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.audio import stt as stt_module
from app.models import UsageRecord
from tests.conftest import create_meeting, project_id
from tests.test_audio_capture import start

SONIOX_KEY = "soniox-test-key-0123456789abcdef"


class FakeSoniox:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.status = 201

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.soniox.com"
        assert request.url.path == "/v1/auth/temporary-api-key"
        assert request.headers["authorization"] == f"Bearer {SONIOX_KEY}"
        self.bodies.append(json.loads(request.content))
        if self.status != 201:
            return httpx.Response(self.status, json={"message": f"nope {SONIOX_KEY}"})
        return httpx.Response(201, json={"api_key": "snx_temp_abc", "expires_at": "2026-10-19T07:00:00Z"})


@pytest.fixture
def soniox(pm):
    fake = FakeSoniox()
    stt_module.set_transport_override(httpx.MockTransport(fake.handle))
    r = pm.put(
        "/providers/configs",
        json={
            "provider": "soniox",
            "model": "stt-rt-v5",
            "api_key": SONIOX_KEY,
            "remember": True,
            "make_default": False,
        },
    )
    assert r.status_code == 200, r.text
    yield fake
    stt_module.set_transport_override(None)


def test_soniox_is_speech_only_and_never_default(pm, soniox):
    configs = pm.get("/providers/configs").json()
    cfg = next(c for c in configs if c["provider"] == "soniox")
    assert cfg["is_default"] is False
    assert pm.post(f"/providers/configs/{cfg['id']}/default").status_code == 422
    r = pm.put(
        "/providers/configs",
        json={"provider": "soniox", "model": "stt-rt-v5", "remember": True, "make_default": True},
    )
    assert r.status_code == 422
    t = pm.post(f"/providers/configs/{cfg['id']}/test").json()
    assert t["ok"] is True and SONIOX_KEY not in json.dumps(t)
    assert soniox.bodies[-1]["usage_type"] == "transcribe_websocket" and soniox.bodies[-1]["single_use"] is True


def test_soniox_session_needs_a_key_and_a_streaming_mode(pm):
    meeting = create_meeting(pm)
    base = {
        "sources": [{"id": "mic", "kind": "microphone", "label": "Tôi", "single_speaker": True}],
        "consent_confirmed": True,
        "stt_provider": "soniox",
    }
    r = pm.post(f"/meetings/{meeting['id']}/audio-sessions", json={**base, "mode": "interpret"})
    assert r.status_code in (400, 409, 422, 424) and "Soniox" in r.text
    r = pm.post(f"/meetings/{meeting['id']}/audio-sessions", json={**base, "mode": "chunked"})
    assert r.status_code == 422


def test_soniox_interpret_token_config_and_storage(pm, db, soniox, caplog):
    pid = project_id(pm)
    pm.post(
        f"/projects/{pid}/glossary",
        json={
            "source_term": "前提",
            "preferred_translation": "giả định (assumption)",
            "source_language": "ja",
            "target_language": "vi",
        },
    )
    meeting = create_meeting(pm, source_language="ja", target_language="vi", participants=[{"display_name": "Tanaka"}])
    out = start(pm, meeting["id"], mode="interpret", stt_provider="soniox")
    cfg = out["session"]["capture_config"]
    assert cfg["stt_provider"] == "soniox" and cfg["mode"] == "interpret" and out["session"]["is_demo"] is False
    sid = out["session"]["id"]

    r = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "meeting"})
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["kind"] == "soniox" and tok["client_secret"] == "snx_temp_abc"
    assert tok["calls_url"] == "wss://stt-rt.soniox.com/transcribe-websocket"
    assert tok["expires_at"] > 0 and tok["target_language"] == "vi"
    sc = tok["session_config"]
    assert "api_key" not in sc  # the browser adds the temporary key itself
    assert sc["model"] == "stt-rt-v5" and sc["audio_format"] == "pcm_s16le" and sc["sample_rate"] == 16000
    assert sc["translation"] == {"type": "one_way", "target_language": "vi"}
    assert sc["enable_speaker_diarization"] is True and sc["enable_language_identification"] is True
    assert "language_hints" not in sc  # auto language detection
    assert "Tanaka" in sc["context"]["terms"] and "前提" in sc["context"]["terms"]
    assert {"source": "前提", "target": "giả định (assumption)"} in sc["context"]["translation_terms"]
    assert SONIOX_KEY not in r.text and SONIOX_KEY not in caplog.text
    mic = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"}).json()
    assert mic["session_config"]["enable_speaker_diarization"] is False  # one person on "my microphone"

    seg = {
        "source_id": "meeting",
        "item_id": "sx-1",
        "text": "前提を確認しましょう。",
        "translated_text": "Hãy xác nhận giả định.",
        "offset_ms": 0,
        "duration_ms": 60_000,
        "speaker": "1",
    }
    e = pm.post(f"/audio-sessions/{sid}/segments", json=seg).json()["entries"][0]
    assert e["translation"]["text"] == "Hãy xác nhận giả định." and e["translation"]["status"] == "done"
    assert e["speaker_label"] == "Người 1" and e["source_metadata"]["stt_model"] == "stt-rt-v5+translation"
    rec = db.scalars(select(UsageRecord).where(UsageRecord.provider == "soniox")).one()
    assert rec.model == "stt-rt-v5+translation" and float(rec.estimated_cost_usd) == pytest.approx(0.003)


def test_soniox_captions_use_app_translation_and_errors_are_safe(pm, soniox):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"], mode="streaming", stt_provider="soniox")["session"]["id"]
    tok = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"}).json()
    assert "translation" not in tok["session_config"] and tok["target_language"] is None
    e = pm.post(
        f"/audio-sessions/{sid}/segments",
        json={"source_id": "mic", "item_id": "c1", "text": "Xin chào", "translated_text": "IGNORED", "offset_ms": 0},
    ).json()["entries"][0]
    assert e["translation"]["status"] == "done" and e["translation"]["text"] != "IGNORED"
    assert e["source_metadata"]["stt_model"] == "stt-rt-v5"
    soniox.status = 403
    r = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"})
    assert r.status_code == 502 and "Temporary API keys" in r.text and SONIOX_KEY not in r.text
