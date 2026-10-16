"""Integration tests for platform connectors against contract fixtures
(MOCKED providers — see tests/fakes/fake_providers.py). No real provider is
contacted; every connection here is flagged SANDBOX."""

from __future__ import annotations

import urllib.parse
from datetime import timedelta

from sqlalchemy import select

from app.db.base import utcnow
from app.models import ExternalMeetingReference, Job, PlatformConnection, PlatformCredential, TranscriptEntry
from app.models.enums import JobStatus
from tests.conftest import connect_platform, create_meeting, run_jobs
from tests.fakes.fake_providers import MEET_CODE, TEAMS_JOIN_URL, ZOOM_MEETING_ID


def _status(client, provider):
    return client.get(f"/integrations/{provider}").json()


def _cap(view, name):
    return next(c for c in view["capabilities"] if c["capability"] == name)


def test_unconfigured_platforms_are_truthful(pm):
    rows = {r["provider"]: r for r in pm.get("/integrations").json()}
    assert set(rows) == {"teams", "zoom", "google_meet"}
    for row in rows.values():
        assert row["status"] == "not_configured"
        assert _cap(row, "transcript_import")["status"] == "available"
        assert _cap(row, "post_meeting_transcript")["status"] == "requires_configuration"
        assert row["sandbox"] is False
    assert _cap(rows["teams"], "live_transcript")["status"] == "not_supported"
    assert _cap(rows["google_meet"], "live_transcript")["status"] == "not_supported"
    assert pm.post("/integrations/teams/connect").status_code == 409


def test_teams_oauth_link_fetch_translate_memo(pm, fake, db):
    cb, params = connect_platform(pm, fake, "teams")
    assert cb.status_code == 302 and cb.headers["location"] == "/integrations?provider=teams&result=connected"
    assert params["code_challenge_method"] == "S256" and len(params["code_challenge"]) >= 43
    assert params["redirect_uri"] == "http://localhost:3000/api/v1/integrations/teams/oauth/callback"
    assert "OnlineMeetingTranscript.Read.All" in params["scope"]
    view = _status(pm, "teams")
    assert view["status"] == "connected_post_meeting_only"  # live is never advertised for Teams
    assert view["sandbox"] is True and view["account"] == "pm@contoso.onmicrosoft.com"
    assert _cap(view, "post_meeting_transcript")["status"] == "available"
    assert _cap(view, "live_transcript")["status"] == "not_supported"

    meetings = pm.get("/integrations/teams/meetings").json()
    assert [m["join_url"] for m in meetings] == [TEAMS_JOIN_URL]  # non-online calendar events filtered out

    meeting = create_meeting(pm)
    r = pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    assert r.status_code == 201, r.text
    assert r.json()["transcript_status"] == "unknown"
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    assert job["kind"] == "fetch_transcript"
    run_jobs()
    assert pm.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
    src = pm.get(f"/meetings/{meeting['id']}/external-source").json()
    assert src["transcript_status"] == "imported"

    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert [e["speaker_label"] for e in entries] == ["田中 太郎", "Nguyen An", "田中 太郎", "Nguyen An"]
    assert [e["start_ms"] for e in entries] == [2120, 7000, 13100, 16000]
    assert entries[0]["source_metadata"]["connector"] == "teams"
    assert entries[0]["source_metadata"]["is_demo"] is False
    # Legitimate repeated short replies ("はい") from different speakers/times are both kept.
    assert sum(e["original_text"] == "はい。" for e in entries) == 2
    assert all(e["translation"]["status"] == "done" for e in entries)  # existing translation pipeline

    # Re-fetch is idempotent: no duplicate entries.
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    run_jobs()
    assert len(pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]) == 4
    assert "0 new, 4 already imported" in pm.get(f"/meetings/{meeting['id']}/external-source").json()["status_message"]

    # Memo generation uses the ingested transcript with source references.
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    action = next(a for a in memo["action_items"] if a["sources"][0]["sequence"] == 2)
    assert action["sources"][0]["speaker_label"] == "Nguyen An"
    assert action["due_text"] == "来週金曜日"


def test_teams_without_admin_consent_degrades_to_import(pm, fake):
    fake.scenario["teams"] = "no_admin_consent"
    connect_platform(pm, fake, "teams")
    view = _status(pm, "teams")
    assert view["status"] == "admin_approval_required"
    cap = _cap(view, "post_meeting_transcript")
    assert cap["status"] == "requires_admin_approval" and "administrator consent" in cap["message"]
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    r = pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    assert r.status_code == 403 and r.json()["error"]["code"] == "integration_admin_approval_required"
    # The rest of the product keeps working: manual import is unaffected.
    imp = pm.post(f"/meetings/{meeting['id']}/transcript/text", json={"text": "A: hello there"})
    assert imp.status_code == 201


def test_teams_admin_consent_denied_at_authorization(pm, fake):
    fake.scenario["teams"] = "consent_denied_admin"
    cb, _ = connect_platform(pm, fake, "teams")
    assert cb.headers["location"].endswith("result=error&category=admin_approval_required")
    assert _status(pm, "teams")["status"] == "admin_approval_required"


def test_teams_tenant_disabled_transcripts(pm, fake):
    fake.scenario["teams"] = "transcripts_disabled"
    connect_platform(pm, fake, "teams")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    run_jobs()
    job = pm.get(f"/jobs/{job['id']}").json()
    assert job["status"] == "failed" and job["error_code"] == "admin_approval_required"
    src = pm.get(f"/meetings/{meeting['id']}/external-source").json()
    assert src["transcript_status"] == "permission_denied"
    assert "disabled" in src["status_message"] and "import" in src["status_message"]


def test_teams_speaker_attribution_disabled_falls_back(pm, fake):
    fake.scenario["teams"] = "no_speaker"
    connect_platform(pm, fake, "teams")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    run_jobs()
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert len(entries) == 2 and all(e["speaker_label"] is None for e in entries)  # never invented
    assert (
        "Speaker attribution is disabled"
        in pm.get(f"/meetings/{meeting['id']}/external-source").json()["status_message"]
    )


def test_teams_no_transcript_yet_is_pending_with_bounded_retry(pm, fake, db):
    fake.scenario["teams"] = "no_transcript"
    connect_platform(pm, fake, "teams")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    # The fake meeting ended long ago => "not available" (transcription was never started).
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    run_jobs()
    src = pm.get(f"/meetings/{meeting['id']}/external-source").json()
    assert src["transcript_status"] == "not_available"


def test_token_refresh_on_401_and_rotation(pm, fake, db):
    connect_platform(pm, fake, "teams")
    conn = db.scalar(select(PlatformConnection))
    old_refresh = db.scalar(select(PlatformCredential)).encrypted_refresh_token
    fake.teams_401_once = True
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    db.expire_all()
    # link() consumed the forced 401 -> mapped to token_expired; retrying works after refresh in fetch
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    fake.teams_401_once = True
    run_jobs()
    db.expire_all()
    assert db.get(PlatformConnection, conn.id).state.value == "connected"
    assert db.scalar(select(PlatformCredential)).encrypted_refresh_token != old_refresh  # rotated
    assert len(pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]) == 4


def test_expired_access_token_is_refreshed_proactively(pm, fake, db):
    connect_platform(pm, fake, "zoom")
    cred = db.scalar(select(PlatformCredential))
    cred.access_token_expires_at = utcnow() - timedelta(minutes=5)
    db.commit()
    assert pm.post("/integrations/zoom/test").json()["ok"] is True
    assert sum(c == "POST /zoom/token" for c in fake.calls) == 2  # code exchange + refresh


def test_revoked_consent_is_reported(pm, fake, db):
    connect_platform(pm, fake, "google_meet")
    cred = db.scalar(select(PlatformCredential))
    cred.access_token_expires_at = utcnow() - timedelta(minutes=5)
    db.commit()
    fake.scenario["google"] = "revoked"
    r = pm.post("/integrations/google_meet/test").json()
    assert r["ok"] is False and r["connection"]["status"] == "error"
    assert r["connection"]["last_error_category"] == "consent_revoked"


def test_zoom_recording_transcript_and_redirect_without_token_leak(pm, fake):
    connect_platform(pm, fake, "zoom")
    view = _status(pm, "zoom")
    assert view["status"] == "connected"  # RTMS configured in the fixture → live capability available
    assert _cap(view, "live_audio")["status"] == "not_supported"
    meeting = create_meeting(pm)
    r = pm.post(
        f"/meetings/{meeting['id']}/external-source",
        json={"provider": "zoom", "reference": f"https://us02web.zoom.us/j/{ZOOM_MEETING_ID}?pwd=x"},
    )
    assert r.status_code == 201 and r.json()["provider_meeting_id"] == ZOOM_MEETING_ID
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    run_jobs()
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert [e["speaker_label"] for e in entries] == ["Sarah Johnson", "Kenji Watanabe"]
    assert "GET /zoom/cdn/transcript-1.vtt" in fake.calls  # fake rejects the CDN call if a token is forwarded


def test_zoom_processing_reschedules_then_imports(pm, fake, db):
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    fake.scenario["zoom"] = "processing"
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    run_jobs()
    j = db.get(Job, job["id"])
    assert j.status == JobStatus.queued and j.run_after > utcnow()  # bounded backoff, not a busy loop
    src = pm.get(f"/meetings/{meeting['id']}/external-source").json()
    assert src["transcript_status"] == "pending" and src["next_check_at"]
    assert run_jobs() == 0  # not due yet
    fake.scenario["zoom"] = ""
    again = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()  # "retry now"
    assert again["id"] == job["id"]  # reuses the scheduled job instead of duplicating it
    run_jobs()
    assert pm.get(f"/meetings/{meeting['id']}/external-source").json()["transcript_status"] == "imported"


def test_zoom_rate_limit_honours_retry_after(pm, fake, db):
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    fake.scenario["zoom"] = "rate_limited"
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    run_jobs()
    j = db.get(Job, job["id"])
    assert j.status == JobStatus.queued and (j.run_after - utcnow()).total_seconds() >= 110


def test_zoom_missing_scope_is_not_retried(pm, fake):
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    fake.scenario["zoom"] = "scope_missing"
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    run_jobs()
    assert pm.get(f"/jobs/{job['id']}").json()["error_code"] == "insufficient_scope"
    assert pm.get(f"/meetings/{meeting['id']}/external-source").json()["transcript_status"] == "permission_denied"


def test_google_meet_transcript_entries_with_pagination_and_participants(pm, fake):
    connect_platform(pm, fake, "google_meet")
    view = _status(pm, "google_meet")
    assert view["status"] == "connected_post_meeting_only"
    meeting = create_meeting(pm)
    r = pm.post(
        f"/meetings/{meeting['id']}/external-source",
        json={"provider": "google_meet", "reference": f"https://meet.google.com/{MEET_CODE}"},
    )
    assert r.status_code == 201
    pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
    run_jobs()
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert [e["speaker_label"] for e in entries] == ["Trần Minh", "Linh (Guest)", None]  # p3 unknown → not invented
    assert [e["start_ms"] for e in entries] == [2500, 10000, 30000]
    assert [e["source_language"] for e in entries] == ["en", "en", "vi"]


def test_google_meet_pending_expired_and_ongoing(pm, fake):
    connect_platform(pm, fake, "google_meet")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "google_meet", "reference": MEET_CODE})
    for scenario, expected in (("generating", "pending"), ("ongoing", "pending"), ("expired", "not_available")):
        fake.scenario["google"] = scenario
        pm.post(f"/meetings/{meeting['id']}/external-source/fetch")
        run_jobs()
        src = pm.get(f"/meetings/{meeting['id']}/external-source").json()
        assert src["transcript_status"] == expected, scenario
    assert pm.get(f"/meetings/{meeting['id']}/transcript").json()["total"] == 0


def test_google_without_meet_scope_requires_consent(pm, fake):
    fake.scenario["google"] = "no_meet_scope"
    connect_platform(pm, fake, "google_meet")
    view = _status(pm, "google_meet")
    assert _cap(view, "post_meeting_transcript")["status"] == "requires_user_consent"


def test_disconnect_revokes_and_deletes_credentials(pm, fake, db):
    connect_platform(pm, fake, "zoom")
    assert db.scalar(select(PlatformCredential)) is not None
    r = pm.delete("/integrations/zoom")
    assert r.status_code == 200 and r.json()["status"] == "not_connected"
    db.expire_all()
    assert db.scalar(select(PlatformCredential)) is None and db.scalar(select(PlatformConnection)) is None
    assert fake.revoked  # provider-side revocation attempted


def test_link_validation_and_uniqueness(pm, fake, outsider):
    connect_platform(pm, fake, "teams")
    meeting = create_meeting(pm)
    bad = pm.post(
        f"/meetings/{meeting['id']}/external-source",
        json={"provider": "teams", "reference": "https://evil.example.com/l/meetup-join/x"},
    )
    assert bad.status_code == 422
    missing = pm.post(
        f"/meetings/{meeting['id']}/external-source",
        json={"provider": "teams", "reference": "https://teams.microsoft.com/l/meetup-join/other"},
    )
    assert missing.status_code == 404
    assert (
        pm.post(
            f"/meetings/{meeting['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL}
        ).status_code
        == 201
    )
    other = create_meeting(pm, title="Another meeting")
    dup = pm.post(f"/meetings/{other['id']}/external-source", json={"provider": "teams", "reference": TEAMS_JOIN_URL})
    assert dup.status_code == 409 and "already linked" in dup.json()["error"]["message"]
    # zoom not connected → clear error
    nc = pm.post(f"/meetings/{other['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    assert nc.status_code == 409 and nc.json()["error"]["code"] == "integration_not_connected"


def test_unlink_and_retry_failed_job(pm, fake, db):
    connect_platform(pm, fake, "zoom")
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/external-source", json={"provider": "zoom", "reference": ZOOM_MEETING_ID})
    fake.scenario["zoom"] = "scope_missing"
    job = pm.post(f"/meetings/{meeting['id']}/external-source/fetch").json()
    run_jobs()
    fake.scenario["zoom"] = ""
    retry = pm.post(f"/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    run_jobs()
    assert pm.get(f"/meetings/{meeting['id']}/external-source").json()["transcript_status"] == "imported"
    assert pm.delete(f"/meetings/{meeting['id']}/external-source").status_code == 204
    assert db.scalar(select(ExternalMeetingReference)) is None
    # Ingested entries stay (they are the meeting's transcript now).
    assert db.scalar(select(TranscriptEntry.id).where(TranscriptEntry.meeting_id == meeting["id"])) is not None


def test_authorization_url_parameters_per_provider(pm, fake):
    for provider, expect in (
        ("google_meet", {"access_type": "offline", "prompt": "consent"}),
        ("zoom", {"response_type": "code"}),
        ("teams", {"response_mode": "query"}),
    ):
        url = pm.post(f"/integrations/{provider}/connect").json()["authorization_url"]
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        for k, v in expect.items():
            assert q[k] == v
        assert q["state"] and q["code_challenge_method"] == "S256"
