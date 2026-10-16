from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk, utcnow


class AudioSpeakerProfile(UUIDPk, Base):
    """A speaker detected in one audio source of a live capture session.

    ``encrypted_reference`` is a short (2–10 s) voice sample of this speaker,
    encrypted with the keyring, sent back to the speech-to-text provider so the
    same person keeps the same label across chunks. It is deleted when the
    session ends (or is purged by maintenance) — no other audio is stored.
    """

    __tablename__ = "audio_speaker_profiles"
    __table_args__ = (UniqueConstraint("live_session_id", "speaker_key", name="uq_audio_speaker_key"),)

    live_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sessions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(String(64))
    speaker_key: Mapped[str] = mapped_column(String(16))  # S1, S2 … unique within the session
    ordinal: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(200))
    encrypted_reference: Mapped[str | None] = mapped_column(Text)
    # Streaming mode: the provider's own speaker label (e.g. "spk_1") mapped to this profile.
    provider_label: Mapped[str | None] = mapped_column(String(64))
    segments: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
