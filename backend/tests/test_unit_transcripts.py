from __future__ import annotations

import pytest

from app.core.errors import PayloadTooLarge, ValidationFailed
from app.models.enums import Language, TranscriptFormat
from app.services.transcripts.importer import parse_upload
from app.services.transcripts.normalize import (
    chunk_segments,
    decode_upload,
    detect_language,
    normalize_entries,
    safe_filename,
    split_long_text,
)
from app.services.transcripts.parsers import (
    ParsedEntry,
    TranscriptParseError,
    parse_json,
    parse_plain_text,
    parse_srt,
    parse_vtt,
)
from tests.conftest import SAMPLES


def test_plain_text_speakers_and_timestamps_only_when_present():
    entries = parse_plain_text("[00:01:02] 田中: 確認します。\nNo speaker line here\nhttps://example.com: link")
    assert entries[0].speaker == "田中" and entries[0].start_ms == 62_000
    assert entries[1].speaker is None and entries[1].start_ms is None
    assert entries[2].speaker is None  # URLs are not speakers


def test_srt_parsing():
    entries = parse_srt((SAMPLES / "en_steering_meeting.srt").read_text())
    assert len(entries) == 6
    assert entries[0].speaker == "Sarah Johnson"
    assert (entries[0].start_ms, entries[0].end_ms) == (1000, 6000)


def test_srt_invalid_timing():
    with pytest.raises(TranscriptParseError):
        parse_srt("1\nnot a timing\nHello")


def test_vtt_voice_tags_and_short_timestamps():
    entries = parse_vtt("WEBVTT\n\nNOTE comment\n\n00:01.000 --> 00:02.500\n<v Tanaka>こんにちは</v>")
    assert entries[0].speaker == "Tanaka"
    assert entries[0].start_ms == 1000 and entries[0].end_ms == 2500
    assert entries[0].text == "こんにちは"


def test_vtt_requires_header():
    with pytest.raises(TranscriptParseError):
        parse_vtt("00:01.000 --> 00:02.000\nhello")


def test_json_schema_validation():
    entries = parse_json((SAMPLES / "sample_transcript.json").read_text())
    assert len(entries) == 3
    assert entries[2].speaker is None and entries[2].start_ms is None
    assert entries[0].language == Language.ja
    with pytest.raises(TranscriptParseError):
        parse_json('{"schema_version": "1.0", "entries": [{"text": "x", "unknown": 1}]}')
    with pytest.raises(TranscriptParseError):
        parse_json('{"schema_version": "1.0", "entries": [{"text": "x", "start_ms": 5, "end_ms": 1}]}')
    with pytest.raises(TranscriptParseError):
        parse_json("{not json")


def test_language_detection():
    assert detect_language("来週の会議") == Language.ja
    assert detect_language("Chúng ta thống nhất deploy") == Language.vi
    assert detect_language("We agreed to deploy") == Language.en
    assert detect_language("123 456") is None


def test_decode_shift_jis_and_reject_binary():
    text, enc = decode_upload("田中: 在庫引当の仕様を確認します。よろしくお願いします。".encode("shift_jis"))
    assert "在庫引当" in text and enc.lower().replace("-", "_") in {"shift_jis", "cp932", "shift_jis_2004"}
    with pytest.raises(TranscriptParseError):
        decode_upload(b"\x00\x01\x02binary")
    with pytest.raises(TranscriptParseError):
        decode_upload(b"   ")


def test_normalization_splits_long_entries_without_inventing_timestamps():
    long = "これは長い文です。" * 30
    out = normalize_entries(
        [ParsedEntry(text=long, speaker="A", start_ms=0, end_ms=9000)], max_entry_chars=100, max_entries=100
    )
    assert len(out) > 1
    assert out[0].start_ms == 0 and out[0].end_ms is None
    assert out[-1].end_ms == 9000 and out[-1].start_ms is None
    assert all(e.speaker == "A" for e in out)
    assert all(len(e.text) <= 100 for e in out)
    assert out[0].metadata["parts"] == len(out)


def test_normalization_strips_control_chars_and_limits_entries():
    out = normalize_entries([ParsedEntry(text="a\u202eb\x07c")], max_entry_chars=100, max_entries=10)
    assert out[0].text == "abc"
    with pytest.raises(TranscriptParseError):
        normalize_entries([ParsedEntry(text="x")] * 11, max_entry_chars=100, max_entries=10)


def test_split_long_text_hard_split():
    assert all(len(p) <= 10 for p in split_long_text("a" * 35, 10))


def test_chunking_preserves_order_and_bounds():
    class Seg:
        def __init__(self, ref: int, text: str) -> None:
            self.ref, self.text = ref, text

    items = [Seg(i, "x" * 30) for i in range(10)]
    chunks = chunk_segments(items, max_entries=3, max_chars=70)
    assert [s.ref for c in chunks for s in c] == list(range(10))
    assert all(len(c) <= 3 and sum(len(s.text) for s in c) <= 70 for c in chunks)


def test_safe_filename_strips_paths():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\x\\会議.vtt") == "会議.vtt"
    assert safe_filename("a<script>.txt") == "a_script_.txt"


def test_parse_upload_rejects_bad_extension_and_size(monkeypatch):
    with pytest.raises(ValidationFailed):
        parse_upload(data=b"MZ...", text=None, filename="evil.exe", declared_format=None)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    with pytest.raises(PayloadTooLarge):
        parse_upload(data=b"x" * 11, text=None, filename="a.txt", declared_format=None)


def test_parse_upload_mismatched_declared_format():
    with pytest.raises(ValidationFailed):
        parse_upload(data=b"WEBVTT\n\n", text=None, filename="a.vtt", declared_format=TranscriptFormat.srt)
