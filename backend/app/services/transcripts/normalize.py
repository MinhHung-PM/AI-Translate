"""Decoding, normalization, segmentation and language detection."""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from charset_normalizer import from_bytes

from app.models.enums import Language
from app.services.transcripts.parsers import ParsedEntry, TranscriptParseError

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_VI_CHARS = set("ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ")


def decode_upload(data: bytes) -> tuple[str, str]:
    """Decode bytes to text. Returns (text, encoding). Rejects binary content."""
    if not data.strip():
        raise TranscriptParseError("The file is empty")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as exc:
            raise TranscriptParseError("Invalid UTF-16 content") from exc
    if b"\x00" in data:
        raise TranscriptParseError("Binary files are not supported")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    # Legacy Japanese exports (Shift_JIS/CP932, EUC-JP) are common; generic
    # detection confuses them with Korean, so accept them when kana appear.
    for enc in ("cp932", "euc_jp"):
        try:
            candidate = data.decode(enc)
        except UnicodeDecodeError:
            continue
        if sum(1 for ch in candidate if "぀" <= ch <= "ヿ") >= 2:
            return candidate, enc
    best = from_bytes(data).best()
    if best is None or best.encoding is None:
        raise TranscriptParseError("Could not detect the text encoding (use UTF-8)")
    # Legacy Japanese encodings (Shift_JIS/CP932/EUC-JP) are common in exports.
    return str(best), best.encoding


def safe_filename(name: str | None) -> str | None:
    """Keep only a display-safe basename; uploads are never written to disk."""
    if not name:
        return None
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^\w.\- ()぀-ヿ一-鿿]", "_", base)[:200]
    return base or None


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL.sub("", text)
    return re.sub(r"[ \t　]+", " ", text).strip()


def detect_language(text: str) -> Language | None:
    kana = sum(1 for ch in text if "぀" <= ch <= "ヿ")
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    vi = sum(1 for ch in text.lower() if ch in _VI_CHARS)
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if kana + cjk >= 2 and kana + cjk >= latin * 0.3:
        return Language.ja
    if vi >= 2 or (vi >= 1 and latin < 15):
        return Language.vi
    if latin >= 3:
        return Language.en
    return None


def detect_transcript_language(entries: Sequence[ParsedEntry]) -> Language | None:
    counts: Counter[Language] = Counter()
    for e in entries:
        lang = e.language or detect_language(e.text)
        if lang:
            counts[lang] += len(e.text)
    return counts.most_common(1)[0][0] if counts else None


_SENTENCE_END = re.compile(r"(?<=[。．！？!?])|(?<=[.;])\s+")


def split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    buf = ""
    for sentence in [s for s in _SENTENCE_END.split(text) if s]:
        while len(sentence) > max_chars:  # no sentence boundary: hard split
            if buf:
                pieces.append(buf.strip())
                buf = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if len(buf) + len(sentence) > max_chars and buf:
            pieces.append(buf.strip())
            buf = ""
        buf += sentence if not buf or buf.endswith(" ") else (" " + sentence if sentence[:1].isascii() else sentence)
    if buf.strip():
        pieces.append(buf.strip())
    return [p for p in pieces if p]


def normalize_entries(entries: Sequence[ParsedEntry], *, max_entry_chars: int, max_entries: int) -> list[ParsedEntry]:
    out: list[ParsedEntry] = []
    for idx, entry in enumerate(entries):
        text = clean_text(entry.text)
        if not text:
            continue
        speaker = clean_text(entry.speaker)[:200] if entry.speaker else None
        lang = entry.language or detect_language(text)
        parts = split_long_text(text, max_entry_chars)
        for part_no, part in enumerate(parts):
            meta = dict(entry.metadata)
            if len(parts) > 1:
                meta.update({"split_from": idx, "part": part_no + 1, "parts": len(parts)})
            out.append(
                replace(
                    entry,
                    text=part,
                    speaker=speaker or None,
                    language=lang,
                    # Sub-timings of split parts are unknown, so they stay null.
                    start_ms=entry.start_ms if part_no == 0 else None,
                    end_ms=entry.end_ms if part_no == len(parts) - 1 else None,
                    metadata=meta,
                )
            )
    if not out:
        raise TranscriptParseError("The transcript contains no text")
    if len(out) > max_entries:
        raise TranscriptParseError(f"The transcript has too many entries ({len(out)} > {max_entries})")
    return out


class Chunkable(Protocol):
    @property
    def text(self) -> str: ...


def chunk_segments[T: Chunkable](items: Sequence[T], max_entries: int, max_chars: int) -> list[list[T]]:
    """Split into ordered chunks bounded by entry count and character count."""
    chunks: list[list[T]] = []
    current: list[T] = []
    size = 0
    for item in items:
        length = len(item.text)
        if current and (len(current) >= max_entries or size + length > max_chars):
            chunks.append(current)
            current, size = [], 0
        current.append(item)
        size += length
    if current:
        chunks.append(current)
    return chunks
