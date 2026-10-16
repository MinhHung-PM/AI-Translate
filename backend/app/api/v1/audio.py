"""Live audio capture API (see services/audio_capture.py)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth, AuthContext
from app.api.v1.transcripts import entry_out
from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound, PayloadTooLarge
from app.core.rate_limit import rate_limiter
from app.models import LiveSession, Meeting
from app.schemas.api import EntryOut, LiveSessionOut
from app.schemas.common import ApiModel
from app.services import audio_capture as audio
from app.services.audit import record_audit
from app.services.authz import AccessLevel, load_meeting, require_edit_meeting

router = APIRouter(tags=["audio"])


def _audio_rate_limit(auth: Auth) -> AuthContext:
    rate_limiter.check(f"audio:{auth.user.id}", get_settings().audio_rate_limit_per_minute)
    return auth


AudioAuth = Annotated[AuthContext, Depends(_audio_rate_limit)]


class SpeakerOut(ApiModel):
    speaker_key: str
    source_id: str
    display_name: str
    segments: int
    has_voice_reference: bool


class AudioSessionOut(BaseModel):
    session: LiveSessionOut
    speakers: list[SpeakerOut]


class ChunkOut(BaseModel):
    entries: list[EntryOut]
    duplicate: bool
    note: str | None


class RealtimeTokenIn(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")


class RealtimeTokenOut(BaseModel):
    client_secret: str
    expires_at: int
    model: str
    calls_url: str


class SpeakerRename(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


def _load(db: DB, auth: AuthContext, session_id: uuid.UUID, *, edit: bool) -> tuple[LiveSession, Meeting]:
    live = db.get(LiveSession, session_id)
    if live is None or live.connector != audio.CONNECTOR:
        raise NotFound("Audio session not found")
    meeting, access = load_meeting(
        db, auth.user, live.meeting_id, AccessLevel.contribute if edit else AccessLevel.transcript
    )
    if edit:
        require_edit_meeting(access, meeting, auth.user)
    return live, meeting


def _out(db: DB, live: LiveSession) -> AudioSessionOut:
    return AudioSessionOut(
        session=LiveSessionOut.model_validate(live),
        speakers=[
            SpeakerOut(
                speaker_key=p.speaker_key,
                source_id=p.source_id,
                display_name=p.display_name,
                segments=p.segments,
                has_voice_reference=p.encrypted_reference is not None,
            )
            for p in audio.list_speakers(db, live)
        ],
    )


@router.post("/meetings/{meeting_id}/audio-sessions", response_model=AudioSessionOut, status_code=201)
def start_audio_session(meeting_id: uuid.UUID, body: audio.AudioSessionIn, auth: Auth, db: DB) -> AudioSessionOut:
    """Start live capture. The browser then posts audio chunks per source."""
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    live = audio.start_session(db, meeting=meeting, user_id=auth.user.id, session_id=auth.session.id, body=body)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="audio_capture.start",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        ip=auth.ip,
        details={"sources": [s.kind for s in body.sources], "mock": live.is_demo},
    )
    db.commit()
    return _out(db, live)


@router.get("/audio-sessions/{session_id}", response_model=AudioSessionOut)
def get_audio_session(session_id: uuid.UUID, auth: Auth, db: DB) -> AudioSessionOut:
    live, _ = _load(db, auth, session_id, edit=False)
    return _out(db, live)


@router.post("/audio-sessions/{session_id}/chunks", response_model=ChunkOut)
def post_audio_chunk(
    session_id: uuid.UUID,
    auth: AudioAuth,
    db: DB,
    source_id: Annotated[str, Form(pattern=r"^[a-z0-9-]{1,32}$")],
    chunk_seq: Annotated[int, Form(ge=0, le=10_000_000)],
    offset_ms: Annotated[int, Form(ge=0, le=86_400_000)],
    file: Annotated[UploadFile, File()],
) -> ChunkOut:
    """One utterance (≤ 30 s, 16-bit mono WAV) from one source. Synchronous:
    returns the recognised, speaker-labelled entries (translation included)."""
    live, meeting = _load(db, auth, session_id, edit=True)
    if live.created_by_id != auth.user.id:
        raise Forbidden("Only the user who started the capture can send audio to it")
    limit = get_settings().audio_chunk_max_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(f"Audio chunk exceeds {limit} bytes")
    outcome = audio.process_chunk(
        db,
        live=live,
        meeting=meeting,
        user_id=auth.user.id,
        session_id=auth.session.id,
        source_id=source_id,
        chunk_seq=chunk_seq,
        offset_ms=offset_ms,
        wav_bytes=data,
    )
    for e in outcome.entries:
        db.refresh(e)
    return ChunkOut(
        entries=[entry_out(e, meeting.target_language) for e in outcome.entries],
        duplicate=outcome.duplicate,
        note=outcome.note,
    )


@router.post("/audio-sessions/{session_id}/realtime-token", response_model=RealtimeTokenOut)
def create_realtime_token(session_id: uuid.UUID, body: RealtimeTokenIn, auth: AudioAuth, db: DB) -> RealtimeTokenOut:
    """Short-lived OpenAI client secret for one source's streaming caption
    connection (the user's API key never leaves the server)."""
    live, meeting = _load(db, auth, session_id, edit=True)
    if live.created_by_id != auth.user.id:
        raise Forbidden("Only the user who started the capture can stream audio to it")
    token = audio.realtime_token(
        db, live=live, meeting=meeting, user_id=auth.user.id, session_id=auth.session.id, source_id=body.source_id
    )
    return RealtimeTokenOut(
        client_secret=token.value,
        expires_at=token.expires_at,
        model=token.model,
        calls_url="https://api.openai.com/v1/realtime/calls",
    )


@router.post("/audio-sessions/{session_id}/segments", response_model=ChunkOut)
def post_realtime_segment(session_id: uuid.UUID, body: audio.RealtimeSegmentIn, auth: AudioAuth, db: DB) -> ChunkOut:
    """A final utterance recognised by the streaming session → stored and translated."""
    live, meeting = _load(db, auth, session_id, edit=True)
    if live.created_by_id != auth.user.id:
        raise Forbidden("Only the user who started the capture can send audio to it")
    outcome = audio.ingest_realtime_segment(
        db, live=live, meeting=meeting, user_id=auth.user.id, session_id=auth.session.id, body=body
    )
    for e in outcome.entries:
        db.refresh(e)
    return ChunkOut(
        entries=[entry_out(e, meeting.target_language) for e in outcome.entries],
        duplicate=outcome.duplicate,
        note=outcome.note,
    )


@router.post("/audio-sessions/{session_id}/stop", response_model=AudioSessionOut)
def stop_audio_session(session_id: uuid.UUID, auth: Auth, db: DB) -> AudioSessionOut:
    live, _ = _load(db, auth, session_id, edit=True)
    audio.stop_session(db, live)
    db.commit()
    return _out(db, live)


@router.patch("/audio-sessions/{session_id}/speakers/{speaker_key}", response_model=SpeakerOut)
def rename_audio_speaker(
    session_id: uuid.UUID, speaker_key: str, body: SpeakerRename, auth: Auth, db: DB
) -> SpeakerOut:
    live, _ = _load(db, auth, session_id, edit=True)
    p = audio.rename_speaker(db, live, speaker_key, body.display_name)
    db.commit()
    return SpeakerOut(
        speaker_key=p.speaker_key,
        source_id=p.source_id,
        display_name=p.display_name,
        segments=p.segments,
        has_voice_reference=p.encrypted_reference is not None,
    )
