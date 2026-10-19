"""Integration tests for migrations, job lifecycles, replay, glossary,
translation edits, provider configuration, retention and pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, select

from alembic import command
from app.db.session import get_engine
from app.models import LiveSession, Meeting
from tests.conftest import alembic_config, create_meeting, project_id, run_jobs, upload_sample


def test_migrations_downgrade_and_upgrade():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    assert "meetings" not in inspect(get_engine()).get_table_names()
    command.upgrade(cfg, "head")
    tables = set(inspect(get_engine()).get_table_names())
    expected = {
        "users",
        "divisions",
        "projects",
        "project_memberships",
        "meetings",
        "meeting_participants",
        "transcript_entries",
        "translations",
        "memos",
        "decisions",
        "action_items",
        "issues",
        "risks",
        "memo_item_sources",
        "ai_provider_configurations",
        "usage_records",
        "audit_events",
        "jobs",
        "glossary_entries",
        "session_secrets",
        "live_sessions",
    }
    assert expected <= tables


def test_all_formats_import(pm):
    for name, fmt, count in [
        ("ja_client_meeting.vtt", "vtt", 8),
        ("vi_internal_meeting.txt", "txt", 7),
        ("en_steering_meeting.srt", "srt", 6),
        ("sample_transcript.json", "json", 3),
    ]:
        meeting = create_meeting(pm, title=f"Import {name}")
        r = upload_sample(pm, meeting["id"], name)
        assert r.status_code == 201, r.text
        assert r.json()["format"] == fmt and r.json()["entry_count"] == count


def test_text_import_with_language_override(pm):
    meeting = create_meeting(pm)
    r = pm.post(f"/meetings/{meeting['id']}/transcript/text", json={"text": "A: 123\nB: 456", "source_language": "en"})
    assert r.status_code == 201
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert all(e["source_language"] == "en" for e in entries)
    assert pm.get(f"/meetings/{meeting['id']}").json()["source_language"] == "en"


def test_transcript_search_and_status_filter(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    r = pm.get(f"/meetings/{meeting['id']}/transcript", params={"q": "受入テスト"})
    assert r.json()["total"] == 1
    r = pm.get(f"/meetings/{meeting['id']}/transcript", params={"status": "pending"})
    assert r.json()["total"] == 8


def test_selected_entry_translation_and_glossary(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    pm.post(f"/meetings/{meeting['id']}/translations", json={"entry_ids": [entries[0]["id"]]})
    run_jobs()
    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert entries[0]["translation"]["status"] == "done"
    assert entries[1]["translation"] is None
    # Seed glossary maps 在庫引当 -> phân bổ tồn kho (applied by the mock provider)
    assert "phân bổ tồn kho" in entries[0]["translation"]["text"]


def test_user_edited_translation_is_preserved_and_source_untouched(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/translations", json={})
    run_jobs()
    entry = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"][0]
    r = pm.put(
        f"/transcript-entries/{entry['id']}/translation", json={"text": "Bản dịch đã sửa", "target_language": "vi"}
    )
    assert r.status_code == 200 and r.json()["is_user_edited"]
    pm.post(f"/meetings/{meeting['id']}/translations", json={"force": True})
    run_jobs()
    after = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"][0]
    assert after["translation"]["text"] == "Bản dịch đã sửa"
    assert after["original_text"] == entry["original_text"]


def test_source_correction_keeps_original_wording(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/translations", json={})
    run_jobs()
    entry = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"][0]
    r = pm.patch(f"/transcript-entries/{entry['id']}", json={"original_text": "修正後のテキスト"})
    body = r.json()
    assert body["original_edited"] is True
    assert body["source_metadata"]["original_text_before_edit"] == entry["original_text"]
    assert body["translation"]["status"] == "pending"


def test_concurrent_job_guard(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    assert pm.post(f"/meetings/{meeting['id']}/translations", json={}).status_code == 202
    assert pm.post(f"/meetings/{meeting['id']}/translations", json={}).status_code == 409
    run_jobs()
    assert pm.post(f"/meetings/{meeting['id']}/translations", json={}).status_code == 202


def test_replay_lifecycle_emits_demo_events_and_translates(pm, db):
    meeting = create_meeting(pm, title="Replay demo")
    text = "田中: 本日の議題を確認します。\nNguyen: 仕様書を共有します。\n田中: 了解しました。"
    r = pm.post(f"/meetings/{meeting['id']}/replay", data={"text": text, "interval_seconds": "0"})
    assert r.status_code == 202, r.text
    live = r.json()
    assert live["is_demo"] is True and live["connector"] == "replay" and live["entries_total"] == 3
    run_jobs()
    feed = pm.get(f"/meetings/{meeting['id']}/live").json()
    assert feed["session"]["status"] == "completed" and feed["session"]["entries_emitted"] == 3
    assert [e["sequence"] for e in feed["entries"]] == [1, 2, 3]
    assert all(e["source_metadata"]["is_demo"] is True for e in feed["entries"])
    assert all(e["translation"]["status"] == "done" for e in feed["entries"])
    assert pm.get(f"/meetings/{meeting['id']}/live", params={"after_sequence": 2}).json()["entries"][0]["sequence"] == 3
    # A meeting that already has a transcript cannot be replayed into.
    assert pm.post(f"/meetings/{meeting['id']}/replay", data={"text": text}).status_code == 409


def test_replay_stop(pm, db):
    meeting = create_meeting(pm)
    live = pm.post(f"/meetings/{meeting['id']}/replay", data={"text": "A: one\nA: two", "interval_seconds": "0"}).json()
    assert pm.post(f"/live-sessions/{live['id']}/stop").json()["status"] == "stopped"
    run_jobs()
    assert db.get(LiveSession, live["id"]).entries_emitted == 0


def test_provider_config_lifecycle(pm):
    providers = pm.get("/providers").json()
    keys = {p["key"] for p in providers["providers"]}
    assert {"mock", "openai", "openai_compatible"} <= keys
    assert providers["secret_storage_available"] is True
    configs = pm.get("/providers/configs").json()
    mock_cfg = next(c for c in configs if c["provider"] == "mock")
    assert mock_cfg["is_default"] and mock_cfg["has_usable_key"]
    test = pm.post(f"/providers/configs/{mock_cfg['id']}/test").json()
    assert test["ok"] is True
    oa = pm.put("/providers/configs", json={"provider": "openai", "model": "gpt-4.1-mini", "make_default": True}).json()
    assert oa["is_default"] and not oa["has_usable_key"]
    test = pm.post(f"/providers/configs/{oa['id']}/test").json()
    assert test["ok"] is False and "API key" in test["message"]
    assert pm.post(f"/providers/configs/{mock_cfg['id']}/default").json()["is_default"]
    assert (
        pm.put("/providers/configs", json={"provider": "openai", "model": "not-a-real-model!!" * 10}).status_code == 422
    )
    assert pm.put("/providers/configs", json={"provider": "nope", "model": "x"}).status_code == 404
    assert pm.delete(f"/providers/configs/{oa['id']}").status_code == 204


def test_glossary_crud_requires_manager(pm, member):
    pid = project_id(pm)
    body = {
        "source_term": "本番環境",
        "preferred_translation": "môi trường production",
        "source_language": "ja",
        "target_language": "vi",
    }
    assert member.post(f"/projects/{pid}/glossary", json=body).status_code == 403
    r = pm.post(f"/projects/{pid}/glossary", json=body)
    assert r.status_code == 201
    assert pm.post(f"/projects/{pid}/glossary", json=body).status_code == 409
    gid = r.json()["id"]
    assert pm.patch(f"/projects/{pid}/glossary/{gid}", json={"is_active": False}).json()["is_active"] is False
    assert any(g["id"] == gid for g in member.get(f"/projects/{pid}/glossary").json())
    assert pm.delete(f"/projects/{pid}/glossary/{gid}").status_code == 204


def test_project_membership_management(pm, admin, outsider):
    pid = project_id(pm)
    r = pm.post(f"/projects/{pid}/members", json={"email": "outsider@example.com", "role": "member"})
    assert r.status_code == 201
    assert outsider.get(f"/projects/{pid}").status_code == 200
    assert pm.delete(f"/projects/{pid}/members/{r.json()['user_id']}").status_code == 204
    assert outsider.get(f"/projects/{pid}").status_code == 404


def test_action_tracker_filters_and_overdue(pm):
    meeting = create_meeting(pm, scheduled_at=datetime(2026, 1, 7, 1, 0, tzinfo=UTC).isoformat())
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    r = pm.post(
        f"/memos/{memo['id']}/action-items",
        json={"description": "Gửi báo cáo", "owner_text": "Trần Minh", "due_date": "2026-01-10", "priority": "high"},
    )
    manual = next(a for a in r.json()["action_items"] if not a["ai_generated"])
    assert manual["verification_status"] == "confirmed"
    overdue = pm.get("/action-items", params={"overdue": True}).json()
    assert any(a["id"] == manual["id"] and a["is_overdue"] for a in overdue["items"])
    assert pm.get("/action-items", params={"priority": "high"}).json()["total"] >= 1
    assert pm.get("/action-items", params={"owner": "Trần"}).json()["total"] == 1
    pm.patch(f"/action-items/{manual['id']}", json={"status": "done"})
    assert pm.get("/action-items", params={"overdue": True, "owner": "Trần"}).json()["total"] == 0
    rows = pm.get("/action-items", params={"status": ["done"]}).json()["items"]
    assert rows[0]["completed_at"] is not None
    # Rejected AI suggestions disappear from the tracker by default
    ai_item = next(a for a in memo["action_items"])
    pm.patch(f"/action-items/{ai_item['id']}", json={"verification_status": "rejected"})
    assert all(a["id"] != ai_item["id"] for a in pm.get("/action-items").json()["items"])


def test_action_owner_can_update_status_only(pm, member, db):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    action = memo["action_items"][0]
    assert member.patch(f"/action-items/{action['id']}", json={"status": "done"}).status_code == 403
    pm.patch(f"/action-items/{action['id']}", json={"owner_user_id": member.user["id"]})
    assert member.patch(f"/action-items/{action['id']}", json={"status": "in_progress"}).status_code == 200
    assert member.patch(f"/action-items/{action['id']}", json={"description": "x"}).status_code == 403
    # Owners must be project members
    assert pm.patch(f"/action-items/{action['id']}", json={"owner_user_id": str(_outsider_id(db))}).status_code == 422


def _outsider_id(db):
    from app.models import User

    return db.scalar(select(User.id).where(User.email == "outsider@example.com"))


def test_history_pagination_and_filters(pm):
    for i in range(5):
        create_meeting(
            pm,
            title=f"Weekly sync {i}",
            scheduled_at=(datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=i)).isoformat(),
            platform="teams" if i % 2 else "manual_import",
        )
    page1 = pm.get("/meetings", params={"page_size": 2}).json()
    page3 = pm.get("/meetings", params={"page_size": 2, "page": 3}).json()
    assert page1["total"] == 5 and len(page1["items"]) == 2 and len(page3["items"]) == 1
    assert page1["items"][0]["title"] == "Weekly sync 4"
    teams = pm.get("/meetings", params={"platform": "teams"}).json()
    assert teams["total"] == 2 and teams["items"][0]["platform_status"] == "not_configured"
    ranged = pm.get("/meetings", params={"date_from": "2026-10-02T00:00:00Z", "date_to": "2026-10-03T23:59:59Z"})
    assert ranged.json()["total"] == 2


def test_meeting_soft_delete(pm):
    meeting = create_meeting(pm)
    assert pm.delete(f"/meetings/{meeting['id']}").status_code == 204
    assert pm.get(f"/meetings/{meeting['id']}").status_code == 404
    assert pm.get("/meetings").json()["total"] == 0


def test_retention_purges_transcript_but_keeps_memo(pm, admin, db):
    meeting = create_meeting(pm, scheduled_at=(datetime.now(UTC) - timedelta(days=400)).isoformat())
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    result = admin.post("/admin/retention/run").json()
    assert result["meetings_purged"] == 1 and result["entries_purged"] == 8
    db.expire_all()
    assert db.get(Meeting, meeting["id"]).content_purged_at is not None
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["decisions"] and all(d["sources"] == [] for d in memo["decisions"])


def test_meeting_validation(pm):
    pid = project_id(pm)
    base = {"project_id": pid, "title": "x", "scheduled_at": "2026-10-14T10:00:00"}
    assert pm.post("/meetings", json=base).status_code == 422  # naive datetime
    assert (
        pm.post(
            "/meetings", json={**base, "scheduled_at": "2026-10-14T10:00:00+09:00", "timezone": "Mars/Base"}
        ).status_code
        == 422
    )
    assert (
        pm.post(
            "/meetings",
            json={**base, "scheduled_at": "2026-10-14T10:00:00+09:00", "meeting_url": "javascript:alert(1)"},
        ).status_code
        == 422
    )


def test_connectors_report_not_configured(pm):
    rows = {c["key"]: c["state"] for c in pm.get("/connectors").json()}
    assert rows["teams"] == rows["zoom"] == rows["google_meet"] == "not_configured"
    assert rows["replay"] == "demo"


def test_admin_user_management(admin, login):
    r = admin.post("/admin/users", json={"email": "new@example.com", "display_name": "New", "role": "member"})
    assert r.status_code == 201
    uid = r.json()["id"]
    login("new@example.com")
    assert admin.patch(f"/admin/users/{uid}", json={"is_active": False}).status_code == 200
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).post("/api/v1/auth/dev/login", json={"email": "new@example.com"}).status_code == 401
    assert admin.patch(f"/admin/users/{admin.user['id']}", json={"role": "member"}).status_code == 422
    health = admin.get("/admin/health").json()
    assert health["database"] == "ok" and "queued" in health["jobs"]


def test_health_endpoints():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert c.get("/api/v1/health/live").json() == {"status": "ok"}
    assert c.get("/api/v1/health/ready").json()["database"] == "ok"
    assert c.get("/api/v1/openapi.json").status_code == 200


def test_memo_action_item_linked_to_a_decision_is_saved(pm, monkeypatch):
    """Real models link actions to decisions (related_decision_index): the decision
    row must be written before the action that references it."""
    import json

    from app.ai.base import MemoGenerationResult, TokenUsage
    from app.services import memo_generation

    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    refs = [e["sequence"] for e in pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]][:2]
    draft = {
        "executive_summary": "Tóm tắt",
        "discussion": [],
        "decisions": [
            {"statement": "Làm dần từng bước", "owner": None, "confidence": "high", "source_refs": [refs[0]]}
        ],
        "action_items": [
            {
                "description": "Chuẩn bị tài liệu",
                "related_decision_index": 0,
                "kind": "confirmed",
                "source_refs": [refs[1]],
            }
        ],
        "issues": [],
        "risks": [],
        "open_questions": [],
        "next_meeting": None,
        "pm_view": None,
    }

    class Linked:
        model = "fake-llm"

        def generate(self, request, *, repair_hint=None):
            return MemoGenerationResult(json.dumps(draft, ensure_ascii=False), TokenUsage(), "fake-llm")

    monkeypatch.setattr(memo_generation, "memo_provider", lambda resolved, params: Linked())
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["status"] == "draft", memo.get("generation_error")
    action = memo["action_items"][0]
    assert action["related_decision_id"] == memo["decisions"][0]["id"]
