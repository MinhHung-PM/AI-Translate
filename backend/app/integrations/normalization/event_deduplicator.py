"""Stable deduplication keys.

Priority: provider entry id > provider sequence > (start time + speaker + text).
Identical *text* at a different time or from a different speaker is a
different key, so legitimate repeated phrases ("はい", "OK") are kept. When a
provider gives none of these, no key is produced and the event is accepted.
"""

from __future__ import annotations

import hashlib

from app.integrations.models import CanonicalEvent


def _h(*parts: object) -> str:
    return hashlib.sha256("\x1f".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def dedup_key(event: CanonicalEvent) -> str | None:
    scope = (event.provider, event.provider_meeting_id or "")
    if event.entry_id:
        return _h(*scope, "id", event.entry_id)
    if event.provider_sequence is not None:
        return _h(*scope, "seq", event.provider_sequence)
    if event.start_timestamp_ms is not None and event.original_text:
        speaker = event.speaker_id or event.speaker_display_name or ""
        return _h(*scope, "ts", event.start_timestamp_ms, speaker, event.original_text)
    return None
