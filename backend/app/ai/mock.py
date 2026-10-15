"""Deterministic mock provider for development, demos and automated tests.

It does not call any external service. Translation output is clearly marked
``[MOCK ja→vi]`` so it can never be mistaken for a real translation. Memo
generation uses keyword heuristics and emits JSON that goes through exactly
the same validation pipeline as real model output.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.base import (
    MemoGenerationResult,
    MemoRequest,
    TokenUsage,
    TranslatedSegment,
    TranslationRequest,
    TranslationResult,
    estimate_tokens,
)
from app.services.date_resolution import extract_due_phrase

MOCK_MODEL = "mock-deterministic"

_DECISION = re.compile(
    r"決定|決まり|合意|確定|承認します|decided|agreed|we will go with|approved|quyết định|thống nhất|chốt", re.I
)
_ACTION = re.compile(
    r"お願いします|対応します|担当します|確認します|します。|\bwill\b|\bI'll\b|action item|\bsẽ\b|phụ trách|nhờ", re.I
)
_ISSUE = re.compile(r"問題|課題|不具合|バグ|\bissue\b|\bproblem\b|\bbug\b|vấn đề|\blỗi\b", re.I)
_RISK = re.compile(r"リスク|遅延|遅れ|懸念|\brisk\b|\bdelay|concern|rủi ro|chậm|lo ngại", re.I)
_QUESTION = re.compile(r"[?？]\s*$|ですか。?$|でしょうか。?$")
_PROPOSAL = re.compile(
    r"を提案|提案します|どうでしょう|しませんか|propose|suggest|maybe|how about|đề xuất|có nên", re.I
)


def _mentioned_owner(text: str, participants: list[str]) -> str | None:
    """Owner only when a participant's name appears in the sentence with an
    assignment marker. The speaker is never assumed to be the owner."""
    for name in participants:
        short = name.split()[0] if name else name
        for candidate in {name, short}:
            if not candidate or len(candidate) < 2:
                continue
            patterns = [
                rf"{re.escape(candidate)}\s*(さん|様)?\s*(が|に|、)",
                rf"{re.escape(candidate)}\s+(will|to|is going to)\b",
                rf"(anh|chị|bạn|em)\s+{re.escape(candidate)}\s+(sẽ|phụ trách)",
                rf"{re.escape(candidate)}\s+(sẽ|phụ trách)",
            ]
            if any(re.search(p, text, re.I) for p in patterns):
                return name
    return None


class MockProvider:
    key = "mock"

    def __init__(self, model: str = MOCK_MODEL) -> None:
        self.provider_key = "mock"
        self.model = model

    # AIProvider-style connectivity (no network involved)
    def test_connection_ok(self) -> tuple[bool, str]:
        return True, "Mock provider is always available (no external calls)"

    def translate(self, request: TranslationRequest) -> TranslationResult:
        tag = f"[MOCK {request.source_language}→{request.target_language}]"
        out: list[TranslatedSegment] = []
        usage = TokenUsage(reported_by_provider=False)
        for seg in request.segments:
            text = seg.text
            for term in request.glossary:
                text = text.replace(term.source, term.target)
            note = "Đoạn này có thể chưa hoàn chỉnh" if text.rstrip().endswith(("…", "...", "、")) else None
            out.append(TranslatedSegment(ref=seg.ref, text=f"{tag} {text}", ambiguity_note=note))
            usage.input_tokens += estimate_tokens(seg.text)
            usage.output_tokens += estimate_tokens(text)
        return TranslationResult(segments=out, usage=usage, model=self.model)

    def generate(self, request: MemoRequest, *, repair_hint: str | None = None) -> MemoGenerationResult:
        decisions: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []
        discussion_points: list[str] = []
        discussion_refs: list[int] = []

        for line in request.lines:
            text = line.text.strip()
            if not text:
                continue
            ref = [line.ref]
            if _QUESTION.search(text):
                questions.append({"question": text, "source_refs": ref})
                continue
            if _DECISION.search(text) and not _PROPOSAL.search(text):
                decisions.append(
                    {
                        "statement": text,
                        "owner": None,
                        "source_refs": ref,
                        "confidence": "medium",
                        "needs_review": False,
                        "review_reason": None,
                    }
                )
            elif _ISSUE.search(text):
                issues.append(
                    {
                        "description": text,
                        "impact": None,
                        "owner": _mentioned_owner(text, request.participants),
                        "status": "open",
                        "follow_up": None,
                        "priority": "medium",
                        "source_refs": ref,
                        "confidence": "medium",
                        "needs_review": False,
                    }
                )
            elif _RISK.search(text):
                risks.append(
                    {
                        "description": text,
                        "probability": "unknown",
                        "impact": None,
                        "severity": "medium",
                        "mitigation": None,
                        "owner": None,
                        "source_refs": ref,
                        "confidence": "low",
                        "needs_review": True,
                    }
                )
            if _ACTION.search(text) and not _QUESTION.search(text):
                owner = _mentioned_owner(text, request.participants)
                actions.append(
                    {
                        "description": text,
                        "owner": owner,
                        "due_text": extract_due_phrase(text),
                        "priority": "medium",
                        "kind": "confirmed" if owner else "suggested",
                        "related_decision_index": None,
                        "source_refs": ref,
                        "confidence": "medium" if owner else "low",
                        "needs_review": owner is None,
                        "review_reason": None if owner else "No explicit owner stated",
                    }
                )
            elif _PROPOSAL.search(text):
                discussion_points.append(text)
                discussion_refs.append(line.ref)

        if not discussion_points:
            discussion_points = [line.text for line in request.lines[:3]]
            discussion_refs = [line.ref for line in request.lines[:3]]

        summary = (
            f"[MOCK] {request.meeting_title}: {len(request.lines)} transcript lines, "
            f"{len(decisions)} decisions, {len(actions)} action items, {len(issues)} issues, "
            f"{len(risks)} risks identified by keyword heuristics. Review every item."
        )
        payload = {
            "executive_summary": summary,
            "discussion": [
                {"topic": "[MOCK] Discussion", "points": discussion_points[:10], "source_refs": discussion_refs[:10]}
            ],
            "decisions": decisions,
            "action_items": actions,
            "issues": issues,
            "risks": risks,
            "open_questions": questions,
            "next_meeting": None,
            "pm_view": {
                "schedule": {
                    "assessment": "[MOCK] Schedule risk flagged" if risks else "[MOCK] No schedule signal",
                    "basis": "evidence" if risks else "ai_suggestion",
                    "source_refs": risks[0]["source_refs"] if risks else [],
                },
                "scope": None,
                "quality": None,
                "cost": None,
                "customer_satisfaction": None,
                "escalation": None,
            },
        }
        raw = json.dumps(payload, ensure_ascii=False)
        usage = TokenUsage(
            input_tokens=sum(estimate_tokens(line.text) for line in request.lines),
            output_tokens=estimate_tokens(raw),
            reported_by_provider=False,
        )
        return MemoGenerationResult(raw_json=raw, usage=usage, model=self.model)
