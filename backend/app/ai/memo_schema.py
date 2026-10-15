"""Strict schema for AI memo output (the contract every provider must meet).

``source_refs`` are transcript sequence numbers shown to the model as
``[#n]``. ``validate_memo_draft`` rejects references to unknown entries so
that extracted items always trace back to real transcript lines.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models.enums import Confidence, IssueStatus, Likelihood, Priority


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _clean_optional(value: object) -> object:
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "unknown", "不明", "未定"}:
        return None
    return value


class DiscussionTopic(_Strict):
    topic: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(default_factory=list, max_length=30)
    source_refs: list[int] = Field(default_factory=list)


class DecisionDraft(_Strict):
    statement: str = Field(min_length=1, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    source_refs: list[int] = Field(min_length=1)
    confidence: Confidence = Confidence.medium
    needs_review: bool = False
    review_reason: str | None = Field(default=None, max_length=500)

    _clean_owner = field_validator("owner", mode="before")(_clean_optional)


class ActionItemDraft(_Strict):
    description: str = Field(min_length=1, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    due_text: str | None = Field(default=None, max_length=200)
    priority: Priority = Priority.medium
    # "confirmed": explicitly agreed in the meeting; "suggested": AI-proposed follow-up.
    kind: Literal["confirmed", "suggested"] = "confirmed"
    related_decision_index: int | None = Field(default=None, ge=0)
    source_refs: list[int] = Field(min_length=1)
    confidence: Confidence = Confidence.medium
    needs_review: bool = False
    review_reason: str | None = Field(default=None, max_length=500)

    _clean = field_validator("owner", "due_text", mode="before")(_clean_optional)


class IssueDraft(_Strict):
    description: str = Field(min_length=1, max_length=2000)
    impact: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=200)
    status: IssueStatus = IssueStatus.open
    follow_up: str | None = Field(default=None, max_length=1000)
    priority: Priority = Priority.medium
    source_refs: list[int] = Field(min_length=1)
    confidence: Confidence = Confidence.medium
    needs_review: bool = False

    _clean = field_validator("owner", mode="before")(_clean_optional)


class RiskDraft(_Strict):
    description: str = Field(min_length=1, max_length=2000)
    probability: Likelihood = Likelihood.unknown
    impact: str | None = Field(default=None, max_length=1000)
    severity: Priority = Priority.medium
    mitigation: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=200)
    source_refs: list[int] = Field(min_length=1)
    confidence: Confidence = Confidence.medium
    needs_review: bool = False

    _clean = field_validator("owner", mode="before")(_clean_optional)


class OpenQuestion(_Strict):
    question: str = Field(min_length=1, max_length=1000)
    source_refs: list[int] = Field(default_factory=list)


class NextMeeting(_Strict):
    when_text: str | None = Field(default=None, max_length=200)
    agenda: list[str] = Field(default_factory=list, max_length=20)
    source_refs: list[int] = Field(default_factory=list)


class PMAssessment(_Strict):
    assessment: str = Field(min_length=1, max_length=1000)
    # "evidence": grounded in cited transcript lines; "ai_suggestion": inference.
    basis: Literal["evidence", "ai_suggestion"]
    source_refs: list[int] = Field(default_factory=list)


class PMView(_Strict):
    schedule: PMAssessment | None = None
    scope: PMAssessment | None = None
    quality: PMAssessment | None = None
    cost: PMAssessment | None = None
    customer_satisfaction: PMAssessment | None = None
    escalation: PMAssessment | None = None


class MemoDraft(_Strict):
    executive_summary: str = Field(min_length=1, max_length=5000)
    discussion: list[DiscussionTopic] = Field(default_factory=list, max_length=50)
    decisions: list[DecisionDraft] = Field(default_factory=list, max_length=100)
    action_items: list[ActionItemDraft] = Field(default_factory=list, max_length=200)
    issues: list[IssueDraft] = Field(default_factory=list, max_length=100)
    risks: list[RiskDraft] = Field(default_factory=list, max_length=100)
    open_questions: list[OpenQuestion] = Field(default_factory=list, max_length=100)
    next_meeting: NextMeeting | None = None
    pm_view: PMView | None = None


class MemoOutputInvalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _all_refs(draft: MemoDraft) -> list[int]:
    refs: list[int] = []
    for group in (
        draft.discussion,
        draft.decisions,
        draft.action_items,
        draft.issues,
        draft.risks,
        draft.open_questions,
    ):
        for item in group:
            refs.extend(item.source_refs)
    if draft.next_meeting:
        refs.extend(draft.next_meeting.source_refs)
    if draft.pm_view:
        for assessment in draft.pm_view.__dict__.values():
            if assessment is not None:
                refs.extend(assessment.source_refs)
    return refs


def strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def validate_memo_draft(raw: str, valid_refs: set[int]) -> MemoDraft:
    try:
        data = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise MemoOutputInvalid(f"Output is not valid JSON: {exc.msg}") from exc
    try:
        draft = MemoDraft.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[:5]
        summary = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in first)
        raise MemoOutputInvalid(f"Schema validation failed: {summary}") from exc
    unknown = sorted({r for r in _all_refs(draft) if r not in valid_refs})
    if unknown:
        raise MemoOutputInvalid(f"Unknown source_refs (not in transcript): {unknown[:10]}")
    for idx, action in enumerate(draft.action_items):
        if action.related_decision_index is not None and action.related_decision_index >= len(draft.decisions):
            raise MemoOutputInvalid(f"action_items[{idx}].related_decision_index out of range")
    return draft


MEMO_JSON_SHAPE = """{
  "executive_summary": string,
  "discussion": [{"topic": string, "points": [string], "source_refs": [int]}],
  "decisions": [{"statement": string, "owner": string|null, "source_refs": [int, ...>=1],
                 "confidence": "high"|"medium"|"low", "needs_review": bool, "review_reason": string|null}],
  "action_items": [{"description": string, "owner": string|null, "due_text": string|null,
                    "priority": "low"|"medium"|"high"|"critical", "kind": "confirmed"|"suggested",
                    "related_decision_index": int|null, "source_refs": [int, ...>=1],
                    "confidence": "high"|"medium"|"low", "needs_review": bool, "review_reason": string|null}],
  "issues": [{"description": string, "impact": string|null, "owner": string|null,
              "status": "open"|"monitoring"|"resolved", "follow_up": string|null,
              "priority": "low"|"medium"|"high"|"critical", "source_refs": [int, ...>=1],
              "confidence": "high"|"medium"|"low", "needs_review": bool}],
  "risks": [{"description": string, "probability": "low"|"medium"|"high"|"unknown", "impact": string|null,
             "severity": "low"|"medium"|"high"|"critical", "mitigation": string|null, "owner": string|null,
             "source_refs": [int, ...>=1], "confidence": "high"|"medium"|"low", "needs_review": bool}],
  "open_questions": [{"question": string, "source_refs": [int]}],
  "next_meeting": {"when_text": string|null, "agenda": [string], "source_refs": [int]} | null,
  "pm_view": {"schedule"|"scope"|"quality"|"cost"|"customer_satisfaction"|"escalation":
              {"assessment": string, "basis": "evidence"|"ai_suggestion", "source_refs": [int]} | null} | null
}"""
