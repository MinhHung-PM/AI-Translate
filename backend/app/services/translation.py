"""Transcript translation pipeline.

* Entries are processed in sequence order, grouped by source language and
  split into bounded chunks (``TRANSLATION_CHUNK_MAX_ENTRIES`` /
  ``..._MAX_CHARS``) — a transcript is never sent in one unbounded request.
* The original text is never modified; translations are separate rows.
* User-corrected translations are never overwritten by the AI.
* A failed chunk marks only its own entries as failed (retryable).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.ai.base import (
    GlossaryTerm,
    ModelParams,
    ProviderError,
    ProviderErrorCode,
    TokenUsage,
    TranslationProvider,
    TranslationRequest,
    TranslationSegment,
)
from app.core.config import get_settings
from app.core.logging import log_event
from app.models import GlossaryEntry, Meeting, Project, TranscriptEntry, Translation
from app.models.enums import Language, TranslationStatus
from app.services.provider_config import ResolvedProvider, translation_provider
from app.services.transcripts.normalize import chunk_segments
from app.services.usage import DbUsageMeter, UsageContext

logger = logging.getLogger(__name__)

FATAL_CODES = {
    ProviderErrorCode.auth_failed,
    ProviderErrorCode.permission_denied,
    ProviderErrorCode.not_configured,
    ProviderErrorCode.quota_exceeded,
}


@dataclass
class TranslationOutcome:
    translated: int = 0
    failed: int = 0
    skipped: int = 0
    chunks: int = 0
    errors: list[str] = field(default_factory=list)


def glossary_for(db: Session, project_id: uuid.UUID, src: Language, tgt: Language) -> list[GlossaryEntry]:
    return list(
        db.scalars(
            select(GlossaryEntry).where(
                GlossaryEntry.project_id == project_id,
                GlossaryEntry.source_language == src,
                GlossaryEntry.target_language == tgt,
                GlossaryEntry.is_active.is_(True),
            )
        )
    )


def _relevant_terms(glossary: Sequence[GlossaryEntry], texts: Sequence[str]) -> list[GlossaryTerm]:
    joined = "\n".join(texts).lower()
    return [
        GlossaryTerm(source=g.source_term, target=g.preferred_translation, context=g.context)
        for g in glossary
        if g.source_term.lower() in joined
    ][:50]


def get_or_create_translation(db: Session, entry: TranscriptEntry, target: Language) -> Translation:
    tr = db.scalar(select(Translation).where(Translation.entry_id == entry.id, Translation.target_language == target))
    if tr is None:
        # A live capture and a "translate all" job may create the same row at once: let the
        # database pick one instead of failing on the unique constraint.
        db.execute(
            pg_insert(Translation)
            .values(id=uuid.uuid4(), entry_id=entry.id, target_language=target, status=TranslationStatus.pending)
            .on_conflict_do_nothing(constraint="uq_translation_entry_lang")
        )
        tr = db.scalars(
            select(Translation)
            .where(Translation.entry_id == entry.id, Translation.target_language == target)
            .execution_options(populate_existing=True)
        ).one()
    return tr


def translate_entries(
    db: Session,
    *,
    meeting: Meeting,
    project: Project,
    entries: Sequence[TranscriptEntry],
    target: Language,
    resolved: ResolvedProvider,
    user_id: uuid.UUID,
    job_id: uuid.UUID | None,
    force: bool = False,
    provider: TranslationProvider | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> TranslationOutcome:
    settings = get_settings()
    provider = provider or translation_provider(resolved, ModelParams(temperature=0.0, max_output_tokens=4000))
    meter = DbUsageMeter(db)
    outcome = TranslationOutcome()
    ctx = UsageContext(user_id, project.id, meeting.id, job_id, resolved.info.key, resolved.model, resolved.key_source)

    todo: list[tuple[TranscriptEntry, Translation]] = []
    for entry in entries:
        tr = get_or_create_translation(db, entry, target)
        if tr.is_user_edited or (tr.status == TranslationStatus.done and not force):
            outcome.skipped += 1
            continue
        src = entry.source_language or meeting.effective_source_language
        if src == target:
            # Same-language entries need no AI call; mirror the original text.
            tr.text, tr.status, tr.provider, tr.model, tr.error_message = (
                entry.original_text,
                TranslationStatus.done,
                "passthrough",
                None,
                None,
            )
            outcome.translated += 1
            continue
        tr.status = TranslationStatus.processing
        tr.job_id = job_id
        todo.append((entry, tr))
    db.commit()

    total = len(todo)
    done_count = 0
    by_lang: dict[Language | None, list[tuple[TranscriptEntry, Translation]]] = {}
    for pair in todo:
        by_lang.setdefault(pair[0].source_language or meeting.effective_source_language, []).append(pair)

    all_entries_by_seq = {e.sequence: e for e in entries}
    fatal: ProviderError | None = None
    for src_lang, pairs in by_lang.items():
        source_code = src_lang.value if src_lang else "auto"
        glossary = glossary_for(db, project.id, src_lang, target) if src_lang else []
        segments = [TranslationSegment(ref=e.sequence, text=e.original_text, speaker=e.speaker_label) for e, _ in pairs]
        tr_by_ref = {e.sequence: tr for e, tr in pairs}
        for chunk in chunk_segments(
            segments, settings.translation_chunk_max_entries, settings.translation_chunk_max_chars
        ):
            outcome.chunks += 1
            if fatal is not None:
                for seg in chunk:
                    _mark_failed(tr_by_ref[seg.ref], fatal)
                outcome.failed += len(chunk)
                continue
            first = chunk[0].ref
            context = [
                TranslationSegment(
                    ref=s, text=all_entries_by_seq[s].original_text, speaker=all_entries_by_seq[s].speaker_label
                )
                for s in (first - 2, first - 1)
                if s in all_entries_by_seq
            ]
            request = TranslationRequest(
                source_language=source_code,
                target_language=target.value,
                segments=chunk,
                context_before=context,
                glossary=_relevant_terms(glossary, [s.text for s in chunk]),
                instructions=project.translation_instructions,
            )
            started = time.monotonic()
            try:
                result = provider.translate(request)
            except ProviderError as err:
                duration = int((time.monotonic() - started) * 1000)
                meter.record(ctx, "translation", TokenUsage(), duration_ms=duration, success=False, error_code=err.code)
                for seg in chunk:
                    _mark_failed(tr_by_ref[seg.ref], err)
                outcome.failed += len(chunk)
                outcome.errors.append(err.message)
                if err.code in FATAL_CODES:
                    fatal = err
                db.commit()
                continue
            duration = int((time.monotonic() - started) * 1000)
            meter.record(
                ctx, "translation", result.usage, duration_ms=duration, success=True, retry_count=result.attempts - 1
            )
            for out in result.segments:
                tr = tr_by_ref[out.ref]
                # The AI call takes seconds: the user may have corrected this translation, or edited
                # the original text (which resets it to pending), meanwhile. Never overwrite either.
                db.refresh(tr, with_for_update=True)
                if tr.is_user_edited or tr.status != TranslationStatus.processing:
                    continue
                tr.text = out.text
                tr.ambiguity_note = out.ambiguity_note
                tr.status = TranslationStatus.done
                tr.error_message = None
                tr.provider = provider.provider_key
                tr.model = result.model
            outcome.translated += len(result.segments)
            done_count += len(chunk)
            if on_progress:
                on_progress(done_count, total)
            db.commit()
    log_event(
        logger,
        "translation.completed",
        meeting_id=str(meeting.id),
        translated=outcome.translated,
        failed=outcome.failed,
        skipped=outcome.skipped,
        chunks=outcome.chunks,
        provider=resolved.info.key,
    )
    return outcome


def _mark_failed(tr: Translation, err: ProviderError) -> None:
    tr.status = TranslationStatus.failed
    tr.error_message = err.message[:500]
