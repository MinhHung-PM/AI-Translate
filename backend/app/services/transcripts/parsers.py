"""Transcript parsers for plain text, TXT, SRT, WebVTT and JSON.

All parsers return ``ParsedEntry`` objects; ``normalize.py`` then produces
the common transcript schema. Parsers never invent speakers or timestamps:
both are taken only from what the source explicitly contains.

JSON import schema (``schema_version`` "1.0")::

    {
      "schema_version": "1.0",
      "language": "ja",                       // optional, ja|vi|en
      "entries": [
        {"speaker": "Tanaka", "start_ms": 0, "end_ms": 4200,
         "text": "...", "language": "ja", "metadata": {"any": "json"}}
      ]
    }

Only ``text`` is required per entry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.enums import Language, TranscriptFormat


class TranscriptParseError(Exception):
    pass


@dataclass
class ParsedEntry:
    text: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    language: Language | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# "Speaker: text", "[00:01:02] Speaker: text", "田中：..."
_SPEAKER_LINE = re.compile(
    r"^(?:\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]\s*)?"
    r"(?:(?P<speaker>[^:：\[\]\n]{1,40}?)\s*[:：]\s+?)?(?P<text>.+)$"
)


def _ts_to_ms(ts: str) -> int:
    ts = ts.replace(",", ".")
    main, _, frac = ts.partition(".")
    parts = [int(p) for p in main.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    if m >= 60 or s >= 60:
        raise TranscriptParseError(f"Invalid timestamp: {ts}")
    ms = int((frac + "000")[:3]) if frac else 0
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _plausible_speaker(name: str | None, text: str) -> bool:
    if not name:
        return False
    name = name.strip()
    lowered = name.lower()
    if lowered.startswith(("http", "https", "note", "todo")) or text.startswith("//"):
        return False
    # Sentences containing these punctuation marks are prose, not a name.
    return not any(ch in name for ch in "。、.,!?！？「」")


def parse_plain_text(text: str) -> list[ParsedEntry]:
    entries: list[ParsedEntry] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        m = _SPEAKER_LINE.match(line)
        speaker: str | None = None
        start_ms: int | None = None
        body = line
        if m:
            if m.group("ts"):
                start_ms = _ts_to_ms(m.group("ts"))
            sp = m.group("speaker")
            if _plausible_speaker(sp, m.group("text")):
                speaker = sp.strip() if sp else None
                body = m.group("text")
            elif m.group("ts"):
                body = line[line.index("]") + 1 :].strip()
        entries.append(ParsedEntry(text=body, speaker=speaker, start_ms=start_ms, metadata={"line": line_no}))
    return entries


_SRT_TIME = re.compile(r"(?P<a>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(?P<b>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")
_VTT_TIME = re.compile(r"(?P<a>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<b>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})")
_VTT_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+([^>]+)>")
_TAG = re.compile(r"</?[^>]+>")


def _split_speaker(text: str) -> tuple[str | None, str]:
    m = re.match(r"^([^:：\n]{1,40}?)\s*[:：]\s+(.+)$", text, re.S)
    if m and _plausible_speaker(m.group(1), m.group(2)):
        return m.group(1).strip(), m.group(2)
    return None, text


def parse_srt(text: str) -> list[ParsedEntry]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    entries: list[ParsedEntry] = []
    for block_no, block in enumerate(blocks, start=1):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        idx = 0
        if lines[0].strip().isdigit():
            idx = 1
        if idx >= len(lines):
            raise TranscriptParseError(f"SRT block {block_no} is missing a timing line")
        m = _SRT_TIME.search(lines[idx])
        if not m:
            raise TranscriptParseError(f"SRT block {block_no} has an invalid timing line")
        body = _TAG.sub("", " ".join(ln.strip() for ln in lines[idx + 1 :])).strip()
        if not body:
            continue
        speaker, body = _split_speaker(body)
        entries.append(
            ParsedEntry(
                text=body,
                speaker=speaker,
                start_ms=_ts_to_ms(m["a"]),
                end_ms=_ts_to_ms(m["b"]),
                metadata={"cue": block_no},
            )
        )
    if not entries:
        raise TranscriptParseError("SRT file contains no subtitle cues")
    return entries


def parse_vtt(text: str) -> list[ParsedEntry]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.lstrip().startswith("WEBVTT"):
        raise TranscriptParseError("VTT file must start with 'WEBVTT'")
    blocks = re.split(r"\n\s*\n", normalized.strip())[1:]
    entries: list[ParsedEntry] = []
    for block_no, block in enumerate(blocks, start=1):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_idx = next((i for i, ln in enumerate(lines[:2]) if "-->" in ln), None)
        if timing_idx is None:
            raise TranscriptParseError(f"VTT cue {block_no} has no timing line")
        m = _VTT_TIME.search(lines[timing_idx])
        if not m:
            raise TranscriptParseError(f"VTT cue {block_no} has an invalid timing line")
        raw_body = " ".join(ln.strip() for ln in lines[timing_idx + 1 :])
        voice = _VTT_VOICE.search(raw_body)
        speaker = voice.group(1).strip() if voice else None
        body = _TAG.sub("", raw_body).strip()
        if speaker is None:
            speaker, body = _split_speaker(body)
        if not body:
            continue
        meta: dict[str, Any] = {"cue": block_no}
        if timing_idx == 1:
            meta["cue_id"] = lines[0].strip()[:100]
        entries.append(
            ParsedEntry(text=body, speaker=speaker, start_ms=_ts_to_ms(m["a"]), end_ms=_ts_to_ms(m["b"]), metadata=meta)
        )
    if not entries:
        raise TranscriptParseError("VTT file contains no cues")
    return entries


class _JsonEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    speaker: str | None = Field(default=None, max_length=200)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    language: Language | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _order(self) -> _JsonEntry:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class _JsonTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^1\.\d+$")
    language: Language | None = None
    entries: list[_JsonEntry] = Field(min_length=1)


def parse_json(text: str) -> list[ParsedEntry]:
    try:
        doc = _JsonTranscript.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise TranscriptParseError(f"Invalid JSON: {exc.msg} (line {exc.lineno})") from exc
    except ValidationError as exc:
        err = exc.errors()[0]
        raise TranscriptParseError(
            f"JSON transcript does not match schema: {'.'.join(map(str, err['loc']))}: {err['msg']}"
        ) from exc
    meta_size = len(json.dumps([e.metadata for e in doc.entries]))
    if meta_size > 200_000:
        raise TranscriptParseError("JSON transcript metadata is too large")
    return [
        ParsedEntry(
            text=e.text,
            speaker=e.speaker,
            start_ms=e.start_ms,
            end_ms=e.end_ms,
            language=e.language or doc.language,
            metadata=e.metadata,
        )
        for e in doc.entries
    ]


PARSERS = {
    TranscriptFormat.text: parse_plain_text,
    TranscriptFormat.txt: parse_plain_text,
    TranscriptFormat.srt: parse_srt,
    TranscriptFormat.vtt: parse_vtt,
    TranscriptFormat.json: parse_json,
}

EXTENSION_FORMATS = {
    ".txt": TranscriptFormat.txt,
    ".srt": TranscriptFormat.srt,
    ".vtt": TranscriptFormat.vtt,
    ".json": TranscriptFormat.json,
}
