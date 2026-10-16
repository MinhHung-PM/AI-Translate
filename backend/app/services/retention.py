"""Data retention and deletion.

* Each project has ``retention_days``. When a meeting is older than that,
  its transcript entries and translations are purged; the meeting record,
  approved memo and tracked items remain (source links to purged lines are
  removed with them) and ``content_purged_at`` is set.
* Soft-deleted meetings are hard-deleted after ``SOFT_DELETE_GRACE``.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Meeting, PlatformOAuthState, Project, ProviderEvent, TranscriptEntry

SOFT_DELETE_GRACE = timedelta(days=30)


def purge_meeting_content(db: Session, meeting: Meeting) -> int:
    result = db.execute(delete(TranscriptEntry).where(TranscriptEntry.meeting_id == meeting.id))
    meeting.content_purged_at = utcnow()
    return int(getattr(result, "rowcount", 0) or 0)


def enforce_retention(db: Session) -> dict[str, int]:
    now = utcnow()
    purged_meetings = 0
    purged_entries = 0
    for project in db.scalars(select(Project).where(Project.retention_days > 0)):
        cutoff = now - timedelta(days=project.retention_days)
        meetings = db.scalars(
            select(Meeting).where(
                Meeting.project_id == project.id, Meeting.scheduled_at < cutoff, Meeting.content_purged_at.is_(None)
            )
        )
        for meeting in meetings:
            purged_entries += purge_meeting_content(db, meeting)
            purged_meetings += 1
    hard = db.execute(
        delete(Meeting).where(Meeting.deleted_at.is_not(None), Meeting.deleted_at < now - SOFT_DELETE_GRACE)
    )
    return {
        "meetings_purged": purged_meetings,
        "entries_purged": purged_entries,
        "meetings_hard_deleted": int(getattr(hard, "rowcount", 0) or 0),
    }


PROVIDER_EVENT_RETENTION = timedelta(days=30)


def purge_provider_events(db: Session) -> int:
    """Webhook event log (no transcript content) is kept 30 days for replay
    protection and diagnostics; stale OAuth states are removed too."""
    now = utcnow()
    db.execute(delete(PlatformOAuthState).where(PlatformOAuthState.created_at < now - timedelta(hours=1)))
    result = db.execute(delete(ProviderEvent).where(ProviderEvent.received_at < now - PROVIDER_EVENT_RETENTION))
    return int(getattr(result, "rowcount", 0) or 0)
