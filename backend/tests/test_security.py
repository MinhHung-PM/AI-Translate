"""Security tests: authentication, CSRF, project isolation, role checks,
upload validation, API-key handling, prompt injection and provider errors."""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import select

from app.ai.base import MemoGenerationResult, ProviderError, ProviderErrorCode, TokenUsage
from app.models import AIProviderConfiguration, AuditEvent, SessionSecret
from tests.conftest import ApiClient, create_meeting, run_jobs, upload_sample

SECRET_KEY = "sk-live-VERYSECRET-0123456789abcdef"


@pytest.fixture
def alpha_meeting(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    return meeting


# ---- Authentication & CSRF ------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/meetings/00000000-0000-0000-0000-000000000000/translations"),
        ("post", "/meetings/00000000-0000-0000-0000-000000000000/memo/generate"),
        ("post", "/providers/configs/00000000-0000-0000-0000-000000000000/test"),
        ("get", "/meetings"),
        ("get", "/dashboard"),
        ("get", "/action-items"),
        ("get", "/admin/users"),
    ],
)
def test_unauthenticated_requests_are_rejected(method, path):
    anon = ApiClient(None)
    r = getattr(anon, method)(path, json={}) if method != "get" else anon.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


def test_csrf_token_required_for_mutations(pm):
    pid = pm.get("/projects").json()["items"][0]["id"]
    r = pm.client.post("/api/v1/meetings", json={"project_id": pid}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = pm.client.post("/api/v1/meetings", json={"project_id": pid})
    assert r.status_code == 403


def test_logout_invalidates_session(pm):
    assert pm.post("/auth/logout").status_code == 204
    assert pm.get("/auth/me").status_code == 401


def test_dev_login_disabled_outside_dev_mode(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_mode", "oidc")
    anon = ApiClient(None)
    assert anon.client.post("/api/v1/auth/dev/login", json={"email": "admin@example.com"}).status_code == 404
    assert anon.get("/auth/dev/users").status_code == 404


def test_production_config_rejects_dev_auth():
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="AUTH_MODE=dev"):
        Settings(environment="production", auth_mode="dev").validate_for_environment()


# ---- Cross-project isolation -------------------------------------------------------


def test_outsider_cannot_access_other_project(outsider, alpha_meeting, pm):
    mid = alpha_meeting["id"]
    memo = pm.get(f"/meetings/{mid}/memo").json()
    for path in [
        f"/meetings/{mid}",
        f"/meetings/{mid}/transcript",
        f"/meetings/{mid}/memo",
        f"/meetings/{mid}/export",
        f"/memos/{memo['id']}/export",
        f"/meetings/{mid}/live",
    ]:
        assert outsider.get(path).status_code == 404, path
    assert outsider.post(f"/meetings/{mid}/translations", json={}).status_code == 404
    assert outsider.post(f"/meetings/{mid}/memo/generate").status_code == 404
    action_id = memo["action_items"][0]["id"]
    assert outsider.patch(f"/action-items/{action_id}", json={"status": "done"}).status_code == 404
    assert outsider.put(f"/memos/{memo['id']}", json={"executive_summary": "x"}).status_code == 404
    # Lists never leak other projects' data
    assert outsider.get("/meetings").json()["total"] == 0
    assert outsider.get("/action-items").json()["total"] == 0
    assert all(p["code"] != "ALPHA" for p in outsider.get("/projects").json()["items"])
    dash = outsider.get("/dashboard").json()
    assert dash["total_meetings"] == 0 and dash["recent_activity"] == []
    assert outsider.get("/usage/summary").json()["total_requests"] == 0


def test_source_refs_cannot_point_to_other_meetings(pm, alpha_meeting, outsider):
    other = create_meeting(outsider, "BETA")
    upload_sample(outsider, other["id"], "en_steering_meeting.srt")
    foreign_entry = outsider.get(f"/meetings/{other['id']}/transcript").json()["items"][0]["id"]
    memo = pm.get(f"/meetings/{alpha_meeting['id']}/memo").json()
    r = pm.post(f"/memos/{memo['id']}/decisions", json={"statement": "x", "source_entry_ids": [foreign_entry]})
    assert r.status_code == 422


def test_member_cannot_approve_or_edit_others_meetings(member, alpha_meeting, pm):
    memo = pm.get(f"/meetings/{alpha_meeting['id']}/memo").json()
    assert member.get(f"/meetings/{alpha_meeting['id']}/memo").status_code == 200  # can view
    assert member.post(f"/memos/{memo['id']}/approve").status_code == 403
    # Member did not create the meeting => cannot edit it
    assert member.put(f"/memos/{memo['id']}", json={"executive_summary": "x"}).status_code == 403
    assert member.post(f"/meetings/{alpha_meeting['id']}/translations", json={}).status_code == 403


def test_member_edits_own_meeting_but_cannot_approve(member):
    meeting = create_meeting(member)
    upload_sample(member, meeting["id"], "vi_internal_meeting.txt")
    member.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = member.get(f"/meetings/{meeting['id']}/memo").json()
    assert member.put(f"/memos/{memo['id']}", json={"executive_summary": "ok"}).status_code == 200
    assert member.post(f"/memos/{memo['id']}/submit").status_code == 200
    assert member.post(f"/memos/{memo['id']}/approve").status_code == 403


def test_member_cannot_create_projects(member):
    assert member.post("/projects", json={"code": "X1", "name": "x"}).status_code == 403


def test_division_manager_sees_summary_but_not_transcript(divmgr, alpha_meeting):
    mid = alpha_meeting["id"]
    memo = divmgr.get(f"/meetings/{mid}/memo")
    assert memo.status_code == 200
    sources = [s for d in memo.json()["decisions"] for s in d["sources"]]
    assert sources and all(s["excerpt"] is None for s in sources)
    assert divmgr.get(f"/meetings/{mid}/transcript").status_code == 403
    assert divmgr.get(f"/meetings/{mid}/export").status_code == 403
    assert divmgr.post(f"/meetings/{mid}/memo/generate").status_code == 403
    assert divmgr.get("/meetings").json()["total"] == 1
    assert divmgr.get("/usage/summary").json()["total_requests"] >= 1


def test_division_manager_with_explicit_transcript_permission(divmgr, admin, alpha_meeting, db):
    from app.models import DivisionAssignment

    row = db.scalar(select(DivisionAssignment))
    r = admin.put(
        "/admin/division-assignments",
        json={"user_id": str(row.user_id), "division_id": str(row.division_id), "can_view_transcripts": True},
    )
    assert r.status_code == 200
    assert divmgr.get(f"/meetings/{alpha_meeting['id']}/transcript").status_code == 200


def test_admin_cannot_read_meeting_content(admin, alpha_meeting):
    assert admin.get(f"/meetings/{alpha_meeting['id']}").status_code == 404
    assert admin.get(f"/meetings/{alpha_meeting['id']}/transcript").status_code == 404
    assert admin.get("/admin/audit-events").status_code == 200
    assert any(p["code"] == "ALPHA" for p in admin.get("/projects").json()["items"])  # metadata only


def test_non_admin_cannot_use_admin_endpoints(pm):
    assert pm.get("/admin/users").status_code == 403
    assert pm.get("/admin/audit-events").status_code == 403
    assert pm.post("/admin/retention/run").status_code == 403


# ---- Upload validation ----------------------------------------------------------------


def test_invalid_uploads_rejected(pm):
    meeting = create_meeting(pm)
    url = f"/meetings/{meeting['id']}/transcript/upload"
    cases = [
        ("evil.exe", b"MZ\x90\x00"),
        ("bad.vtt", b"not a vtt file"),
        ("bad.srt", b"1\nnope\ntext"),
        ("bin.txt", b"\x00\x01\x02\x03"),
        ("empty.txt", b""),
        ("bad.json", b'{"schema_version": "2.0", "entries": []}'),
    ]
    for name, data in cases:
        r = pm.post(url, files={"file": (name, data)})
        assert r.status_code == 422, (name, r.text)
    assert pm.get(f"/meetings/{meeting['id']}").json()["entry_count"] == 0


def test_oversized_upload_rejected(pm, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1024)
    meeting = create_meeting(pm)
    r = pm.post(f"/meetings/{meeting['id']}/transcript/upload", files={"file": ("big.txt", b"a: b\n" * 1000)})
    assert r.status_code == 413
    r = pm.post(f"/meetings/{meeting['id']}/transcript/text", json={"text": "x" * 2000})
    assert r.status_code == 413


def test_path_traversal_filename_is_sanitized(pm):
    meeting = create_meeting(pm)
    r = pm.post(
        f"/meetings/{meeting['id']}/transcript/upload", files={"file": ("../../../etc/passwd.txt", b"A: hello there")}
    )
    assert r.status_code == 201
    assert r.json()["filename"] == "passwd.txt"


def test_replace_requires_explicit_flag(pm):
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    assert upload_sample(pm, meeting["id"]).status_code == 409
    assert upload_sample(pm, meeting["id"], "vi_internal_meeting.txt", replace=True).status_code == 201


# ---- API key handling -----------------------------------------------------------------


def test_api_key_never_returned_or_logged(pm, db, caplog):
    caplog.set_level(logging.DEBUG)
    r = pm.put(
        "/providers/configs",
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": SECRET_KEY, "remember": True},
    )
    assert r.status_code == 200, r.text
    assert SECRET_KEY not in r.text
    body = r.json()
    assert body["key_storage"] == "persistent" and body["key_hint"] == "…cdef" and body["has_usable_key"]
    listing = pm.get("/providers/configs")
    assert SECRET_KEY not in listing.text
    stored = db.scalar(select(AIProviderConfiguration).where(AIProviderConfiguration.provider == "openai"))
    assert stored.encrypted_api_key and SECRET_KEY not in stored.encrypted_api_key
    assert stored.encrypted_api_key.startswith("v1.ktest.")
    audit = db.scalars(select(AuditEvent).where(AuditEvent.action == "provider.config_save")).all()
    assert audit and all(SECRET_KEY not in json.dumps(a.details) for a in audit)
    assert SECRET_KEY not in caplog.text


def test_session_only_key_is_destroyed_at_logout(login, db):
    client = login("member@example.com")
    r = client.put(
        "/providers/configs",
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": SECRET_KEY, "remember": False},
    )
    assert r.json()["key_storage"] == "session" and r.json()["has_usable_key"]
    assert db.scalar(select(SessionSecret)) is not None
    client.post("/auth/logout")
    db.expire_all()
    assert db.scalar(select(SessionSecret)) is None
    # A new session does not have the key.
    again = login("member@example.com")
    cfg = next(c for c in again.get("/providers/configs").json() if c["provider"] == "openai")
    assert cfg["has_usable_key"] is False


def test_key_removal(pm, db):
    cfg = pm.put(
        "/providers/configs",
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": SECRET_KEY, "remember": True},
    ).json()
    r = pm.delete(f"/providers/configs/{cfg['id']}/key")
    assert r.json()["key_storage"] == "none" and r.json()["has_usable_key"] is False
    db.expire_all()
    stored = db.get(AIProviderConfiguration, cfg["id"])
    assert stored.encrypted_api_key is None and stored.key_hint is None


def test_remember_disabled_without_keyring(pm, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_persistent_api_keys", False)
    r = pm.put(
        "/providers/configs",
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": SECRET_KEY, "remember": True},
    )
    assert r.status_code == 409
    assert pm.get("/providers").json()["remember_key_supported"] is False


def test_custom_base_url_ssrf_blocked(pm):
    r = pm.put(
        "/providers/configs",
        json={
            "provider": "openai_compatible",
            "model": "llama",
            "base_url": "http://169.254.169.254/latest",
            "api_key": SECRET_KEY,
        },
    )
    assert r.status_code == 422


def test_users_cannot_touch_other_users_provider_configs(pm, member):
    cfg = pm.get("/providers/configs").json()[0]
    assert member.post(f"/providers/configs/{cfg['id']}/test").status_code == 404
    assert member.delete(f"/providers/configs/{cfg['id']}/key").status_code == 404


def test_missing_key_gives_clear_error_not_fabrication(pm):
    pm.put("/providers/configs", json={"provider": "openai", "model": "gpt-4.1-mini", "make_default": True})
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    job = pm.post(f"/meetings/{meeting['id']}/memo/generate").json()
    run_jobs()
    job = pm.get(f"/jobs/{job['id']}").json()
    assert job["status"] == "failed" and job["error_code"] == "provider_not_configured"
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["status"] == "failed" and memo["decisions"] == [] and memo["executive_summary"] == ""


# ---- Prompt injection & malformed provider output -----------------------------------------


def test_prompt_injection_content_stays_data(pm):
    meeting = create_meeting(pm, participants=[{"display_name": "Tanaka"}])
    upload_sample(pm, meeting["id"], "prompt_injection_test.txt")
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["status"] == "draft"  # never auto-approved
    assert all(d["verification_status"] != "confirmed" for d in memo["decisions"])
    assert "BEGIN" not in memo["executive_summary"]


def test_provider_obeying_injection_is_rejected_by_validator(pm, monkeypatch):
    """A compromised/misbehaving model that tries to approve the memo or
    exfiltrate data produces output the strict schema refuses."""

    class Hijacked:
        provider_key = "mock"
        model = "hijacked"

        def generate(self, request, *, repair_hint=None):
            raw = json.dumps({"status": "approved", "executive_summary": "leaked", "system_prompt": "..."})
            return MemoGenerationResult(raw_json=raw, usage=TokenUsage(1, 1, False), model=self.model)

    monkeypatch.setattr("app.services.memo_generation.memo_provider", lambda *a, **k: Hijacked())
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"], "prompt_injection_test.txt")
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    memo = pm.get(f"/meetings/{meeting['id']}/memo").json()
    assert memo["status"] == "failed"
    assert "invalid memo output" in memo["generation_error"]
    usage = pm.get("/usage/summary").json()
    assert any(o["operation"] == "memo_generation" and o["failed"] >= 1 for o in usage["by_operation"])


def test_owner_hallucination_is_removed(pm, monkeypatch):
    class Inventor:
        provider_key = "mock"
        model = "inventor"

        def generate(self, request, *, repair_hint=None):
            raw = json.dumps(
                {
                    "executive_summary": "s",
                    "action_items": [
                        {"description": "Fix bug", "owner": "Yamada", "due_text": "next Monday", "source_refs": [1]}
                    ],
                }
            )
            return MemoGenerationResult(raw_json=raw, usage=TokenUsage(1, 1, False), model=self.model)

    monkeypatch.setattr("app.services.memo_generation.memo_provider", lambda *a, **k: Inventor())
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"], "prompt_injection_test.txt")
    pm.post(f"/meetings/{meeting['id']}/memo/generate")
    run_jobs()
    action = pm.get(f"/meetings/{meeting['id']}/memo").json()["action_items"][0]
    assert action["owner_text"] is None  # "Yamada" never appears in the cited line
    assert action["due_date"] is None and action["due_needs_confirmation"] is True
    assert action["verification_status"] == "needs_review"
    assert "Yamada" in action["review_note"]


def test_translation_provider_failure_marks_entries_failed_and_retry_works(pm, monkeypatch):
    class Failing:
        provider_key = "mock"
        model = "x"

        def translate(self, request):
            raise ProviderError(ProviderErrorCode.unavailable, "Provider error 503", retryable=True)

    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    monkeypatch.setattr("app.services.translation.translation_provider", lambda *a, **k: Failing())
    job = pm.post(f"/meetings/{meeting['id']}/translations", json={}).json()
    run_jobs()
    job = pm.get(f"/jobs/{job['id']}").json()
    assert job["status"] == "failed" and "503" in job["error_message"]
    stats = pm.get(f"/meetings/{meeting['id']}/transcript/stats").json()
    assert stats["failed"] == 8
    entry = pm.get(f"/meetings/{meeting['id']}/transcript").json()["items"][0]
    assert entry["translation"]["status"] == "failed" and entry["translation"]["text"] is None

    monkeypatch.undo()
    pm.post(f"/meetings/{meeting['id']}/translations", json={"only_failed": True})
    run_jobs()
    assert pm.get(f"/meetings/{meeting['id']}/transcript/stats").json()["done"] == 8


def test_rate_limit_on_ai_endpoints(pm, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ai_rate_limit_per_minute", 2)
    meeting = create_meeting(pm)
    upload_sample(pm, meeting["id"])
    codes = []
    for _ in range(3):
        codes.append(pm.post(f"/meetings/{meeting['id']}/translations", json={}).status_code)
        run_jobs()
    assert codes == [202, 202, 429]


def test_security_headers(pm):
    r = pm.get("/auth/me")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    cookie = (
        ApiClient(None).client.post("/api/v1/auth/dev/login", json={"email": "pm@example.com"}).headers["set-cookie"]
    )
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_csv_export_neutralizes_formulas(pm):
    meeting = create_meeting(pm)
    pm.post(f"/meetings/{meeting['id']}/transcript/text", json={"text": 'A: =HYPERLINK("http://x")'})
    csv = pm.get(f"/meetings/{meeting['id']}/export", params={"format": "csv"}).text
    assert "'=HYPERLINK" in csv
