"""Exports. All user/AI text is escaped for the target format (HTML-escaped
in HTML; CSV cells are protected against spreadsheet formula injection)."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Meeting, Project, TranscriptEntry, Translation
from app.schemas.api import MemoOut

LABELS = {
    "vi": {
        "info": "Thông tin cuộc họp",
        "title": "Tiêu đề",
        "project": "Dự án",
        "date": "Thời gian",
        "participants": "Thành phần tham dự",
        "objective": "Mục tiêu",
        "source_lang": "Ngôn ngữ gốc",
        "memo_lang": "Ngôn ngữ biên bản",
        "summary": "Tóm tắt",
        "discussion": "Nội dung thảo luận",
        "decisions": "Quyết định",
        "actions": "Công việc cần làm",
        "issues": "Vấn đề",
        "risks": "Rủi ro",
        "questions": "Câu hỏi còn mở",
        "next": "Cuộc họp tiếp theo",
        "pm": "Góc nhìn quản lý dự án",
        "owner": "Phụ trách",
        "due": "Hạn",
        "priority": "Ưu tiên",
        "status": "Trạng thái",
        "verification": "Xác minh",
        "source": "Nguồn",
        "impact": "Ảnh hưởng",
        "mitigation": "Biện pháp",
        "probability": "Khả năng",
        "follow_up": "Theo dõi",
        "approved": "Đã phê duyệt",
        "ai_note": "Biên bản được tạo với sự hỗ trợ của AI và đã được con người xem xét.",
        "evidence": "dựa trên bằng chứng",
        "ai_suggestion": "gợi ý của AI",
        "human": "do người dùng nhập",
        "none": "—",
    },
    "en": {
        "info": "Meeting information",
        "title": "Title",
        "project": "Project",
        "date": "Date",
        "participants": "Participants",
        "objective": "Objective",
        "source_lang": "Source language",
        "memo_lang": "Memo language",
        "summary": "Executive summary",
        "discussion": "Discussion",
        "decisions": "Decisions",
        "actions": "Action items",
        "issues": "Issues",
        "risks": "Risks",
        "questions": "Open questions",
        "next": "Next meeting",
        "pm": "Project management view",
        "owner": "Owner",
        "due": "Due",
        "priority": "Priority",
        "status": "Status",
        "verification": "Verification",
        "source": "Source",
        "impact": "Impact",
        "mitigation": "Mitigation",
        "probability": "Probability",
        "follow_up": "Follow-up",
        "approved": "Approved",
        "ai_note": "These minutes were drafted with AI assistance and reviewed by a person.",
        "evidence": "evidence-based",
        "ai_suggestion": "AI suggestion",
        "human": "entered by user",
        "none": "—",
    },
    "ja": {
        "info": "会議情報",
        "title": "件名",
        "project": "プロジェクト",
        "date": "日時",
        "participants": "参加者",
        "objective": "目的",
        "source_lang": "原語",
        "memo_lang": "議事録の言語",
        "summary": "要約",
        "discussion": "議論内容",
        "decisions": "決定事項",
        "actions": "アクションアイテム",
        "issues": "課題",
        "risks": "リスク",
        "questions": "未解決の質問",
        "next": "次回会議",
        "pm": "PM観点",
        "owner": "担当",
        "due": "期限",
        "priority": "優先度",
        "status": "状態",
        "verification": "確認状況",
        "source": "出典",
        "impact": "影響",
        "mitigation": "対策",
        "probability": "発生可能性",
        "follow_up": "フォローアップ",
        "approved": "承認済み",
        "ai_note": "本議事録はAIの支援により作成され、担当者が確認しました。",
        "evidence": "根拠あり",
        "ai_suggestion": "AIによる提案",
        "human": "ユーザー入力",
        "none": "—",
    },
}

PM_KEYS = ["schedule", "scope", "quality", "cost", "customer_satisfaction", "escalation"]


def _refs(sources: list[Any]) -> str:
    return ", ".join(f"#{s.sequence}" for s in sources) or "—"


def memo_to_markdown(memo: MemoOut) -> str:
    L = LABELS.get(memo.language.value, LABELS["en"])
    info = memo.meeting_info
    lines = [
        f"# {info.title}",
        "",
        f"_{L['approved']}: {memo.reviewed_at:%Y-%m-%d %H:%M} UTC_" if memo.reviewed_at else "",
        "",
        f"## A. {L['info']}",
        "",
        f"- **{L['project']}**: {info.project_name}",
        f"- **{L['date']}**: {info.scheduled_at:%Y-%m-%d %H:%M} ({info.timezone})",
        f"- **{L['participants']}**: {', '.join(info.participants) or L['none']}",
        f"- **{L['objective']}**: {info.objective or L['none']}",
        f"- **{L['source_lang']}**: {info.source_language.value if info.source_language else L['none']}",
        f"- **{L['memo_lang']}**: {memo.language.value}",
        "",
        f"## B. {L['summary']}",
        "",
        memo.executive_summary or L["none"],
        "",
        f"## C. {L['discussion']}",
        "",
    ]
    for topic in memo.discussion:
        lines.append(f"### {topic.get('topic', '')}")
        lines.extend(f"- {p}" for p in topic.get("points", []))
        lines.append("")
    lines += [f"## D. {L['decisions']}", ""]
    for d in memo.decisions:
        lines.append(
            f"- **{d.code}** {d.statement} — {L['owner']}: {d.owner_text or L['none']}; "
            f"{L['verification']}: {d.verification_status.value}; {L['source']}: {_refs(d.sources)}"
        )
    lines += [
        "",
        f"## E. {L['actions']}",
        "",
        f"| ID | {L['actions']} | {L['owner']} | {L['due']} | {L['priority']} | {L['status']} | "
        f"{L['verification']} | {L['source']} |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in memo.action_items:
        due = a.due_date.isoformat() if a.due_date else (a.due_text or L["none"])
        cells = [
            a.code,
            a.description,
            a.owner_text or L["none"],
            due,
            a.priority.value,
            a.status.value,
            a.verification_status.value,
            _refs(a.sources),
        ]
        lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    lines += ["", f"## F. {L['issues']}", ""]
    for i in memo.issues:
        lines.append(
            f"- **{i.code}** {i.description} — {L['impact']}: {i.impact or L['none']}; "
            f"{L['owner']}: {i.owner_text or L['none']}; {L['status']}: {i.status.value}; "
            f"{L['follow_up']}: {i.follow_up or L['none']}; {L['source']}: {_refs(i.sources)}"
        )
    lines += ["", f"## G. {L['risks']}", ""]
    for r in memo.risks:
        lines.append(
            f"- **{r.code}** {r.description} — {L['probability']}: {r.probability.value}; "
            f"{L['impact']}: {r.impact or L['none']}; {L['mitigation']}: {r.mitigation or L['none']}; "
            f"{L['owner']}: {r.owner_text or L['none']}; {L['verification']}: {r.verification_status.value}; "
            f"{L['source']}: {_refs(r.sources)}"
        )
    lines += ["", f"## H. {L['questions']}", ""]
    lines.extend(f"- {q.get('question', '')}" for q in memo.open_questions)
    lines += ["", f"## I. {L['next']}", ""]
    nm = memo.next_meeting
    if nm:
        lines.append(f"- {nm.get('when_text') or L['none']}")
        lines.extend(f"  - {item}" for item in nm.get("agenda", []))
    else:
        lines.append(L["none"])
    lines += ["", f"## J. {L['pm']}", ""]
    for key in PM_KEYS:
        val = (memo.pm_view or {}).get(key)
        if val:
            lines.append(f"- **{key}**: {val['assessment']} _({L.get(val['basis'], val['basis'])})_")
    lines += [
        "",
        "---",
        f"_{L['ai_note']}_ (prompt {memo.prompt_version or '-'}, {memo.provider or '-'}/{memo.model or '-'})",
        "",
    ]
    return "\n".join(lines)


def memo_to_html(memo: MemoOut) -> str:
    L = LABELS.get(memo.language.value, LABELS["en"])
    e = html.escape
    info = memo.meeting_info

    def section(title: str, body: str) -> str:
        return f"<section><h2>{e(title)}</h2>{body}</section>"

    def table(headers: list[str], rows: list[list[str]]) -> str:
        head = "".join(f"<th>{e(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    parts = [
        section(
            "A. " + L["info"],
            table(
                ["", ""],
                [
                    [L["project"], info.project_name],
                    [L["date"], f"{info.scheduled_at:%Y-%m-%d %H:%M} ({info.timezone})"],
                    [L["participants"], ", ".join(info.participants) or L["none"]],
                    [L["objective"], info.objective or L["none"]],
                    [L["source_lang"], info.source_language.value if info.source_language else L["none"]],
                    [L["memo_lang"], memo.language.value],
                ],
            ),
        ),
        section(
            "B. " + L["summary"], "".join(f"<p>{e(p)}</p>" for p in memo.executive_summary.split("\n") if p.strip())
        ),
        section(
            "C. " + L["discussion"],
            "".join(
                f"<h3>{e(t.get('topic', ''))}</h3><ul>"
                + "".join(f"<li>{e(p)}</li>" for p in t.get("points", []))
                + "</ul>"
                for t in memo.discussion
            ),
        ),
        section(
            "D. " + L["decisions"],
            table(
                ["ID", L["decisions"], L["owner"], L["verification"], L["source"]],
                [
                    [d.code, d.statement, d.owner_text or L["none"], d.verification_status.value, _refs(d.sources)]
                    for d in memo.decisions
                ],
            ),
        ),
        section(
            "E. " + L["actions"],
            table(
                ["ID", L["actions"], L["owner"], L["due"], L["priority"], L["status"], L["verification"], L["source"]],
                [
                    [
                        a.code,
                        a.description,
                        a.owner_text or L["none"],
                        a.due_date.isoformat() if a.due_date else (a.due_text or L["none"]),
                        a.priority.value,
                        a.status.value,
                        a.verification_status.value,
                        _refs(a.sources),
                    ]
                    for a in memo.action_items
                ],
            ),
        ),
        section(
            "F. " + L["issues"],
            table(
                ["ID", L["issues"], L["impact"], L["owner"], L["status"], L["follow_up"], L["source"]],
                [
                    [
                        i.code,
                        i.description,
                        i.impact or "",
                        i.owner_text or "",
                        i.status.value,
                        i.follow_up or "",
                        _refs(i.sources),
                    ]
                    for i in memo.issues
                ],
            ),
        ),
        section(
            "G. " + L["risks"],
            table(
                ["ID", L["risks"], L["probability"], L["impact"], L["mitigation"], L["owner"], L["source"]],
                [
                    [
                        r.code,
                        r.description,
                        r.probability.value,
                        r.impact or "",
                        r.mitigation or "",
                        r.owner_text or "",
                        _refs(r.sources),
                    ]
                    for r in memo.risks
                ],
            ),
        ),
        section(
            "H. " + L["questions"],
            "<ul>" + "".join(f"<li>{e(q.get('question', ''))}</li>" for q in memo.open_questions) + "</ul>",
        ),
        section("I. " + L["next"], f"<p>{e((memo.next_meeting or {}).get('when_text') or L['none'])}</p>"),
        section(
            "J. " + L["pm"],
            table(
                ["", "", ""],
                [
                    [k, v["assessment"], L.get(v["basis"], v["basis"])]
                    for k in PM_KEYS
                    if (v := (memo.pm_view or {}).get(k))
                ],
            ),
        ),
    ]
    return f"""<!doctype html><html lang="{e(memo.language.value)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(info.title)}</title>
<style>body{{font-family:system-ui,"Noto Sans JP","Noto Sans",sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1f2937}}
h1{{font-size:1.5rem}}h2{{font-size:1.1rem;border-bottom:1px solid #e5e7eb;padding-bottom:.25rem;margin-top:1.5rem}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}td,th{{border:1px solid #e5e7eb;padding:.35rem .5rem;text-align:left;vertical-align:top}}
th{{background:#f9fafb}}footer{{margin-top:2rem;color:#6b7280;font-size:.8rem}}</style></head>
<body><h1>{e(info.title)}</h1>{"".join(parts)}<footer>{e(L["ai_note"])}</footer></body></html>"""


def memo_to_json(memo: MemoOut) -> str:
    return memo.model_dump_json(indent=2, exclude={"permissions"})


def _csv_safe(value: str | None) -> str:
    v = value or ""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_meeting_record(db: Session, meeting: Meeting, fmt: str) -> tuple[str, str, str]:
    project = db.get(Project, meeting.project_id)
    assert project is not None
    rows = db.execute(
        select(TranscriptEntry, Translation)
        .outerjoin(
            Translation,
            (Translation.entry_id == TranscriptEntry.id) & (Translation.target_language == meeting.target_language),
        )
        .where(TranscriptEntry.meeting_id == meeting.id)
        .order_by(TranscriptEntry.sequence)
    ).all()

    def ts(ms: int | None) -> str:
        if ms is None:
            return ""
        s = ms // 1000
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "sequence",
                "start",
                "end",
                "speaker",
                "source_language",
                "original_text",
                "target_language",
                "translation",
                "translation_status",
                "translation_user_edited",
            ]
        )
        for entry, tr in rows:
            writer.writerow(
                [
                    entry.sequence,
                    ts(entry.start_ms),
                    ts(entry.end_ms),
                    _csv_safe(entry.speaker_label),
                    entry.source_language.value if entry.source_language else "",
                    _csv_safe(entry.original_text),
                    meeting.target_language.value,
                    _csv_safe(tr.text if tr else ""),
                    tr.status.value if tr else "",
                    bool(tr and tr.is_user_edited),
                ]
            )
        return "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8", "csv"
    if fmt == "json":
        payload: dict[str, Any] = {
            "meeting": {
                "id": str(meeting.id),
                "title": meeting.title,
                "project": project.name,
                "scheduled_at": meeting.scheduled_at.isoformat(),
                "timezone": meeting.timezone,
                "platform": meeting.platform.value,
            },
            "entries": [
                {
                    "sequence": e_.sequence,
                    "speaker": e_.speaker_label,
                    "start_ms": e_.start_ms,
                    "end_ms": e_.end_ms,
                    "text": e_.original_text,
                    "language": e_.source_language.value if e_.source_language else None,
                    "translation": {
                        "language": meeting.target_language.value,
                        "text": tr.text,
                        "status": tr.status.value,
                        "ai_generated": not tr.is_user_edited,
                    }
                    if tr
                    else None,
                }
                for e_, tr in rows
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2), "application/json", "json"
    lines = [
        f"# {meeting.title}",
        "",
        f"- Project: {project.name}",
        f"- Date: {meeting.scheduled_at:%Y-%m-%d %H:%M} ({meeting.timezone})",
        "",
        "| # | Time | Speaker | Original | Translation (AI) |",
        "|---|---|---|---|---|",
    ]
    for entry, tr in rows:
        cells = [
            str(entry.sequence),
            ts(entry.start_ms),
            entry.speaker_label or "",
            entry.original_text,
            (tr.text or "") + (" ✎" if tr and tr.is_user_edited else "") if tr else "",
        ]
        lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    return "\n".join(lines) + "\n", "text/markdown; charset=utf-8", "md"
