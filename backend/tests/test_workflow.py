"""Integration: Create Project → Meeting → Import → Translate → Memo →
Review → Approve → Confirm actions → Export (mock AI provider)."""

from __future__ import annotations

from tests.conftest import create_meeting, run_jobs, upload_sample


def test_full_workflow(pm, db):
    # Create project (PM role creates and becomes manager).
    r = pm.post("/projects", json={"code": "GAMMA", "name": "Dự án Gamma", "retention_days": 365})
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["my_role"] == "manager"
    assert project["permissions"]["manage"] is True

    meeting = create_meeting(pm, "GAMMA")
    assert meeting["status"] == "planned"
    assert meeting["platform_status"] == "available"

    # Import
    r = upload_sample(pm, meeting["id"])
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["format"] == "vtt"
    assert imp["entry_count"] == 8
    assert imp["detected_language"] == "ja"

    r = pm.get(f"/meetings/{meeting['id']}/transcript")
    entries = r.json()["items"]
    assert [e["sequence"] for e in entries] == list(range(1, 9))
    assert entries[0]["speaker_label"] == "田中"
    assert entries[0]["start_ms"] == 2000
    assert entries[0]["translation"] is None

    # Translate (async job)
    r = pm.post(f"/meetings/{meeting['id']}/translations", json={})
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    assert r.json()["status"] == "queued"
    assert run_jobs() == 1
    job = pm.get(f"/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert job["result"]["translated"] == 8

    entries = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"]
    assert all(e["translation"]["status"] == "done" for e in entries)
    assert entries[0]["translation"]["text"].startswith("[MOCK ja→vi]")
    # Original never modified
    assert entries[0]["original_text"] == "本日は在庫引当機能の仕様について確認したいと思います。"
    stats = pm.get(f"/meetings/{meeting['id']}/transcript/stats").json()
    assert stats == {"total": 8, "done": 8, "failed": 0, "pending": 0, "processing": 0}

    # Generate memo
    r = pm.post(f"/meetings/{meeting['id']}/memo/generate")
    assert r.status_code == 202, r.text
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["status"] == "draft"
    assert memo["prompt_version"] == "memo-v1"
    assert memo["decisions"], "expected at least one decision"
    assert memo["action_items"], "expected at least one action"
    for item in memo["decisions"] + memo["action_items"] + memo["issues"] + memo["risks"]:
        assert item["sources"], f"item {item['code']} has no source reference"
        assert item["verification_status"] in ("draft", "needs_review")
        assert item["ai_generated"] is True

    # The action in entry 4 names Nguyen explicitly and has a resolvable deadline.
    action = next(a for a in memo["action_items"] if a["sources"][0]["sequence"] == 4)
    assert action["owner_text"] == "Nguyen An"
    assert action["due_text"] == "来週金曜日"
    assert action["due_date"] == "2026-10-23"  # meeting on Wed 2026-10-14 (JST)
    assert action["status"] == "open"

    # Export is blocked before approval
    assert pm.get(f"/memos/{memo['id']}/export").status_code == 409

    # Edit memo
    r = pm.put(f"/memos/{memo['id']}", json={"executive_summary": "Đã thống nhất giao diện dạng tab."})
    assert r.status_code == 200, r.text
    assert r.json()["executive_summary"] == "Đã thống nhất giao diện dạng tab."

    # Add a manual decision (human-entered => confirmed)
    r = pm.post(
        f"/memos/{memo['id']}/decisions",
        json={"statement": "Giữ nguyên lịch UAT 28/10", "source_entry_ids": [entries[5]["id"]]},
    )
    assert r.status_code == 201, r.text
    manual = next(d for d in r.json()["decisions"] if not d["ai_generated"])
    assert manual["verification_status"] == "confirmed"

    # Submit, approve
    assert pm.post(f"/memos/{memo['id']}/submit").json()["status"] == "in_review"
    r = pm.post(f"/memos/{memo['id']}/approve", json={"comment": "OK"})
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["status"] == "approved"
    assert approved["reviewed_by_id"] == pm.user["id"]
    assert pm.get(f"/meetings/{meeting['id']}").json()["status"] == "completed"

    # Content edits are locked after approval
    assert pm.put(f"/memos/{memo['id']}", json={"executive_summary": "x"}).status_code == 409

    # Confirm an action item and track it (allowed after approval)
    r = pm.patch(f"/action-items/{action['id']}", json={"verification_status": "confirmed", "status": "in_progress"})
    assert r.status_code == 200, r.text
    tracked = pm.get("/action-items", params={"meeting_id": meeting["id"]}).json()["items"]
    row = next(a for a in tracked if a["id"] == action["id"])
    assert row["verification_status"] == "confirmed"
    assert row["status"] == "in_progress"
    assert row["meeting_title"] == meeting["title"]

    # Export approved memo in all formats
    md = pm.get(f"/memos/{memo['id']}/export", params={"format": "md"})
    assert md.status_code == 200
    assert "## D." in md.text and "Giữ nguyên lịch UAT 28/10" in md.text
    html = pm.get(f"/memos/{memo['id']}/export", params={"format": "html"})
    assert html.status_code == 200 and html.text.startswith("<!doctype html>")
    js = pm.get(f"/memos/{memo['id']}/export", params={"format": "json"})
    assert js.status_code == 200 and js.json()["status"] == "approved"

    # Meeting record export
    csv = pm.get(f"/meetings/{meeting['id']}/export", params={"format": "csv"})
    assert csv.status_code == 200 and "original_text" in csv.text

    # Usage recorded for AI operations
    usage = pm.get("/usage/summary").json()
    ops = {o["operation"] for o in usage["by_operation"]}
    assert {"translation", "memo_generation"} <= ops
    assert "Estimated" in usage["cost_note"]

    # History lists the meeting with its memo status
    hist = pm.get("/meetings", params={"q": "Sprint 14", "memo_status": "approved"}).json()
    assert hist["total"] == 1 and hist["items"][0]["memo_status"] == "approved"

    # Dashboard figures derive from the data
    dash = pm.get("/dashboard", params={"project_id": project["id"]}).json()
    assert dash["total_meetings"] == 1
    assert dash["open_action_items"] >= 1


def test_reopen_and_regenerate(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"], "en_steering_meeting.srt")
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    pm.post(f"/memos/{memo['id']}/approve")
    assert pm.post(f"/meetings/{meeting['id']}/memo/generate").status_code == 409
    assert pm.post(f"/memos/{memo['id']}/reopen").json()["status"] == "draft"
    assert pm.post(f"/meetings/{meeting['id']}/memo/generate").status_code == 202
    run_jobs()
    again = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert again["generation_count"] == 2
    assert again["status"] == "draft"


def test_reject_then_edit_returns_to_draft(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"], "vi_internal_meeting.txt")
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    r = pm.post(f"/memos/{memo['id']}/reject", json={"comment": "Thiếu thông tin"})
    assert r.json()["status"] == "rejected"
    assert r.json()["review_comment"] == "Thiếu thông tin"
    r = pm.put(f"/memos/{memo['id']}", json={"executive_summary": "Bổ sung"})
    assert r.json()["status"] == "draft"
