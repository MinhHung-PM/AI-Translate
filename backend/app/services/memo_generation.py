"""AI memo generation: request building, bounded retry on malformed output,
grounding checks, and persistence as a *draft* (never auto-approved).

Grounding rules applied after schema validation (provider-independent):

* An owner is kept only if the name literally appears in the cited
  transcript lines. If it only matches the speaker of a cited line (a
  self-commitment such as "I'll do it"), it is kept but flagged for review.
  Otherwise it is removed and the item is flagged.
* ``due_text`` must appear in a cited line; it is resolved to a date only by
  ``date_resolution.resolve_due`` (deterministic, conservative).
* "suggested" action items and anything the model marked as uncertain start
  as ``needs_review``; everything else starts as ``draft``. Only a human can
  set ``confirmed``.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.base import (
    GlossaryTerm,
    MemoGenerationProvider,
    MemoRequest,
    MemoTranscriptLine,
    ModelParams,
    ProviderError,
    TokenUsage,
)
from app.ai.memo_schema import MemoDraft, MemoOutputInvalid, validate_memo_draft
from app.ai.prompts.memo import MEMO_PROMPT_VERSION
from app.core.config import get_settings
from app.core.logging import log_event
from app.db.base import utcnow
from app.models import (
    ActionItem,
    Decision,
    Issue,
    Meeting,
    Memo,
    MemoItemSource,
    Project,
    Risk,
    TranscriptEntry,
)
from app.models.enums import MeetingStatus, MemoStatus, VerificationStatus
from app.services.date_resolution import resolve_due
from app.services.provider_config import ResolvedProvider, memo_provider
from app.services.translation import glossary_for
from app.services.usage import DbUsageMeter, UsageContext

logger = logging.getLogger(__name__)

MEMO_PARAMS = ModelParams(temperature=0.1, max_output_tokens=8000, seed=7)


class MemoGenerationFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


@dataclass
class Grounding:
    entries_by_seq: dict[int, TranscriptEntry]

    def texts(self, refs: list[int]) -> str:
        return _norm(" ".join(self.entries_by_seq[r].original_text for r in refs))

    def speakers(self, refs: list[int]) -> set[str]:
        return {_norm(self.entries_by_seq[r].speaker_label or "") for r in refs} - {""}

    def check_owner(self, owner: str | None, refs: list[int]) -> tuple[str | None, str | None]:
        """Returns (owner_to_keep, review_note)."""
        if not owner:
            return None, None
        n = _norm(owner)
        first = _norm(owner.split()[0]) if owner.split() else n
        texts = self.texts(refs)
        if n in texts or (len(first) >= 2 and first in texts):
            return owner, None
        if n in self.speakers(refs):
            return owner, "Owner inferred from the speaker's own commitment; please confirm"
        return None, f"AI-proposed owner '{owner[:60]}' is not stated in the cited lines and was removed"


def build_request(db: Session, meeting: Meeting, project: Project, entries: list[TranscriptEntry]) -> MemoRequest:
    participants = [p.display_name for p in meeting.participants]
    for e in entries:
        if e.speaker_label and e.speaker_label not in participants:
            participants.append(e.speaker_label)
    src = meeting.effective_source_language
    glossary = []
    if src and src != meeting.memo_language:
        glossary = glossary_for(db, project.id, src, meeting.memo_language)[:100]
    return MemoRequest(
        meeting_title=meeting.title,
        project_name=project.name,
        meeting_date_iso=meeting.scheduled_at.isoformat(),
        timezone=meeting.timezone,
        participants=participants[:100],
        objective=meeting.objective,
        memo_language=meeting.memo_language.value,
        source_language=src.value if src else None,
        lines=[
            MemoTranscriptLine(ref=e.sequence, text=e.original_text, speaker=e.speaker_label, start_ms=e.start_ms)
            for e in entries
        ],
        custom_instructions=meeting.custom_instructions,
        glossary=[GlossaryTerm(source=g.source_term, target=g.preferred_translation) for g in glossary],
    )


def generate_validated(
    provider: MemoGenerationProvider, request: MemoRequest, max_attempts: int
) -> tuple[MemoDraft, TokenUsage, str, int]:
    """Call the provider until output validates, at most ``max_attempts`` times.
    Raises MemoGenerationFailed — never returns fabricated content."""
    valid_refs = {line.ref for line in request.lines}
    usage = TokenUsage(reported_by_provider=True)
    hint: str | None = None
    model = provider.model
    for attempt in range(1, max_attempts + 1):
        try:
            result = provider.generate(request, repair_hint=hint)
        except ProviderError as err:
            raise MemoGenerationFailed(err.code, err.message) from err
        usage.add(result.usage)
        model = result.model
        try:
            return validate_memo_draft(result.raw_json, valid_refs), usage, model, attempt
        except MemoOutputInvalid as exc:
            hint = exc.reason
            log_event(logger, "memo.output_invalid", attempt=attempt, reason=exc.reason[:200])
    raise MemoGenerationFailed(
        "invalid_output", f"The AI returned invalid memo output after {max_attempts} attempts: {hint}"
    )


def _verification(needs_review: bool) -> VerificationStatus:
    return VerificationStatus.needs_review if needs_review else VerificationStatus.draft


def _join_notes(*notes: str | None) -> str | None:
    kept = [n for n in notes if n]
    return " | ".join(kept) if kept else None


def persist_draft(db: Session, memo: Memo, meeting: Meeting, draft: MemoDraft, entries: list[TranscriptEntry]) -> None:
    by_seq = {e.sequence: e for e in entries}
    g = Grounding(by_seq)

    def ids(refs: list[int]) -> list[str]:
        return [str(by_seq[r].id) for r in refs]

    for model_cls in (ActionItem, Decision, Issue, Risk):
        db.execute(delete(model_cls).where(model_cls.memo_id == memo.id))

    memo.executive_summary = draft.executive_summary
    memo.discussion = [
        {"topic": t.topic, "points": t.points, "source_entry_ids": ids(t.source_refs)} for t in draft.discussion
    ]
    memo.open_questions = [
        {"question": q.question, "source_entry_ids": ids(q.source_refs)} for q in draft.open_questions
    ]
    memo.next_meeting = (
        {
            "when_text": draft.next_meeting.when_text,
            "agenda": draft.next_meeting.agenda,
            "source_entry_ids": ids(draft.next_meeting.source_refs),
        }
        if draft.next_meeting
        else None
    )
    pm: dict[str, Any] | None = None
    if draft.pm_view:
        pm = {}
        for key, val in draft.pm_view.__dict__.items():
            if val is None:
                pm[key] = None
                continue
            basis = val.basis if val.source_refs else "ai_suggestion"  # evidence must cite lines
            pm[key] = {"assessment": val.assessment, "basis": basis, "source_entry_ids": ids(val.source_refs)}
    memo.pm_view = pm

    common = {"memo_id": memo.id, "meeting_id": meeting.id, "project_id": meeting.project_id, "ai_generated": True}

    decisions: list[Decision] = []
    for i, d in enumerate(draft.decisions, start=1):
        owner, note = g.check_owner(d.owner, d.source_refs)
        row = Decision(
            id=uuid.uuid4(),
            code=f"D-{i}",
            statement=d.statement,
            owner_text=owner,
            confidence=d.confidence,
            verification_status=_verification(d.needs_review or note is not None),
            review_note=_join_notes(d.review_reason, note),
            sort_order=i,
            **common,
        )
        row.source_links = [MemoItemSource(transcript_entry_id=by_seq[r].id) for r in dict.fromkeys(d.source_refs)]
        decisions.append(row)
        db.add(row)
    # Action items may reference these decisions (related_decision_id) and there is no ORM
    # relationship to order the INSERTs: write the decisions first.
    db.flush()

    for i, it in enumerate(draft.issues, start=1):
        owner, note = g.check_owner(it.owner, it.source_refs)
        issue = Issue(
            id=uuid.uuid4(),
            code=f"I-{i}",
            description=it.description,
            impact=it.impact,
            owner_text=owner,
            status=it.status,
            follow_up=it.follow_up,
            priority=it.priority,
            confidence=it.confidence,
            verification_status=_verification(it.needs_review or note is not None),
            review_note=note,
            sort_order=i,
            **common,
        )
        issue.source_links = [MemoItemSource(transcript_entry_id=by_seq[r].id) for r in dict.fromkeys(it.source_refs)]
        db.add(issue)

    for i, rk in enumerate(draft.risks, start=1):
        owner, note = g.check_owner(rk.owner, rk.source_refs)
        risk = Risk(
            id=uuid.uuid4(),
            code=f"R-{i}",
            description=rk.description,
            probability=rk.probability,
            impact=rk.impact,
            severity=rk.severity,
            mitigation=rk.mitigation,
            owner_text=owner,
            confidence=rk.confidence,
            verification_status=_verification(rk.needs_review or note is not None),
            review_note=note,
            sort_order=i,
            **common,
        )
        risk.source_links = [MemoItemSource(transcript_entry_id=by_seq[r].id) for r in dict.fromkeys(rk.source_refs)]
        db.add(risk)

    for i, a in enumerate(draft.action_items, start=1):
        owner, owner_note = g.check_owner(a.owner, a.source_refs)
        due_text = a.due_text
        due_note: str | None = None
        due_date = None
        due_flag = False
        if due_text:
            if _norm(due_text) not in g.texts(a.source_refs):
                due_note = f"Deadline '{due_text[:60]}' not found in cited lines; please confirm"
                due_flag = True
            else:
                res = resolve_due(due_text, meeting.scheduled_at, meeting.timezone)
                due_date, due_flag = res.due_date, res.needs_confirmation
                if res.needs_confirmation:
                    due_note = f"Deadline needs confirmation: {res.reason}"
        suggested_note = (
            "AI-suggested follow-up; not explicitly agreed in the meeting" if a.kind == "suggested" else None
        )
        needs_review = a.needs_review or a.kind == "suggested" or owner_note is not None or due_flag
        action = ActionItem(
            id=uuid.uuid4(),
            code=f"A-{i}",
            description=a.description,
            owner_text=owner,
            due_text=due_text,
            due_date=due_date,
            due_needs_confirmation=due_flag,
            priority=a.priority,
            confidence=a.confidence,
            verification_status=_verification(needs_review),
            review_note=_join_notes(a.review_reason, suggested_note, owner_note, due_note),
            related_decision_id=decisions[a.related_decision_index].id
            if a.related_decision_index is not None
            else None,
            sort_order=i,
            **common,
        )
        action.source_links = [MemoItemSource(transcript_entry_id=by_seq[r].id) for r in dict.fromkeys(a.source_refs)]
        db.add(action)


def run_memo_generation(
    db: Session,
    *,
    memo: Memo,
    meeting: Meeting,
    project: Project,
    resolved: ResolvedProvider,
    user_id: uuid.UUID,
    job_id: uuid.UUID | None,
    provider: MemoGenerationProvider | None = None,
) -> Memo:
    settings = get_settings()
    entries = list(
        db.scalars(
            select(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id).order_by(TranscriptEntry.sequence)
        )
    )
    ctx = UsageContext(user_id, project.id, meeting.id, job_id, resolved.info.key, resolved.model, resolved.key_source)
    meter = DbUsageMeter(db)
    try:
        if not entries:
            raise MemoGenerationFailed("no_transcript", "The meeting has no transcript entries")
        total_chars = sum(len(e.original_text) for e in entries)
        if total_chars > settings.memo_max_transcript_chars:
            raise MemoGenerationFailed(
                "transcript_too_long",
                f"Transcript is {total_chars} characters; the single-pass memo limit is "
                f"{settings.memo_max_transcript_chars}. Split the meeting or raise MEMO_MAX_TRANSCRIPT_CHARS.",
            )
        provider = provider or memo_provider(resolved, MEMO_PARAMS)
        request = build_request(db, meeting, project, entries)
        started = time.monotonic()
        try:
            draft, usage, model, attempts = generate_validated(provider, request, settings.ai_output_max_attempts)
        except MemoGenerationFailed as exc:
            meter.record(
                ctx,
                "memo_generation",
                TokenUsage(),
                duration_ms=int((time.monotonic() - started) * 1000),
                success=False,
                retry_count=settings.ai_output_max_attempts - 1,
                error_code=exc.code,
            )
            raise
        meter.record(
            ctx,
            "memo_generation",
            usage,
            duration_ms=int((time.monotonic() - started) * 1000),
            success=True,
            retry_count=attempts - 1,
        )
    except MemoGenerationFailed as exc:
        memo.status = MemoStatus.failed
        memo.generation_error = exc.message[:500]
        db.commit()
        raise

    persist_draft(db, memo, meeting, draft, entries)
    memo.status = MemoStatus.draft
    memo.generation_error = None
    memo.prompt_version = MEMO_PROMPT_VERSION
    memo.provider = resolved.info.key
    memo.model = model
    memo.generation_params = {
        "temperature": MEMO_PARAMS.temperature,
        "seed": MEMO_PARAMS.seed,
        "max_output_tokens": MEMO_PARAMS.max_output_tokens,
        "attempts": attempts,
    }
    memo.generated_at = utcnow()
    memo.generation_count += 1
    memo.reviewed_by_id = None
    memo.reviewed_at = None
    meeting.status = MeetingStatus.memo_draft
    db.commit()
    log_event(
        logger,
        "memo.generated",
        meeting_id=str(meeting.id),
        decisions=len(draft.decisions),
        actions=len(draft.action_items),
        attempts=attempts,
        provider=resolved.info.key,
    )
    return memo
