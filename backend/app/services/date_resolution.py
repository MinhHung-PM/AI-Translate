"""Deadline extraction and conservative resolution.

The AI only copies the deadline wording (``due_text``). Converting it to a
calendar date is done here, deterministically, using the meeting date and
timezone. Anything that is not clearly unambiguous stays unresolved and is
flagged for human confirmation. Examples:

* ``2026-10-20`` / ``10月20日`` / ``来週金曜日`` / ``thứ Sáu tuần sau`` → resolved
* ``next Friday`` (English "next" is ambiguous) / ``来週中`` / ``5/6`` → flagged
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_JA_WD = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
_EN_WD = {d.lower(): i for i, d in enumerate(calendar.day_name)}
_VI_WD = {"hai": 0, "ba": 1, "tư": 2, "tu": 2, "năm": 3, "nam": 3, "sáu": 4, "sau": 4, "bảy": 5, "bay": 5}

_EN_WD_RE = "|".join(_EN_WD)
_VI_WD_RE = r"thứ\s+(?:hai|ba|tư|năm|sáu|bảy)|chủ\s+nhật"

# Order matters: more specific patterns first.
_PHRASES: list[re.Pattern[str]] = [
    re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"),
    re.compile(r"\d{1,2}月\d{1,2}日"),
    re.compile(r"(?:来週|今週|再来週)の?[月火水木金土日]曜日?"),
    re.compile(r"[月火水木金土日]曜日?(?:まで|中)"),
    re.compile(r"明後日|明日|今日中|本日中|今月末|月末|来週中|今週中"),
    re.compile(rf"(?:by\s+)?(?:next|this)\s+(?:{_EN_WD_RE})", re.I),
    re.compile(rf"by\s+(?:{_EN_WD_RE}|tomorrow|today|end of (?:the )?(?:day|week|month))", re.I),
    re.compile(r"day after tomorrow|tomorrow|end of (?:the )?month|next week", re.I),
    re.compile(rf"(?:trước\s+)?(?:{_VI_WD_RE})(?:\s+tuần\s+(?:sau|tới|này))?", re.I),
    re.compile(r"ngày\s+mai|ngày\s+kia|cuối\s+tháng|tuần\s+(?:sau|tới)", re.I),
    re.compile(r"(?:by|trước|until|まで)?\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?", re.I),
]


def extract_due_phrase(text: str) -> str | None:
    for pattern in _PHRASES:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


@dataclass(frozen=True)
class DueResolution:
    due_date: date | None
    needs_confirmation: bool
    reason: str | None = None


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _local_date(meeting_at: datetime, tz: str) -> date:
    try:
        return meeting_at.astimezone(ZoneInfo(tz)).date()
    except ZoneInfoNotFoundError:
        return meeting_at.date()


def _upcoming(base: date, weekday: int) -> date | None:
    """Next occurrence strictly after ``base``; None if it is the same day (ambiguous)."""
    delta = (weekday - base.weekday()) % 7
    return None if delta == 0 else base + timedelta(days=delta)


def _end_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_due(due_text: str | None, meeting_at: datetime | None, tz: str | None) -> DueResolution:
    if not due_text:
        return DueResolution(None, False)
    text = due_text.strip()
    low = text.lower()

    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return DueResolution(d, d is None, None if d else "invalid date")

    if meeting_at is None or not tz:
        return DueResolution(None, True, "meeting date/timezone unknown")
    base = _local_date(meeting_at, tz)

    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        d = _safe_date(base.year, int(m[1]), int(m[2]))
        if d and d < base:
            d = _safe_date(base.year + 1, int(m[1]), int(m[2]))
        if d and (d - base).days <= 183:
            return DueResolution(d, False)
        return DueResolution(None, True, "year is unclear")

    m = re.search(r"(来週|今週|再来週)の?([月火水木金土日])曜", text)
    if m:
        offset = {"今週": 0, "来週": 7, "再来週": 14}[m[1]]
        d = _week_start(base) + timedelta(days=offset + _JA_WD[m[2]])
        if d < base:
            return DueResolution(None, True, "date is in the past")
        return DueResolution(d, False)

    m = re.search(r"([月火水木金土日])曜日?(まで|中)", text)
    if m:
        d = _upcoming(base, _JA_WD[m[1]])
        return DueResolution(d, d is None, None if d else "same weekday as meeting")

    simple_offsets = {
        "明後日": 2,
        "day after tomorrow": 2,
        "ngày kia": 2,
        "明日": 1,
        "tomorrow": 1,
        "ngày mai": 1,
        "今日中": 0,
        "本日中": 0,
        "today": 0,
        "end of day": 0,
    }
    for key, days in simple_offsets.items():
        if key in low:
            return DueResolution(base + timedelta(days=days), False)

    if any(k in low for k in ("月末", "end of month", "end of the month", "cuối tháng")):
        return DueResolution(_end_of_month(base), False)

    # Vietnamese weekday with explicit week ("thứ Sáu tuần sau") is unambiguous.
    m = re.search(r"thứ\s+(hai|ba|tư|tu|năm|nam|sáu|sau|bảy|bay)(?:\s+tuần\s+(sau|tới|này))?", low)
    if m or "chủ nhật" in low:
        wd = _VI_WD[m[1]] if m else 6
        week = m[2] if m else None
        if week in {"sau", "tới"}:
            return DueResolution(_week_start(base) + timedelta(days=7 + wd), False)
        if week == "này":
            d = _week_start(base) + timedelta(days=wd)
            return DueResolution(d if d >= base else None, d < base, None if d >= base else "date is in the past")
        d = _upcoming(base, wd)
        return DueResolution(d, d is None, None if d else "same weekday as meeting")

    m = re.search(rf"\b(next|this)\s+({_EN_WD_RE})\b", low)
    if m:
        if m[1] == "next":
            # "next Friday" can mean this coming Friday or the one after.
            return DueResolution(None, True, "'next <weekday>' is ambiguous")
        d = _week_start(base) + timedelta(days=_EN_WD[m[2]])
        return DueResolution(d if d >= base else None, d < base, None if d >= base else "date is in the past")

    m = re.search(rf"\bby\s+({_EN_WD_RE})\b", low)
    if m:
        d = _upcoming(base, _EN_WD[m[1]])
        return DueResolution(d, d is None, None if d else "same weekday as meeting")

    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if m:
        a, b = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else base.year
        if year < 100:
            year += 2000
        as_dm = _safe_date(year, b, a)
        as_md = _safe_date(year, a, b)
        if as_dm and as_md and as_dm != as_md:
            return DueResolution(None, True, "day/month order is ambiguous")
        d = as_dm or as_md
        if d and not m[3] and d < base:
            d = _safe_date(year + 1, d.month, d.day)
        return DueResolution(d, d is None, None if d else "invalid date")

    return DueResolution(None, True, "deadline wording could not be resolved to a date")
