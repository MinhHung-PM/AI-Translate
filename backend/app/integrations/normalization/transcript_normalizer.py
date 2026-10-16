"""Map provider transcript payloads to canonical events.

Transcript *files* (Teams/Zoom WebVTT) reuse the Workstream 1 parsers so
there is one parsing implementation in the codebase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.integrations.models import CanonicalEvent, EventType
from app.models.enums import Language
from app.services.transcripts.normalize import clean_text, detect_language
from app.services.transcripts.parsers import TranscriptParseError, parse_plain_text, parse_vtt

_LANGS = {lang.value for lang in Language}


def language_from_code(code: str | None) -> Language | None:
    """BCP-47 ("ja-JP", "vi", "en-US") → supported Language, else None."""
    if not code:
        return None
    base = code.split("-")[0].lower()
    return Language(base) if base in _LANGS else None


def events_from_vtt(
    text: str, *, provider: str, provider_meeting_id: str, transcript_id: str, metadata: dict[str, Any] | None = None
) -> list[CanonicalEvent]:
    """WebVTT (Teams `<v Speaker>` tags, Zoom `Name: text`) → canonical events.
    Cue ids, when present, become stable entry ids."""
    try:
        parsed = parse_vtt(text)
    except TranscriptParseError:
        # Unattributed formats are plain timestamped text; fall back without inventing speakers.
        parsed = parse_plain_text(text)
    events: list[CanonicalEvent] = []
    for idx, p in enumerate(parsed, start=1):
        body = clean_text(p.text)
        if not body:
            continue
        cue = p.metadata.get("cue_id") or p.metadata.get("cue") or idx
        events.append(
            CanonicalEvent(
                provider=provider,
                provider_meeting_id=provider_meeting_id,
                entry_id=f"{transcript_id}:{cue}",
                speaker_display_name=p.speaker,
                start_timestamp_ms=p.start_ms,
                end_timestamp_ms=p.end_ms,
                source_language=detect_language(body),
                original_text=body,
                provider_sequence=idx,
                source_metadata={**(metadata or {}), "transcript_id": transcript_id},
            )
        )
    return events


def offset_ms(start: str | None, origin: datetime | None) -> int | None:
    """RFC 3339 timestamp → milliseconds after ``origin``; None when unknown."""
    if not start or origin is None:
        return None
    ts = datetime.fromisoformat(start.replace("Z", "+00:00"))
    delta = int((ts - origin).total_seconds() * 1000)
    return max(delta, 0)


def lifecycle_event(
    provider: str, provider_meeting_id: str | None, event_type: EventType, **meta: Any
) -> CanonicalEvent:
    return CanonicalEvent(
        provider=provider, provider_meeting_id=provider_meeting_id, event_type=event_type, source_metadata=meta
    )
