"""Live audio capture: chunk → speech-to-text with diarization → speaker
profiles → transcript → translation. OpenAI is MOCKED at the HTTP layer with
the documented diarized_json contract; no real audio service is called."""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.audio import stt as stt_module
from app.audio.wav import parse_wav
from app.core.errors import ValidationFailed
from app.models import AudioSpeakerProfile, UsageRecord
from tests.conftest import create_meeting

OPENAI_KEY = "sk-test-AUDIO-0123456789abcdef"


def make_wav(seconds: float, rate: int = 16000, freq: float = 220.0, channels: int = 1, width: int = 2) -> bytes:
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            frames = b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) * channels for i in range(n)
            )
        else:
            frames = b"\x80" * n * channels
        w.writeframes(frames)
    return buf.getvalue()


def start(client: Any, meeting_id: str, **overrides: Any) -> dict[str, Any]:
    body = {
        "sources": [
            {"id": "meeting", "kind": "system", "label": "Âm thanh cuộc họp"},
            {"id": "mic", "kind": "microphone", "label": "Tôi", "single_speaker": True},
        ],
        "translate": True,
        "consent_confirmed": True,
        **overrides,
    }
    r = client.post(f"/meetings/{meeting_id}/audio-sessions", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def chunk(client: Any, sid: str, source: str, seq: int, wav: bytes, offset_ms: int = 0) -> Any:
    return client.post(
        f"/audio-sessions/{sid}/chunks",
        data={"source_id": source, "chunk_seq": str(seq), "offset_ms": str(offset_ms)},
        files={"file": ("c.wav", wav, "audio/wav")},
    )


# ---- MOCK speech-to-text (no OpenAI configured) ---------------------------------


def test_mock_capture_diarizes_translates_and_keeps_speakers(pm, db):
    meeting = create_meeting(pm)
    out = start(pm, meeting["id"])
    sid = out["session"]["id"]
    assert out["session"]["is_demo"] is True and out["session"]["connector"] == "audio_capture"
    assert "MOCK" in out["session"]["status_message"]

    r1 = chunk(pm, sid, "meeting", 0, make_wav(3.0))
    assert r1.status_code == 200, r1.text
    e1 = r1.json()["entries"]
    assert len(e1) == 1 and e1[0]["speaker_label"] == "Người 1"
    assert e1[0]["original_text"].startswith("[MOCK STT]")
    assert e1[0]["translation"]["status"] == "done"
    meta = e1[0]["source_metadata"]
    assert meta["audio_source_id"] == "meeting" and meta["audio_speaker_key"] == "S1" and meta["is_demo"] is True

    # Same speaker comes back in the next chunk thanks to the stored voice reference.
    r2 = chunk(pm, sid, "meeting", 1, make_wav(2.5), offset_ms=4000)
    e2 = r2.json()["entries"]
    assert e2[0]["speaker_label"] == "Người 1" and e2[0]["start_ms"] == 4000

    # Microphone source is single-speaker: label is the source label, no diarization.
    r3 = chunk(pm, sid, "mic", 0, make_wav(1.0))
    assert r3.json()["entries"][0]["speaker_label"] == "Tôi"

    # Idempotent retry of the same chunk: no duplicate entry, no second STT call.
    usage_before = len(db.scalars(select(UsageRecord).where(UsageRecord.operation == "speech_to_text")).all())
    again = chunk(pm, sid, "meeting", 0, make_wav(3.0))
    assert again.json()["duplicate"] is True and len(again.json()["entries"]) == 1
    db.expire_all()
    assert len(db.scalars(select(UsageRecord).where(UsageRecord.operation == "speech_to_text")).all()) == usage_before

    # Rename a speaker → existing entries are relabelled.
    rn = pm.patch(f"/audio-sessions/{sid}/speakers/S1", json={"display_name": "Tanaka-san"})
    assert rn.status_code == 200 and rn.json()["display_name"] == "Tanaka-san"
    feed = pm.get(f"/meetings/{meeting['id']}/live").json()
    labels = [e["speaker_label"] for e in feed["entries"]]
    assert labels == ["Tanaka-san", "Tanaka-san", "Tôi"]
    assert feed["session"]["entries_emitted"] == 3

    # Stop: voice references are deleted.
    stopped = pm.post(f"/audio-sessions/{sid}/stop").json()
    assert stopped["session"]["status"] == "stopped"
    assert all(not s["has_voice_reference"] for s in stopped["speakers"])
    db.expire_all()
    assert all(p.encrypted_reference is None for p in db.scalars(select(AudioSpeakerProfile)))
    assert chunk(pm, sid, "meeting", 2, make_wav(1.0)).status_code == 409


def test_short_utterance_from_unknown_speaker_stays_unattributed(pm):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    e = chunk(pm, sid, "meeting", 0, make_wav(1.2)).json()["entries"][0]
    assert e["speaker_label"] is None  # < 2 s: not enough audio to identify → never invented


def test_capture_requires_consent_and_valid_sources(pm):
    meeting = create_meeting(pm)
    r = pm.post(
        f"/meetings/{meeting['id']}/audio-sessions",
        json={"sources": [{"id": "a", "kind": "system", "label": "x"}], "consent_confirmed": False},
    )
    assert r.status_code == 422
    r = pm.post(
        f"/meetings/{meeting['id']}/audio-sessions",
        json={"sources": [{"id": "a", "kind": "system", "label": "x"}] * 2, "consent_confirmed": True},
    )
    assert r.status_code == 422
    r = pm.post(
        f"/meetings/{meeting['id']}/audio-sessions",
        json={"sources": [{"id": "A B", "kind": "system", "label": "x"}], "consent_confirmed": True},
    )
    assert r.status_code == 422
    start(pm, meeting["id"])
    again = pm.post(
        f"/meetings/{meeting['id']}/audio-sessions",
        json={"sources": [{"id": "a", "kind": "system", "label": "x"}], "consent_confirmed": True},
    )
    assert again.status_code == 409  # one live session per meeting


def test_invalid_audio_is_rejected(pm, monkeypatch):
    from app.core.config import get_settings

    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    assert chunk(pm, sid, "meeting", 0, b"not a wav").status_code == 422
    assert chunk(pm, sid, "meeting", 1, make_wav(1.0, channels=2)).status_code == 422
    assert chunk(pm, sid, "meeting", 2, make_wav(1.0, width=1)).status_code == 422
    assert chunk(pm, sid, "meeting", 3, make_wav(0.05)).status_code == 422
    assert chunk(pm, sid, "meeting", 4, make_wav(31.0, rate=8000)).status_code == 422
    assert chunk(pm, sid, "unknown", 5, make_wav(1.0)).status_code == 422
    monkeypatch.setattr(get_settings(), "audio_chunk_max_bytes", 1000)
    assert chunk(pm, sid, "meeting", 6, make_wav(1.0)).status_code == 413


def test_only_the_capturing_user_can_send_audio(pm, member, outsider):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    assert chunk(outsider, sid, "meeting", 0, make_wav(1.0)).status_code == 404
    assert chunk(member, sid, "meeting", 0, make_wav(1.0)).status_code in (403, 404)
    assert outsider.get(f"/audio-sessions/{sid}").status_code == 404
    assert outsider.post(f"/audio-sessions/{sid}/stop").status_code == 404
    assert outsider.patch(f"/audio-sessions/{sid}/speakers/S1", json={"display_name": "x"}).status_code == 404


def test_no_mock_and_no_openai_means_not_configured(pm, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "enable_mock_provider", False)
    meeting = create_meeting(pm)
    r = pm.post(
        f"/meetings/{meeting['id']}/audio-sessions",
        json={"sources": [{"id": "a", "kind": "system", "label": "x"}], "consent_confirmed": True},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "provider_not_configured"


def test_idle_sessions_are_stopped_and_references_purged(pm, db):
    from datetime import timedelta

    from app.db.base import utcnow
    from app.models import LiveSession
    from app.services.audio_capture import purge_idle_sessions

    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    chunk(pm, sid, "meeting", 0, make_wav(3.0))
    live = db.get(LiveSession, sid)
    live.last_event_at = utcnow() - timedelta(hours=2)
    db.commit()
    assert purge_idle_sessions(db) == 1
    db.commit()
    db.expire_all()
    assert db.get(LiveSession, sid).status.value == "interrupted"
    assert all(p.encrypted_reference is None for p in db.scalars(select(AudioSpeakerProfile)))


# ---- OpenAI speech-to-text (HTTP mocked with the documented contract) ----------


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.text_model_available = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
        body = request.content
        fields: dict[str, list[str]] = {}
        ctype = request.headers["content-type"]
        boundary = ctype.split("boundary=")[1].encode()
        for part in body.split(b"--" + boundary):
            if b'name="' not in part:
                continue
            header, _, value = part.partition(b"\r\n\r\n")
            name = header.split(b'name="')[1].split(b'"')[0].decode()
            fields.setdefault(name, []).append(value.rstrip(b"\r\n").decode("latin-1"))
        self.requests.append(fields)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": f"denied {OPENAI_KEY}"}})
        model = fields["model"][0]
        if model == "gpt-transcribe":
            if not self.text_model_available:
                return httpx.Response(404, json={"error": {"message": "The model `gpt-transcribe` does not exist"}})
            return httpx.Response(
                200, json={"text": "Xin chào, tôi tên là Hùng.", "languages": [{"code": "vi"}], "usage": {}}
            )
        if model == "gpt-4o-transcribe":
            return httpx.Response(200, json={"text": "Xin chào, tôi tên là Hùng."})
        known = fields.get("known_speaker_names[]", [])
        if not known:
            segs = [
                {
                    "type": "transcript.text.segment",
                    "id": "seg_1",
                    "start": 0.0,
                    "end": 2.6,
                    "text": "本日は在庫引当の仕様を確認します。",
                    "speaker": "A",
                },
                {
                    "type": "transcript.text.segment",
                    "id": "seg_2",
                    "start": 2.7,
                    "end": 3.4,
                    "text": "はい。",
                    "speaker": "B",
                },
            ]
        else:
            segs = [
                {
                    "type": "transcript.text.segment",
                    "id": "seg_1",
                    "start": 0.0,
                    "end": 2.0,
                    "text": "来週金曜日までに設計書を更新します。",
                    "speaker": known[0],
                },
                {
                    "type": "transcript.text.segment",
                    "id": "seg_2",
                    "start": 2.1,
                    "end": 4.5,
                    "text": "Thanks, let's confirm the release plan.",
                    "speaker": "A",
                },
            ]
        return httpx.Response(
            200,
            json={
                "task": "transcribe",
                "duration": 4.5,
                "text": "",
                "segments": segs,
                "usage": {"type": "duration", "seconds": 5},
            },
        )


@pytest.fixture
def openai_stt(pm):
    fake = FakeOpenAI()
    stt_module.set_transport_override(httpx.MockTransport(fake.handle))
    r = pm.put(
        "/providers/configs",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": OPENAI_KEY,
            "remember": True,
            "make_default": False,
        },
    )
    assert r.status_code == 200, r.text
    yield fake
    stt_module.set_transport_override(None)


def test_openai_diarization_contract_and_speaker_references(pm, db, openai_stt, caplog):
    meeting = create_meeting(pm, source_language="ja")
    out = start(pm, meeting["id"], languages=["ja"])
    sid = out["session"]["id"]
    assert out["session"]["is_demo"] is False and out["session"]["provider_session_id"] == "gpt-4o-transcribe-diarize"

    first = chunk(pm, sid, "meeting", 0, make_wav(3.5)).json()["entries"]
    req = openai_stt.requests[0]
    assert req["model"] == ["gpt-4o-transcribe-diarize"] and req["response_format"] == ["diarized_json"]
    assert req["language"] == ["ja"] and "known_speaker_names[]" not in req
    # A (2.6 s) gets a profile; B (0.7 s) is too short to identify → unattributed.
    assert [(e["speaker_label"], e["original_text"]) for e in first] == [
        ("Người 1", "本日は在庫引当の仕様を確認します。"),
        (None, "はい。"),
    ]
    assert first[0]["translation"]["status"] == "done"  # translated with the user's default provider (mock)

    second = chunk(pm, sid, "meeting", 1, make_wav(4.5), offset_ms=5000).json()["entries"]
    req2 = openai_stt.requests[1]
    assert req2["known_speaker_names[]"] == ["S1"]
    assert req2["known_speaker_references[]"][0].startswith("data:audio/wav;base64,")
    assert [e["speaker_label"] for e in second] == ["Người 1", "Người 2"]
    assert second[1]["start_ms"] == 7100

    usage = db.scalars(select(UsageRecord).where(UsageRecord.operation == "speech_to_text")).all()
    assert len(usage) == 2 and all(u.provider == "openai" and u.audio_seconds for u in usage)
    assert all(u.estimated_cost_usd is not None and u.estimated_cost_usd > 0 for u in usage)
    assert OPENAI_KEY not in caplog.text


def test_openai_errors_are_safe_and_recorded(pm, db, openai_stt):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    openai_stt.status = 401
    r = chunk(pm, sid, "meeting", 0, make_wav(1.0))
    assert r.status_code == 502 and r.json()["error"]["code"] == "speech_to_text_failed"
    assert OPENAI_KEY not in r.text
    assert "rejected" in r.json()["error"]["message"]
    openai_stt.status = 429
    r = chunk(pm, sid, "meeting", 1, make_wav(1.0))
    assert r.json()["error"]["details"]["retryable"] is True
    failed = db.scalars(select(UsageRecord).where(UsageRecord.success.is_(False))).all()
    assert len(failed) == 2
    s = pm.get(f"/audio-sessions/{sid}").json()["session"]
    assert "Speech-to-text error" in s["status_message"] and OPENAI_KEY not in json.dumps(s)


def test_microphone_uses_language_constrained_text_model(pm, openai_stt):
    meeting = create_meeting(pm, source_language="vi", target_language="ja", participants=[{"display_name": "Tanaka"}])
    out = start(pm, meeting["id"])
    assert out["session"]["capture_config"]["languages"] == ["vi", "ja"]
    entries = chunk(pm, out["session"]["id"], "mic", 0, make_wav(2.0)).json()["entries"]
    req = openai_stt.requests[0]
    assert req["model"] == ["gpt-transcribe"] and req["response_format"] == ["json"]
    assert req["languages[]"] == ["vi", "ja"]  # recognition constrained to the meeting languages
    assert "Tanaka" in req["keywords[]"]
    assert "known_speaker_names[]" not in req and "language" not in req
    assert entries[0]["speaker_label"] == "Tôi" and entries[0]["source_language"] == "vi"
    assert entries[0]["source_metadata"]["stt_model"] == "gpt-transcribe"


def test_text_model_falls_back_when_unavailable(pm, openai_stt):
    openai_stt.text_model_available = False
    meeting = create_meeting(pm, participants=[{"display_name": "Tanaka"}])
    sid = start(pm, meeting["id"], languages=["vi"])["session"]["id"]
    e = chunk(pm, sid, "mic", 0, make_wav(2.0)).json()["entries"]
    assert [r["model"] for r in openai_stt.requests] == [["gpt-transcribe"], ["gpt-4o-transcribe"]]
    fallback = openai_stt.requests[1]
    assert fallback["language"] == ["vi"] and "Tanaka" in fallback["prompt"][0]
    assert e[0]["source_metadata"]["stt_model"] == "gpt-4o-transcribe"


def test_near_silence_is_not_sent_or_billed(pm, db, openai_stt):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    quiet = make_wav(2.0, freq=220.0)
    # Same WAV container, amplitude scaled far below speech level.
    import array

    header, frames = quiet[:44], array.array("h", quiet[44:])
    frames = array.array("h", (x // 200 for x in frames))
    r = chunk(pm, sid, "meeting", 0, header + frames.tobytes())
    assert r.status_code == 200 and r.json()["entries"] == []
    assert openai_stt.requests == []
    assert db.scalars(select(UsageRecord).where(UsageRecord.operation == "speech_to_text")).all() == []


# ---- unit ----------------------------------------------------------------------


def test_wav_parsing_and_slicing():
    audio = parse_wav(make_wav(2.0, rate=8000), max_seconds=30)
    assert audio.sample_rate == 8000 and abs(audio.duration_s - 2.0) < 0.01
    assert abs(audio.slice(0.5, 1.5).duration_s - 1.0) < 0.01
    assert parse_wav(audio.to_wav(), max_seconds=30).frames == audio.frames
    with pytest.raises(ValidationFailed):
        parse_wav(make_wav(2.0, rate=96000), max_seconds=30)


# ---- streaming captions (OpenAI Realtime; HTTP mocked) -------------------------


class FakeRealtime:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.live_model_available = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/realtime/client_secrets"
        assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
        body = json.loads(request.content)
        self.bodies.append(body)
        model = body["session"]["audio"]["input"]["transcription"]["model"]
        if model == "gpt-live-transcribe" and not self.live_model_available:
            return httpx.Response(400, json={"error": {"message": "Invalid model: gpt-live-transcribe"}})
        return httpx.Response(200, json={"value": "ek_test_123", "expires_at": 1999999999, "session": body["session"]})


@pytest.fixture
def realtime(pm):
    fake = FakeRealtime()
    stt_module.set_transport_override(httpx.MockTransport(fake.handle))
    r = pm.put(
        "/providers/configs",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": OPENAI_KEY,
            "remember": True,
            "make_default": False,
        },
    )
    assert r.status_code == 200, r.text
    yield fake
    stt_module.set_transport_override(None)


def test_streaming_token_is_ephemeral_and_configured(pm, realtime, caplog):
    meeting = create_meeting(pm, source_language="vi", target_language="ja", participants=[{"display_name": "Tanaka"}])
    out = start(pm, meeting["id"])
    sid = out["session"]["id"]
    assert out["session"]["capture_config"]["mode"] == "streaming"
    r = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"})
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["client_secret"] == "ek_test_123" and tok["model"] == "gpt-live-transcribe"
    assert tok["calls_url"] == "https://api.openai.com/v1/realtime/calls"
    assert OPENAI_KEY not in r.text and OPENAI_KEY not in caplog.text
    body = realtime.bodies[0]
    assert body["expires_after"] == {"anchor": "created_at", "seconds": 600}
    session = body["session"]
    assert session["type"] == "transcription"
    tr = session["audio"]["input"]["transcription"]
    assert tr["languages"] == ["vi", "ja"] and "Tanaka" in tr["keywords"]
    assert session["audio"]["input"]["noise_reduction"] == {"type": "near_field"}
    assert session["audio"]["input"]["turn_detection"]["type"] == "server_vad"
    # Meeting audio uses far-field noise reduction.
    pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "meeting"})
    assert realtime.bodies[1]["session"]["audio"]["input"]["noise_reduction"] == {"type": "far_field"}


def test_streaming_model_fallback(pm, realtime):
    realtime.live_model_available = False
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"], languages=["ja"])["session"]["id"]
    tok = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"}).json()
    assert tok["model"] == "gpt-4o-transcribe"
    tr = realtime.bodies[1]["session"]["audio"]["input"]["transcription"]
    assert tr["model"] == "gpt-4o-transcribe" and tr["language"] == "ja"
    assert "languages" not in tr and "在庫引当" in tr["prompt"]  # glossary terms as a prompt hint


def test_streaming_segments_are_stored_translated_and_idempotent(pm, member, db, realtime):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    seg = {
        "source_id": "mic",
        "item_id": "item_001",
        "text": "Xin chào, tôi tên là Hùng.",
        "offset_ms": 1200,
        "duration_ms": 2300,
        "model": "gpt-live-transcribe",
    }
    r = pm.post(f"/audio-sessions/{sid}/segments", json=seg)
    assert r.status_code == 200, r.text
    e = r.json()["entries"][0]
    assert e["speaker_label"] == "Tôi" and e["start_ms"] == 1200 and e["end_ms"] == 3500
    assert e["translation"]["status"] == "done" and e["source_metadata"]["streaming"] is True
    assert pm.post(f"/audio-sessions/{sid}/segments", json=seg).json()["duplicate"] is True
    # Meeting audio: provider speaker labels map to stable session speakers; none → unattributed.
    a = pm.post(
        f"/audio-sessions/{sid}/segments", json={**seg, "source_id": "meeting", "item_id": "i2", "speaker": "spk_1"}
    ).json()["entries"][0]
    b = pm.post(
        f"/audio-sessions/{sid}/segments", json={**seg, "source_id": "meeting", "item_id": "i3", "speaker": "spk_1"}
    ).json()["entries"][0]
    c = pm.post(f"/audio-sessions/{sid}/segments", json={**seg, "source_id": "meeting", "item_id": "i4"}).json()
    assert a["speaker_label"] == b["speaker_label"] == "Người 1"
    assert c["entries"][0]["speaker_label"] is None
    usage = db.scalars(select(UsageRecord).where(UsageRecord.operation == "speech_to_text")).all()
    assert len(usage) == 4 and all(float(u.audio_seconds) == 2.3 for u in usage)
    # Only the capturing user; invalid input rejected.
    assert member.post(f"/audio-sessions/{sid}/segments", json=seg).status_code in (403, 404)
    assert pm.post(f"/audio-sessions/{sid}/segments", json={**seg, "item_id": "bad id!"}).status_code == 422
    assert pm.post(f"/audio-sessions/{sid}/segments", json={**seg, "text": "x" * 6000}).status_code == 422


def test_mock_sessions_use_chunked_mode_only(pm):
    meeting = create_meeting(pm)
    out = start(pm, meeting["id"])
    assert out["session"]["capture_config"]["mode"] == "chunked"
    sid = out["session"]["id"]
    assert pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"}).status_code == 409
    seg = {"source_id": "mic", "item_id": "x", "text": "hi", "offset_ms": 0}
    assert pm.post(f"/audio-sessions/{sid}/segments", json=seg).status_code == 409


def test_streaming_token_errors_are_safe(pm, realtime, monkeypatch):
    meeting = create_meeting(pm)
    sid = start(pm, meeting["id"])["session"]["id"]
    stt_module.set_transport_override(
        httpx.MockTransport(lambda req: httpx.Response(401, json={"error": {"message": f"bad key {OPENAI_KEY}"}}))
    )
    r = pm.post(f"/audio-sessions/{sid}/realtime-token", json={"source_id": "mic"})
    assert r.status_code == 502 and OPENAI_KEY not in r.text and "rejected" in r.json()["error"]["message"]
