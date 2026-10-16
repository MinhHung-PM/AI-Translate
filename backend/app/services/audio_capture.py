"""Live audio capture: browser audio chunks → speech-to-text with speaker
diarization → transcript entries → live translation.

Flow per chunk (one source at a time, serialized by an advisory lock):

1. validate the WAV (16-bit mono, ≤ ``AUDIO_CHUNK_MAX_SECONDS``);
2. send it to the STT provider with up to 4 known-speaker voice references of
   that source, so a returning speaker keeps the same label;
3. map provider labels to session speakers (S1, S2 …). A new speaker gets a
   profile only when ≥ 2 s of their audio exists in the chunk (the provider's
   minimum reference length); otherwise the segment stays unattributed —
   speakers are never invented;
4. store segments through the common ``ingest_event`` path (idempotent per
   chunk) and translate them immediately with the user's AI provider.

Audio itself is never persisted. Only the short encrypted voice references are
kept while the session runs and are deleted when it stops.
"""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.ai.base import ProviderError, TokenUsage
from app.ai.catalog import get_catalog
from app.audio.stt import REF_MAX_S, REF_MIN_S, KnownSpeaker, MockSTT, OpenAIDiarizingSTT, SpeechToText, SttResult
from app.audio.wav import PcmAudio, concat, parse_wav
from app.core.config import get_settings
from app.core.crypto import CryptoError
from app.core.errors import Conflict, ProviderNotConfigured, SpeechToTextFailed, ValidationFailed
from app.db.base import utcnow
from app.integrations.models import CanonicalEvent
from app.models import AIProviderConfiguration, AudioSpeakerProfile, LiveSession, Meeting, Project, TranscriptEntry
from app.models.enums import Language, LiveSessionStatus
from app.services.ingestion import ingest_event
from app.services.provider_config import get_keyring, resolve_provider
from app.services.transcripts.normalize import clean_text
from app.services.usage import DbUsageMeter, UsageContext

CONNECTOR = "audio_capture"
ACTIVE = (LiveSessionStatus.running, LiveSessionStatus.waiting)


class AudioSourceIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    kind: Literal["microphone", "system", "tab", "device"]
    label: str = Field(min_length=1, max_length=80)
    single_speaker: bool = False  # e.g. "my microphone": no diarization, label = source label


class AudioSessionIn(BaseModel):
    sources: list[AudioSourceIn] = Field(min_length=1)
    # Languages that may be spoken (constrains recognition). Default: the meeting's languages.
    languages: list[Literal["ja", "vi", "en"]] | None = Field(default=None, min_length=1, max_length=3)
    translate: bool = True
    # streaming = words appear while speaking (OpenAI Realtime over WebRTC);
    # chunked = one request per utterance (supports voice-reference speaker tracking).
    mode: Literal["streaming", "chunked"] = "streaming"
    consent_confirmed: bool


@dataclass
class ChunkOutcome:
    entries: list[TranscriptEntry] = field(default_factory=list)
    duplicate: bool = False
    note: str | None = None


# ---- providers ---------------------------------------------------------------


def resolve_stt(db: Session, user_id: uuid.UUID, session_id: uuid.UUID | None) -> tuple[SpeechToText, str]:
    """The user's OpenAI configuration provides speech-to-text. Without one, the
    deterministic MOCK is used only where the mock provider is allowed."""
    settings = get_settings()
    config = db.scalar(
        select(AIProviderConfiguration).where(
            AIProviderConfiguration.user_id == user_id, AIProviderConfiguration.provider == "openai"
        )
    )
    if config is not None:
        resolved = resolve_provider(db, user_id, session_id, config.id)
        return (
            OpenAIDiarizingSTT(
                resolved.credentials,
                settings.stt_model,
                settings.stt_timeout_seconds,
                text_model=settings.stt_text_model,
                text_fallback_model=settings.stt_text_fallback_model,
            ),
            "byok",
        )
    if settings.enable_mock_provider:
        return MockSTT(), "none"
    raise ProviderNotConfigured(
        "Live speech recognition needs an OpenAI API key. Add OpenAI in AI Settings (Cài đặt AI)."
    )


def stt_cost(provider: str, model: str, seconds: float) -> Decimal | None:
    info = get_catalog().get(provider)
    m = next((x for x in (info.stt_models if info else []) if x.id == model), None)
    if m is None or m.audio_per_minute is None:
        return None
    return (m.audio_per_minute * Decimal(str(seconds)) / Decimal(60)).quantize(Decimal("0.000001"))


# ---- sessions ------------------------------------------------------------------


def active_session(db: Session, meeting: Meeting) -> LiveSession | None:
    return db.scalar(
        select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status.in_(ACTIVE)).limit(1)
    )


def start_session(
    db: Session, *, meeting: Meeting, user_id: uuid.UUID, session_id: uuid.UUID, body: AudioSessionIn
) -> LiveSession:
    settings = get_settings()
    if not body.consent_confirmed:
        raise ValidationFailed("Confirm that meeting participants were informed before capturing audio")
    if len(body.sources) > settings.audio_max_sources:
        raise ValidationFailed(f"At most {settings.audio_max_sources} audio sources per session")
    if len({s.id for s in body.sources}) != len(body.sources):
        raise ValidationFailed("Audio source ids must be unique")
    if active_session(db, meeting) is not None:
        raise Conflict("A live session is already running for this meeting")
    stt, _ = resolve_stt(db, user_id, session_id)  # fail fast when STT is unavailable
    languages = list(dict.fromkeys(body.languages or [])) or [
        lang.value for lang in dict.fromkeys(x for x in (meeting.source_language, meeting.target_language) if x)
    ]
    live = LiveSession(
        meeting_id=meeting.id,
        connector=CONNECTOR,
        is_demo=stt.is_mock,
        status=LiveSessionStatus.running,
        created_by_id=user_id,
        requested_session_id=session_id,
        provider_session_id=stt.model,
        last_event_at=utcnow(),
        capture_config={
            "sources": [s.model_dump() for s in body.sources],
            "translate": body.translate,
            "languages": languages or ["ja", "vi", "en"],
            # Streaming needs a real provider; the MOCK only supports chunked mode.
            "mode": "chunked" if stt.is_mock else body.mode,
            "stt_model": stt.model,
            "consent_confirmed_at": utcnow().isoformat(),
        },
        status_message=("MOCK speech-to-text (development only): no real speech recognition." if stt.is_mock else None),
    )
    db.add(live)
    db.flush()
    return live


def _wipe_references(db: Session, live: LiveSession) -> None:
    db.execute(
        update(AudioSpeakerProfile)
        .where(AudioSpeakerProfile.live_session_id == live.id)
        .values(encrypted_reference=None)
    )


def stop_session(db: Session, live: LiveSession, status: LiveSessionStatus = LiveSessionStatus.stopped) -> None:
    if live.status in ACTIVE:
        live.status = status
        live.ended_at = utcnow()
    _wipe_references(db, live)


def purge_idle_sessions(db: Session) -> int:
    """Maintenance: end capture sessions whose browser disappeared and delete
    their voice references."""
    cutoff = utcnow() - timedelta(minutes=get_settings().audio_session_idle_minutes)
    stale = db.scalars(
        select(LiveSession).where(
            LiveSession.connector == CONNECTOR, LiveSession.status.in_(ACTIVE), LiveSession.last_event_at < cutoff
        )
    ).all()
    for live in stale:
        stop_session(db, live, LiveSessionStatus.interrupted)
        live.status_message = "Capture stopped: no audio received from the browser for a while."
    # Defensive: references must never outlive their session.
    db.execute(
        update(AudioSpeakerProfile)
        .where(
            AudioSpeakerProfile.encrypted_reference.is_not(None),
            AudioSpeakerProfile.live_session_id.in_(select(LiveSession.id).where(LiveSession.status.not_in(ACTIVE))),
        )
        .values(encrypted_reference=None)
    )
    return len(stale)


def source_config(live: LiveSession, source_id: str) -> dict[str, Any]:
    for s in (live.capture_config or {}).get("sources", []):
        if s.get("id") == source_id:
            return dict(s)
    raise ValidationFailed("Unknown audio source for this session")


# ---- speakers ------------------------------------------------------------------


def _aad(live: LiveSession, key: str) -> str:
    return f"audio-speaker-ref:{live.id}:{key}"


def _known_speakers(db: Session, live: LiveSession, source_id: str) -> list[tuple[AudioSpeakerProfile, KnownSpeaker]]:
    keyring = get_keyring()
    if keyring is None:
        return []
    profiles = db.scalars(
        select(AudioSpeakerProfile)
        .where(
            AudioSpeakerProfile.live_session_id == live.id,
            AudioSpeakerProfile.source_id == source_id,
            AudioSpeakerProfile.encrypted_reference.is_not(None),
        )
        .order_by(AudioSpeakerProfile.last_active_at.desc())
        .limit(4)
    ).all()
    out = []
    for p in profiles:
        assert p.encrypted_reference is not None
        try:
            wav = base64.b64decode(keyring.decrypt(p.encrypted_reference, _aad(live, p.speaker_key)))
        except (CryptoError, ValueError):
            continue
        out.append((p, KnownSpeaker(p.speaker_key, wav)))
    return out


def _new_profile(db: Session, live: LiveSession, source_id: str, reference: PcmAudio | None) -> AudioSpeakerProfile:
    ordinal = (
        db.scalar(
            select(func.coalesce(func.max(AudioSpeakerProfile.ordinal), 0)).where(
                AudioSpeakerProfile.live_session_id == live.id
            )
        )
        or 0
    ) + 1
    profile = AudioSpeakerProfile(
        live_session_id=live.id,
        source_id=source_id,
        speaker_key=f"S{ordinal}",
        ordinal=ordinal,
        display_name=f"Người {ordinal}",
    )
    keyring = get_keyring()
    if reference is not None and keyring is not None:
        encoded = base64.b64encode(reference.to_wav()).decode()
        profile.encrypted_reference = keyring.encrypt(encoded, _aad(live, profile.speaker_key))
    db.add(profile)
    db.flush()
    return profile


def _assign_speakers(
    db: Session,
    live: LiveSession,
    source_id: str,
    audio: PcmAudio,
    result: SttResult,
    known: dict[str, AudioSpeakerProfile],
) -> dict[str, AudioSpeakerProfile | None]:
    """Provider label → session profile (None = not enough audio to identify)."""
    mapping: dict[str, AudioSpeakerProfile | None] = {}
    labels = {s.speaker for s in result.segments if s.speaker}
    for label in sorted(labels):
        if label in known:
            mapping[label] = known[label]
            continue
        parts = [audio.slice(s.start_s, s.end_s) for s in result.segments if s.speaker == label]
        total = sum(p.duration_s for p in parts)
        if total < REF_MIN_S:
            mapping[label] = None
            continue
        mapping[label] = _new_profile(db, live, source_id, concat(parts, REF_MAX_S))
    return mapping


def rename_speaker(db: Session, live: LiveSession, speaker_key: str, display_name: str) -> AudioSpeakerProfile:
    name = clean_text(display_name)[:200]
    if not name:
        raise ValidationFailed("Speaker name cannot be empty")
    profile = db.scalar(
        select(AudioSpeakerProfile).where(
            AudioSpeakerProfile.live_session_id == live.id, AudioSpeakerProfile.speaker_key == speaker_key
        )
    )
    if profile is None:
        raise ValidationFailed("Unknown speaker")
    profile.display_name = name
    db.execute(
        update(TranscriptEntry)
        .where(
            TranscriptEntry.meeting_id == live.meeting_id,
            TranscriptEntry.source_metadata["live_session_id"].astext == str(live.id),
            TranscriptEntry.source_metadata["audio_speaker_key"].astext == speaker_key,
        )
        .values(speaker_label=name)
    )
    return profile


# ---- chunks ----------------------------------------------------------------------


def process_chunk(
    db: Session,
    *,
    live: LiveSession,
    meeting: Meeting,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    source_id: str,
    chunk_seq: int,
    offset_ms: int,
    wav_bytes: bytes,
) -> ChunkOutcome:
    settings = get_settings()
    if live.connector != CONNECTOR or live.status not in ACTIVE:
        raise Conflict("This audio capture session is not running")
    source = source_config(live, source_id)
    chunk_ref = f"{source_id}:{chunk_seq}"
    # One chunk of one source at a time: keeps speaker numbering consistent.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{live.id}:{source_id}"})
    existing = db.scalars(
        select(TranscriptEntry)
        .where(
            TranscriptEntry.meeting_id == meeting.id,
            TranscriptEntry.source_metadata["live_session_id"].astext == str(live.id),
            TranscriptEntry.source_metadata["audio_chunk"].astext == chunk_ref,
        )
        .order_by(TranscriptEntry.sequence)
    ).all()
    if existing:
        return ChunkOutcome(entries=list(existing), duplicate=True)

    audio = parse_wav(wav_bytes, max_seconds=settings.audio_chunk_max_seconds)
    if audio.rms < settings.audio_min_rms:
        # Near-silence: not sent (STT models invent text on silence) and not billed.
        live.last_event_at = utcnow()
        db.commit()
        return ChunkOutcome(note=None)
    stt, key_source = resolve_stt(db, user_id, session_id)
    diarize = not source.get("single_speaker")
    known_pairs = _known_speakers(db, live, source_id) if diarize else []
    languages: list[str] = list((live.capture_config or {}).get("languages") or [])

    meter = DbUsageMeter(db)
    ctx = UsageContext(user_id, meeting.project_id, meeting.id, None, stt.key, stt.model, key_source)
    started = time.monotonic()
    try:
        if diarize:
            result = stt.transcribe(
                audio.to_wav(),
                language=languages[0] if len(languages) == 1 else None,
                known=[k for _, k in known_pairs],
                diarize=True,
            )
        else:
            result = stt.transcribe_text(audio.to_wav(), languages=languages, keywords=_keywords(db, meeting))
    except ProviderError as err:
        rec = meter.record(
            ctx,
            "speech_to_text",
            TokenUsage(),
            duration_ms=int((time.monotonic() - started) * 1000),
            success=False,
            error_code=err.code.value,
        )
        rec.audio_seconds = round(audio.duration_s, 2)
        live.status_message = f"Speech-to-text error: {err.message}"
        db.commit()
        raise SpeechToTextFailed(
            err.message, details={"provider_code": err.code.value, "retryable": err.retryable}
        ) from None
    ctx.model = result.model
    rec = meter.record(
        ctx,
        "speech_to_text",
        TokenUsage(reported_by_provider=True),
        duration_ms=int((time.monotonic() - started) * 1000),
        success=True,
    )
    rec.audio_seconds = round(audio.duration_s, 2)
    rec.estimated_cost_usd = stt_cost(stt.key, result.model, audio.duration_s)
    reported = result.language if result.language in {lang.value for lang in Language} else None

    known = {p.speaker_key: p for p, _ in known_pairs}
    mapping = _assign_speakers(db, live, source_id, audio, result, known) if diarize else {}
    now = utcnow()
    outcome = ChunkOutcome()
    for i, seg in enumerate(result.segments):
        profile = mapping.get(seg.speaker) if seg.speaker else None
        speaker_name = source["label"] if not diarize else (profile.display_name if profile else None)
        if profile is not None:
            profile.segments += 1
            profile.last_active_at = now
        event = CanonicalEvent(
            provider=CONNECTOR,
            provider_meeting_id=f"audio:{live.id}",
            entry_id=f"{live.id}:{chunk_ref}:{i}",
            speaker_id=profile.speaker_key if profile else None,
            speaker_display_name=speaker_name,
            start_timestamp_ms=offset_ms + int(seg.start_s * 1000),
            end_timestamp_ms=offset_ms + int(seg.end_s * 1000),
            # Language actually recognised (never forced to the meeting default; ingestion detects it).
            source_language=Language(reported) if reported else None,
            original_text=seg.text,
            is_demo=stt.is_mock,
            source_metadata={
                "live_session_id": str(live.id),
                "audio_chunk": chunk_ref,
                "audio_source_id": source_id,
                "audio_source_kind": source.get("kind"),
                "audio_speaker_key": profile.speaker_key if profile else None,
                "stt_model": result.model,
            },
        )
        entry, created = ingest_event(db, meeting, event)
        if entry is not None and created:
            outcome.entries.append(entry)
    live.entries_emitted += len(outcome.entries)
    live.entries_total = live.entries_emitted
    live.last_event_at = now
    if not stt.is_mock:
        live.status_message = None
    db.commit()

    if outcome.entries and (live.capture_config or {}).get("translate", True):
        outcome.note = translate_now(
            db, live=live, meeting=meeting, user_id=user_id, session_id=session_id, entries=outcome.entries
        )
    return outcome


def translate_now(
    db: Session,
    *,
    live: LiveSession,
    meeting: Meeting,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    entries: list[TranscriptEntry],
) -> str | None:
    from app.services.translation import translate_entries

    try:
        resolved = resolve_provider(db, user_id, session_id)
    except ProviderNotConfigured as exc:
        return f"Not translated: {exc.message}"
    project = db.get(Project, meeting.project_id)
    assert project is not None
    outcome = translate_entries(
        db,
        meeting=meeting,
        project=project,
        entries=entries,
        target=meeting.target_language,
        resolved=resolved,
        user_id=user_id,
        job_id=None,
    )
    db.commit()
    if outcome.failed:
        return f"{outcome.failed} segment(s) could not be translated; retry from the transcript view."
    return None


def _keywords(db: Session, meeting: Meeting) -> list[str]:
    """Glossary terms and participant names guide recognition of names and jargon."""
    from app.models import GlossaryEntry, MeetingParticipant

    terms = db.scalars(
        select(GlossaryEntry.source_term)
        .where(GlossaryEntry.project_id == meeting.project_id, GlossaryEntry.is_active.is_(True))
        .limit(60)
    ).all()
    names = db.scalars(select(MeetingParticipant.display_name).where(MeetingParticipant.meeting_id == meeting.id)).all()
    out: list[str] = []
    for w in [*names, *terms]:
        w = clean_text(w)[:50]
        if w and w not in out:
            out.append(w)
    return out[:50]


# ---- streaming (OpenAI Realtime) ------------------------------------------------


def realtime_token(
    db: Session,
    *,
    live: LiveSession,
    meeting: Meeting,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    source_id: str,
) -> Any:
    from app.audio.realtime import create_transcription_token

    settings = get_settings()
    if live.connector != CONNECTOR or live.status not in ACTIVE:
        raise Conflict("This audio capture session is not running")
    config = live.capture_config or {}
    if config.get("mode") != "streaming":
        raise Conflict("This session does not use streaming captions")
    source = source_config(live, source_id)
    stt, _ = resolve_stt(db, user_id, session_id)
    creds = getattr(stt, "_creds", None)
    if stt.is_mock or creds is None:
        raise ProviderNotConfigured("Streaming captions need an OpenAI API key (AI Settings).")
    try:
        token = create_transcription_token(
            creds,
            languages=list(config.get("languages") or []),
            keywords=_keywords(db, meeting),
            far_field=source.get("kind") != "microphone",
            model=settings.stt_realtime_model,
            fallback_model=settings.stt_realtime_fallback_model,
            ttl_seconds=settings.stt_realtime_token_ttl_seconds,
            timeout_s=settings.stt_timeout_seconds,
        )
    except ProviderError as err:
        live.status_message = f"Live caption error: {err.message}"
        db.commit()
        raise SpeechToTextFailed(
            err.message, details={"provider_code": err.code.value, "retryable": err.retryable}
        ) from None
    live.last_event_at = utcnow()
    live.status_message = None
    db.commit()
    return token


class RealtimeSegmentIn(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    item_id: str = Field(pattern=r"^[A-Za-z0-9_\-:.]{1,120}$")
    text: str = Field(max_length=5000)
    offset_ms: int = Field(ge=0, le=86_400_000)
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    model: str | None = Field(default=None, max_length=64)
    speaker: str | None = Field(default=None, max_length=64)  # provider label from segment events


def _streaming_profile(db: Session, live: LiveSession, source_id: str, label: str) -> AudioSpeakerProfile:
    profile = db.scalar(
        select(AudioSpeakerProfile).where(
            AudioSpeakerProfile.live_session_id == live.id,
            AudioSpeakerProfile.source_id == source_id,
            AudioSpeakerProfile.provider_label == label,
        )
    )
    if profile is None:
        profile = _new_profile(db, live, source_id, None)
        profile.provider_label = label
    return profile


def ingest_realtime_segment(
    db: Session,
    *,
    live: LiveSession,
    meeting: Meeting,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    body: RealtimeSegmentIn,
) -> ChunkOutcome:
    """Store one final utterance recognised by the browser's Realtime session."""
    if live.connector != CONNECTOR or live.status not in ACTIVE:
        raise Conflict("This audio capture session is not running")
    config = live.capture_config or {}
    if config.get("mode") != "streaming":
        raise Conflict("This session does not use streaming captions")
    source = source_config(live, body.source_id)
    text_value = clean_text(body.text)
    if not text_value:
        return ChunkOutcome()
    chunk_ref = f"{body.source_id}:rt:{body.item_id}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{live.id}:{body.source_id}"})
    existing = db.scalars(
        select(TranscriptEntry).where(
            TranscriptEntry.meeting_id == meeting.id,
            TranscriptEntry.source_metadata["live_session_id"].astext == str(live.id),
            TranscriptEntry.source_metadata["audio_chunk"].astext == chunk_ref,
        )
    ).all()
    if existing:
        return ChunkOutcome(entries=list(existing), duplicate=True)

    settings = get_settings()
    model = body.model or settings.stt_realtime_model
    seconds = round((body.duration_ms or 0) / 1000, 2)
    ctx = UsageContext(user_id, meeting.project_id, meeting.id, None, "openai", model, "byok")
    rec = DbUsageMeter(db).record(
        ctx, "speech_to_text", TokenUsage(reported_by_provider=False), duration_ms=0, success=True
    )
    rec.audio_seconds = seconds or None
    rec.estimated_cost_usd = stt_cost("openai", model, seconds) if seconds else None

    profile: AudioSpeakerProfile | None = None
    if source.get("single_speaker"):
        speaker_name: str | None = source["label"]
    elif body.speaker:
        profile = _streaming_profile(db, live, body.source_id, body.speaker)
        profile.segments += 1
        profile.last_active_at = utcnow()
        speaker_name = profile.display_name
    else:
        speaker_name = None  # no speaker information from the provider: never invented
    event = CanonicalEvent(
        provider=CONNECTOR,
        provider_meeting_id=f"audio:{live.id}",
        entry_id=f"{live.id}:{chunk_ref}",
        speaker_id=profile.speaker_key if profile else None,
        speaker_display_name=speaker_name,
        start_timestamp_ms=body.offset_ms,
        end_timestamp_ms=body.offset_ms + body.duration_ms if body.duration_ms else None,
        original_text=text_value,
        source_metadata={
            "live_session_id": str(live.id),
            "audio_chunk": chunk_ref,
            "audio_source_id": body.source_id,
            "audio_source_kind": source.get("kind"),
            "audio_speaker_key": profile.speaker_key if profile else None,
            "stt_model": model,
            "streaming": True,
        },
    )
    entry, created = ingest_event(db, meeting, event)
    outcome = ChunkOutcome(entries=[entry] if entry is not None and created else [])
    live.entries_emitted += len(outcome.entries)
    live.entries_total = live.entries_emitted
    live.last_event_at = utcnow()
    db.commit()
    if outcome.entries and config.get("translate", True):
        outcome.note = translate_now(
            db, live=live, meeting=meeting, user_id=user_id, session_id=session_id, entries=outcome.entries
        )
    return outcome


def list_speakers(db: Session, live: LiveSession) -> list[AudioSpeakerProfile]:
    return list(
        db.scalars(
            select(AudioSpeakerProfile)
            .where(AudioSpeakerProfile.live_session_id == live.id)
            .order_by(AudioSpeakerProfile.ordinal)
        )
    )
