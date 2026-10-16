from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import contains_eager

from app.api.deps import DB, Auth, AuthContext, ai_rate_limit
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, PayloadTooLarge, ValidationFailed
from app.integrations.models import CanonicalEvent
from app.models import Job, LiveSession, Meeting, TranscriptEntry, TranscriptImport, Translation
from app.models.enums import (
    JobKind,
    Language,
    LiveSessionStatus,
    TranscriptFormat,
    TranslationStatus,
)
from app.schemas.api import (
    EntryOut,
    EntryUpdate,
    ImportOut,
    JobOut,
    LiveFeedOut,
    LiveSessionOut,
    TextImportIn,
    TranslateIn,
    TranslationOut,
    TranslationStats,
    TranslationUpdate,
)
from app.schemas.common import Page
from app.services import jobs as job_service
from app.services.audit import record_audit
from app.services.authz import AccessLevel, load_meeting, require_edit_meeting
from app.services.transcripts.importer import parse_upload, store_transcript
from app.services.translation import get_or_create_translation

router = APIRouter(tags=["transcripts"])
TranslateAuth = Annotated[AuthContext, Depends(ai_rate_limit("translate"))]
ReplayAuth = Annotated[AuthContext, Depends(ai_rate_limit("replay"))]


def _read_limited(upload: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(f"File exceeds {limit} bytes")
    return data


def _import(
    db: DB,
    auth: AuthContext,
    meeting: Meeting,
    parsed_kwargs: dict[str, object],
    source_language: Language | None,
    replace: bool,
) -> TranscriptImport:
    parsed = parse_upload(**parsed_kwargs)  # type: ignore[arg-type]
    record = store_transcript(db, meeting, auth.user, parsed, replace=replace, source_language=source_language)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="transcript.import",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={
            "format": parsed.format.value,
            "entries": len(parsed.entries),
            "bytes": parsed.byte_size,
            "replace": replace,
        },
        ip=auth.ip,
    )
    db.commit()
    return record


@router.post("/meetings/{meeting_id}/transcript/upload", response_model=ImportOut, status_code=201)
def upload_transcript(
    meeting_id: uuid.UUID,
    auth: Auth,
    db: DB,
    file: Annotated[UploadFile, File()],
    source_language: Annotated[Language | None, Form()] = None,
    replace: Annotated[bool, Form()] = False,
) -> TranscriptImport:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    data = _read_limited(file)
    # The upload is parsed in memory and never written to disk, so client
    # filenames cannot cause path traversal; only a sanitized basename is kept.
    return _import(
        db,
        auth,
        meeting,
        {"data": data, "text": None, "filename": file.filename, "declared_format": None},
        source_language,
        replace,
    )


@router.post("/meetings/{meeting_id}/transcript/text", response_model=ImportOut, status_code=201)
def import_text(meeting_id: uuid.UUID, body: TextImportIn, auth: Auth, db: DB) -> TranscriptImport:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    return _import(
        db,
        auth,
        meeting,
        {"data": None, "text": body.text, "filename": None, "declared_format": body.format},
        body.source_language,
        body.replace,
    )


@router.get("/meetings/{meeting_id}/transcript/imports", response_model=list[ImportOut])
def list_imports(meeting_id: uuid.UUID, auth: Auth, db: DB) -> list[TranscriptImport]:
    load_meeting(db, auth.user, meeting_id, AccessLevel.transcript)
    return list(
        db.scalars(
            select(TranscriptImport)
            .where(TranscriptImport.meeting_id == meeting_id)
            .order_by(TranscriptImport.created_at.desc())
        )
    )


def entry_out(entry: TranscriptEntry, target: Language) -> EntryOut:
    out = EntryOut.model_validate(entry)
    tr = next((t for t in entry.translations if t.target_language == target), None)
    out.translation = TranslationOut.model_validate(tr) if tr else None
    return out


@router.get("/meetings/{meeting_id}/transcript", response_model=Page[EntryOut])
def get_transcript(
    meeting_id: uuid.UUID,
    auth: Auth,
    db: DB,
    target_language: Language | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: TranslationStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
) -> Page[EntryOut]:
    meeting, _ = load_meeting(db, auth.user, meeting_id, AccessLevel.transcript)
    target = target_language or meeting.target_language
    stmt = (
        select(TranscriptEntry)
        .outerjoin(Translation, (Translation.entry_id == TranscriptEntry.id) & (Translation.target_language == target))
        .where(TranscriptEntry.meeting_id == meeting.id)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                TranscriptEntry.original_text.ilike(pattern),
                Translation.text.ilike(pattern),
                TranscriptEntry.speaker_label.ilike(pattern),
            )
        )
    if status == TranslationStatus.pending:
        stmt = stmt.where(or_(Translation.id.is_(None), Translation.status == TranslationStatus.pending))
    elif status:
        stmt = stmt.where(Translation.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.options(contains_eager(TranscriptEntry.translations))
        .order_by(TranscriptEntry.sequence)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique()
    return Page(items=[entry_out(e, target) for e in rows], total=total, page=page, page_size=page_size)


@router.get("/meetings/{meeting_id}/transcript/stats", response_model=TranslationStats)
def transcript_stats(
    meeting_id: uuid.UUID, auth: Auth, db: DB, target_language: Language | None = None
) -> TranslationStats:
    meeting, _ = load_meeting(db, auth.user, meeting_id, AccessLevel.transcript)
    target = target_language or meeting.target_language
    total = (
        db.scalar(select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id))
        or 0
    )
    counts = dict(
        db.execute(
            select(Translation.status, func.count())
            .join(TranscriptEntry, TranscriptEntry.id == Translation.entry_id)
            .where(TranscriptEntry.meeting_id == meeting.id, Translation.target_language == target)
            .group_by(Translation.status)
        ).all()
    )
    done = counts.get(TranslationStatus.done, 0)
    failed = counts.get(TranslationStatus.failed, 0)
    processing = counts.get(TranslationStatus.processing, 0)
    return TranslationStats(
        total=total, done=done, failed=failed, processing=processing, pending=max(0, total - done - failed - processing)
    )


def _load_entry(db: DB, auth: AuthContext, entry_id: uuid.UUID) -> tuple[TranscriptEntry, Meeting]:
    entry = db.get(TranscriptEntry, entry_id)
    if entry is None:
        raise NotFound("Transcript entry not found")
    meeting, access = load_meeting(db, auth.user, entry.meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    return entry, meeting


@router.patch("/transcript-entries/{entry_id}", response_model=EntryOut)
def update_entry(entry_id: uuid.UUID, body: EntryUpdate, auth: Auth, db: DB) -> EntryOut:
    """Correct the source transcript (e.g. recognition errors). The first
    original wording is preserved in source_metadata for traceability, and
    AI translations of the entry are reset so they are regenerated."""
    entry, meeting = _load_entry(db, auth, entry_id)
    changes = body.model_dump(exclude_unset=True)
    if "original_text" in changes and changes["original_text"] != entry.original_text:
        meta = dict(entry.source_metadata or {})
        meta.setdefault("original_text_before_edit", entry.original_text)
        entry.source_metadata = meta
        entry.original_text = changes["original_text"]
        entry.original_edited = True
        for tr in entry.translations:
            if not tr.is_user_edited:
                tr.status, tr.text = TranslationStatus.pending, None
    if "speaker_label" in changes:
        entry.speaker_label = changes["speaker_label"] or None
    if "source_language" in changes:
        entry.source_language = changes["source_language"]
    record_audit(
        db,
        actor_id=auth.user.id,
        action="transcript.entry_edit",
        resource_type="transcript_entry",
        resource_id=entry.id,
        project_id=meeting.project_id,
        details={"fields": sorted(changes)},
        ip=auth.ip,
    )
    db.commit()
    db.refresh(entry)
    return entry_out(entry, meeting.target_language)


@router.put("/transcript-entries/{entry_id}/translation", response_model=TranslationOut)
def correct_translation(entry_id: uuid.UUID, body: TranslationUpdate, auth: Auth, db: DB) -> Translation:
    """User correction of a translation. Stored separately; the source text is untouched."""
    entry, meeting = _load_entry(db, auth, entry_id)
    tr = get_or_create_translation(db, entry, body.target_language)
    tr.text = body.text
    tr.status = TranslationStatus.done
    tr.is_user_edited = True
    tr.edited_by_id = auth.user.id
    tr.error_message = None
    record_audit(
        db,
        actor_id=auth.user.id,
        action="translation.edit",
        resource_type="translation",
        resource_id=tr.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()
    return tr


@router.post("/meetings/{meeting_id}/translations", response_model=JobOut, status_code=202)
def start_translation(meeting_id: uuid.UUID, body: TranslateIn, auth: TranslateAuth, db: DB) -> Job:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    count = db.scalar(select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id))
    if not count:
        raise Conflict("Import a transcript before translating")
    target = body.target_language or meeting.target_language
    job = job_service.enqueue(
        db,
        kind=JobKind.translation,
        user_id=auth.user.id,
        session_id=auth.session.id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        params={
            "target_language": target.value,
            "entry_ids": [str(i) for i in body.entry_ids or []],
            "only_failed": body.only_failed,
            "force": body.force,
        },
    )
    record_audit(
        db,
        actor_id=auth.user.id,
        action="translation.start",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"target": target.value, "selected": len(body.entry_ids or [])},
        ip=auth.ip,
    )
    db.commit()
    return job


# ---- Replay (DEMO) ------------------------------------------------------------


@router.post("/meetings/{meeting_id}/replay", response_model=LiveSessionOut, status_code=202)
def start_replay(
    meeting_id: uuid.UUID,
    auth: ReplayAuth,
    db: DB,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    interval_seconds: Annotated[float, Form(ge=0, le=10)] = 1.5,
    translate: Annotated[bool, Form()] = True,
) -> LiveSession:
    """Replay a transcript incrementally through the connector ingestion path.
    DEMO MODE: this is not a live meeting connection."""
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    existing = db.scalar(
        select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id)
    )
    if existing:
        raise Conflict("Replay requires a meeting without a transcript; create a new meeting for the demo")
    active = db.scalar(
        select(LiveSession).where(LiveSession.meeting_id == meeting.id, LiveSession.status == LiveSessionStatus.running)
    )
    if active:
        raise Conflict("A replay is already running for this meeting")
    if file is not None:
        parsed = parse_upload(data=_read_limited(file), text=None, filename=file.filename, declared_format=None)
    elif text:
        parsed = parse_upload(data=None, text=text, filename=None, declared_format=TranscriptFormat.text)
    else:
        raise ValidationFailed("Provide a file or text to replay")
    # Same canonical event model that real platform connectors emit (demo-flagged).
    events = [
        CanonicalEvent(
            provider="replay",
            provider_meeting_id=f"replay:{meeting.id}",
            entry_id=f"replay-{i}",
            is_demo=True,
            speaker_display_name=e.speaker,
            start_timestamp_ms=e.start_ms,
            end_timestamp_ms=e.end_ms,
            original_text=e.text,
            source_language=e.language,
            provider_sequence=i,
            source_metadata={k: v for k, v in e.metadata.items() if isinstance(v, (str, int, float, bool))},
        ).model_dump(mode="json")
        for i, e in enumerate(parsed.entries, start=1)
    ]
    live = LiveSession(
        id=uuid.uuid4(),
        meeting_id=meeting.id,
        connector="replay",
        is_demo=True,
        entries_total=len(events),
        created_by_id=auth.user.id,
    )
    db.add(live)
    db.flush()
    job = job_service.enqueue(
        db,
        kind=JobKind.replay,
        user_id=auth.user.id,
        session_id=auth.session.id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        params={
            "live_session_id": str(live.id),
            "events": events,
            "interval_seconds": interval_seconds,
            "translate": translate,
            "target_language": meeting.target_language.value,
        },
    )
    live.job_id = job.id
    meeting.detected_language = parsed.detected_language
    record_audit(
        db,
        actor_id=auth.user.id,
        action="replay.start",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"entries": len(events)},
        ip=auth.ip,
    )
    db.commit()
    return live


@router.post("/live-sessions/{session_id}/stop", response_model=LiveSessionOut)
def stop_replay(session_id: uuid.UUID, auth: Auth, db: DB) -> LiveSession:
    live = db.get(LiveSession, session_id)
    if live is None:
        raise NotFound("Live session not found")
    meeting, access = load_meeting(db, auth.user, live.meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    if live.connector == "audio_capture":
        from app.services.audio_capture import stop_session

        stop_session(db, live)  # also deletes voice references
    elif live.status == LiveSessionStatus.running:
        live.status = LiveSessionStatus.stopped
    db.commit()
    return live


@router.get("/meetings/{meeting_id}/live", response_model=LiveFeedOut)
def live_feed(
    meeting_id: uuid.UUID, auth: Auth, db: DB, after_sequence: Annotated[int, Query(ge=0)] = 0
) -> LiveFeedOut:
    """Polling endpoint for the live-style view (replay demo now, real connectors later)."""
    meeting, _ = load_meeting(db, auth.user, meeting_id, AccessLevel.transcript)
    live = db.scalar(
        select(LiveSession).where(LiveSession.meeting_id == meeting.id).order_by(LiveSession.started_at.desc()).limit(1)
    )
    entries = db.scalars(
        select(TranscriptEntry)
        .where(TranscriptEntry.meeting_id == meeting.id, TranscriptEntry.sequence > after_sequence)
        .order_by(TranscriptEntry.sequence)
        .limit(500)
    )
    return LiveFeedOut(
        session=LiveSessionOut.model_validate(live) if live else None,
        entries=[entry_out(e, meeting.target_language) for e in entries],
    )
