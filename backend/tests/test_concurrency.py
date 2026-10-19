"""Concurrency / consistency regressions: several writers on one meeting (colleagues, live
capture + platform fetch jobs, translation jobs) must not lose data or corrupt state."""

from __future__ import annotations

import threading
import time
import uuid

from app.db.session import get_sessionmaker
from app.integrations.models import CanonicalEvent
from app.models import LiveSession, Meeting, TranscriptEntry, Translation
from app.services.ingestion import ingest_event
from tests.conftest import create_meeting


def _ev(i: str) -> CanonicalEvent:
    return CanonicalEvent(provider="replay", provider_meeting_id="x", entry_id=i, original_text=f"hello {i}")


def test_concurrent_ingest_sequence_collision(pm):
    mid = uuid.UUID(create_meeting(pm)["id"])
    S = get_sessionmaker()
    a = S()
    meeting_a = a.get(Meeting, mid)
    ingest_event(a, meeting_a, _ev("a"))  # flushed, holds seq 1 uncommitted
    err: list[BaseException] = []

    def other() -> None:
        with S() as b:
            try:
                ingest_event(b, b.get(Meeting, mid), _ev("b"))  # also computes seq 1, blocks on the index
                b.commit()
            except BaseException as e:  # noqa: BLE001
                err.append(e)

    t = threading.Thread(target=other)
    t.start()
    time.sleep(0.5)
    a.commit()
    a.close()
    t.join(10)
    assert not err, err  # the second writer waits for the first instead of colliding
    with S() as check:
        seqs = sorted(e.sequence for e in check.query(TranscriptEntry).filter_by(meeting_id=mid))
    assert seqs == [1, 2]


def test_concurrent_new_speaker_profiles_get_distinct_keys(pm):
    from app.services.audio_capture import _new_profile

    mid = uuid.UUID(create_meeting(pm)["id"])
    S = get_sessionmaker()
    with S() as db:
        live = LiveSession(meeting_id=mid, connector="audio_capture", is_demo=True)
        db.add(live)
        db.commit()
        lid = live.id
    a = S()
    _new_profile(a, a.get(LiveSession, lid), "system", None)  # S1 for source "system"
    err: list[BaseException] = []

    def other() -> None:
        with S() as b:
            try:
                _new_profile(b, b.get(LiveSession, lid), "tab", None)  # also S1 for source "tab"
                b.commit()
            except BaseException as e:  # noqa: BLE001
                err.append(e)

    t = threading.Thread(target=other)
    t.start()
    time.sleep(0.5)
    a.commit()
    a.close()
    t.join(10)
    assert not err, err
    with S() as check:
        from app.models import AudioSpeakerProfile

        keys = {p.speaker_key for p in check.query(AudioSpeakerProfile).filter_by(live_session_id=lid)}
    assert len(keys) == 2


def test_translation_job_never_overwrites_user_correction(pm, db):
    from app.ai.base import TokenUsage, TranslatedSegment, TranslationResult
    from app.models import Project
    from app.services.provider_config import resolve_provider
    from app.services.translation import translate_entries

    m = create_meeting(pm)
    r = pm.post(
        f"/meetings/{m['id']}/transcript/text", json={"text": "田中: 明日までに資料を送ります。\n佐藤: 了解です。"}
    )
    assert r.status_code == 201, r.text
    meeting = db.get(Meeting, uuid.UUID(m["id"]))
    entries = list(db.query(TranscriptEntry).filter_by(meeting_id=meeting.id).order_by(TranscriptEntry.sequence))
    target_entry = entries[0]

    class SlowProvider:
        provider_key = "fake"
        model = "fake"

        def translate(self, request):
            # While the AI call is in flight, the user corrects entry #1's translation.
            r2 = pm.put(
                f"/transcript-entries/{target_entry.id}/translation",
                json={"target_language": "vi", "text": "USER FIX"},
            )
            assert r2.status_code == 200, r2.text
            return TranslationResult(
                segments=[TranslatedSegment(ref=s.ref, text=f"AI {s.ref}") for s in request.segments],
                usage=TokenUsage(),
                model="fake",
                attempts=1,
            )

    user_id = uuid.UUID(pm.user["id"])
    from app.models import AIProviderConfiguration

    resolved = (
        resolve_provider(db, user_id, None)
        if db.query(AIProviderConfiguration).filter_by(user_id=user_id, is_default=True).first()
        else None
    )
    if resolved is None:
        from app.ai.base import Credentials
        from app.ai.catalog import get_catalog
        from app.services.provider_config import ResolvedProvider

        resolved = ResolvedProvider(
            get_catalog().get("mock"), None, "mock-deterministic", Credentials(None, None), "none"
        )
    translate_entries(
        db,
        meeting=meeting,
        project=db.get(Project, meeting.project_id),
        entries=entries,
        target=meeting.target_language,
        resolved=resolved,
        user_id=user_id,
        job_id=None,
        provider=SlowProvider(),
    )
    with get_sessionmaker()() as fresh:
        tr = fresh.query(Translation).filter_by(entry_id=target_entry.id).one()
        assert tr.is_user_edited is True
        assert tr.text == "USER FIX"


def test_memo_not_stuck_generating_after_worker_lost(pm, db):
    from datetime import timedelta

    from app.db.base import utcnow
    from app.models import Job, Memo
    from app.services import jobs as job_service

    m = create_meeting(pm)
    assert (
        pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: 明日までに資料を送ります。"}).status_code
        == 201
    )
    assert pm.post(f"/meetings/{m['id']}/memo/generate").status_code == 202
    # worker claims the job, then dies (deploy / OOM) on its last attempt
    job = job_service.claim_next(db, "w1")
    job.attempts = job.max_attempts
    job.heartbeat_at = utcnow() - timedelta(minutes=30)
    db.commit()
    job_service.requeue_stale(db)
    db.expire_all()
    assert db.get(Job, job.id).status.value == "failed"
    memo = db.query(Memo).filter_by(meeting_id=uuid.UUID(m["id"])).one()
    assert memo.status.value == "failed" and memo.generation_error
    r = pm.post(f"/meetings/{m['id']}/memo/generate")
    assert r.status_code == 202, r.text  # the user can try again


def test_concurrent_get_or_create_translation(pm):
    from app.models.enums import Language
    from app.services.translation import get_or_create_translation

    m = create_meeting(pm)
    assert pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: テスト"}).status_code == 201
    S = get_sessionmaker()
    a = S()
    e = a.query(TranscriptEntry).filter_by(meeting_id=uuid.UUID(m["id"])).one()
    get_or_create_translation(a, e, Language.vi)
    err: list[BaseException] = []

    def other() -> None:
        with S() as b:
            try:
                get_or_create_translation(b, b.get(TranscriptEntry, e.id), Language.vi)
                b.commit()
            except BaseException as ex:  # noqa: BLE001
                err.append(ex)

    t = threading.Thread(target=other)
    t.start()
    time.sleep(0.5)
    a.commit()
    a.close()
    t.join(10)
    assert not err, err
    with S() as check:
        assert check.query(Translation).filter_by(entry_id=e.id).count() == 1


def test_retention_purges_content_added_after_a_purge(pm, db):
    from app.models import Project
    from app.services.retention import enforce_retention

    m = create_meeting(pm)  # scheduled 2026-10-14
    meeting = db.get(Meeting, uuid.UUID(m["id"]))
    db.get(Project, meeting.project_id).retention_days = 1
    db.commit()
    assert pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: テスト"}).status_code == 201
    enforce_retention(db)
    db.commit()
    assert db.query(TranscriptEntry).filter_by(meeting_id=meeting.id).count() == 0  # purged
    assert pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: 秘密"}).status_code == 201
    enforce_retention(db)
    db.commit()
    assert db.query(TranscriptEntry).filter_by(meeting_id=meeting.id).count() == 0


def test_transcript_cannot_be_replaced_while_the_memo_is_generating(pm):
    m = create_meeting(pm)
    assert pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: テスト"}).status_code == 201
    assert pm.post(f"/meetings/{m['id']}/memo/generate").status_code == 202
    r = pm.post(f"/meetings/{m['id']}/transcript/text", json={"text": "田中: 別", "replace": True})
    assert r.status_code == 409, r.text


def test_deleting_the_default_provider_promotes_another(pm):
    pm.put(
        "/providers/configs",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": "sk-test-0123456789abcdef",
            "remember": True,
            "make_default": False,
        },
    )
    configs = pm.get("/providers/configs").json()
    default = next(c for c in configs if c["is_default"])
    assert pm.delete(f"/providers/configs/{default['id']}").status_code == 204
    assert any(c["is_default"] for c in pm.get("/providers/configs").json())
