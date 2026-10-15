from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, PayloadTooLarge, ValidationFailed
from app.models import Memo, TranscriptEntry, TranscriptImport, User
from app.models.enums import Language, MeetingStatus, MemoStatus, TranscriptFormat
from app.models.meeting import Meeting
from app.services.transcripts.normalize import (
    decode_upload,
    detect_transcript_language,
    normalize_entries,
    safe_filename,
)
from app.services.transcripts.parsers import EXTENSION_FORMATS, PARSERS, ParsedEntry, TranscriptParseError


@dataclass
class ParsedTranscript:
    format: TranscriptFormat
    filename: str | None
    encoding: str
    byte_size: int
    entries: list[ParsedEntry]
    detected_language: Language | None


def parse_upload(
    *, data: bytes | None, text: str | None, filename: str | None, declared_format: TranscriptFormat | None
) -> ParsedTranscript:
    settings = get_settings()
    if (data is None) == (text is None):
        raise ValidationFailed("Provide exactly one of a file or pasted text")
    if text is not None:
        raw = text.encode("utf-8")
        fmt = declared_format or TranscriptFormat.text
        encoding = "utf-8"
        if len(raw) > settings.max_upload_bytes:
            raise PayloadTooLarge(f"Transcript exceeds {settings.max_upload_bytes} bytes")
        decoded = text
    else:
        assert data is not None
        if len(data) > settings.max_upload_bytes:
            raise PayloadTooLarge(f"File exceeds {settings.max_upload_bytes} bytes")
        ext = os.path.splitext((filename or "").lower())[1]
        fmt_from_ext = EXTENSION_FORMATS.get(ext)
        if fmt_from_ext is None:
            raise ValidationFailed("Unsupported file type. Allowed: .txt, .srt, .vtt, .json")
        if declared_format and declared_format not in (fmt_from_ext, TranscriptFormat.text):
            raise ValidationFailed("Declared format does not match the file extension")
        fmt = fmt_from_ext
        raw = data
        try:
            decoded, encoding = decode_upload(data)
        except TranscriptParseError as exc:
            raise ValidationFailed(str(exc)) from exc
    try:
        parsed = PARSERS[fmt](decoded)
        entries = normalize_entries(
            parsed, max_entry_chars=settings.max_entry_chars, max_entries=settings.max_transcript_entries
        )
    except TranscriptParseError as exc:
        raise ValidationFailed(str(exc)) from exc
    return ParsedTranscript(
        format=fmt,
        filename=safe_filename(filename),
        encoding=encoding,
        byte_size=len(raw),
        entries=entries,
        detected_language=detect_transcript_language(entries),
    )


def clear_transcript(db: Session, meeting: Meeting) -> None:
    memo = db.scalar(select(Memo).where(Memo.meeting_id == meeting.id))
    if memo is not None:
        if memo.status == MemoStatus.approved:
            raise Conflict("The memo is approved; reopen it before replacing the transcript")
        db.delete(memo)
    db.execute(delete(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id))
    db.flush()


def next_sequence(db: Session, meeting: Meeting) -> int:
    current = db.scalar(select(func.max(TranscriptEntry.sequence)).where(TranscriptEntry.meeting_id == meeting.id))
    return int(current or 0) + 1


def store_transcript(
    db: Session,
    meeting: Meeting,
    user: User,
    parsed: ParsedTranscript,
    *,
    replace: bool,
    source_language: Language | None,
) -> TranscriptImport:
    existing = db.scalar(
        select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id)
    )
    if existing:
        if not replace:
            raise Conflict("This meeting already has a transcript. Use replace=true to replace it.")
        clear_transcript(db, meeting)
    record = TranscriptImport(
        meeting_id=meeting.id,
        format=parsed.format,
        filename=parsed.filename,
        byte_size=parsed.byte_size,
        encoding=parsed.encoding,
        entry_count=len(parsed.entries),
        detected_language=parsed.detected_language,
        created_by_id=user.id,
    )
    db.add(record)
    db.flush()
    override = source_language or meeting.source_language
    for seq, entry in enumerate(parsed.entries, start=1):
        db.add(
            TranscriptEntry(
                meeting_id=meeting.id,
                import_id=record.id,
                sequence=seq,
                speaker_label=entry.speaker,
                start_ms=entry.start_ms,
                end_ms=entry.end_ms,
                original_text=entry.text,
                # A user override applies to entries whose language was not detected.
                source_language=entry.language or override,
                source_metadata={**entry.metadata, "import_format": parsed.format.value},
            )
        )
    meeting.detected_language = parsed.detected_language
    if source_language:
        meeting.source_language = source_language
    meeting.status = MeetingStatus.transcript_ready
    db.flush()
    return record
