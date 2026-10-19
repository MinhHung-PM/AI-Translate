"""AUTH_MODE=shared: no sign-in, one shared team account, AI keys from the server."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings

SERVER_KEY = "sk-server-0123456789abcdef"


@pytest.fixture
def shared(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "shared")
    monkeypatch.setattr(s, "openai_api_key", SERVER_KEY)
    monkeypatch.setattr(s, "soniox_api_key", "")
    from app.main import app

    return TestClient(app)


def _me(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_visitors_are_signed_in_automatically_as_the_shared_account(shared):
    first = _me(shared)
    assert first["auth_mode"] == "shared" and first["features"]["shared_mode"] is True
    assert first["features"]["server_openai"] is True and first["features"]["server_soniox"] is False
    assert first["user"]["email"] == "team@memohub.local" and first["user"]["role"] == "project_manager"
    assert SERVER_KEY not in str(first)
    again = _me(shared)  # the cookie is reused, not a new session per request
    assert again["csrf_token"] == first["csrf_token"]
    other_browser = TestClient(shared.app)
    assert _me(other_browser)["user"]["id"] == first["user"]["id"]  # everyone shares the account

    # A ready-to-use project exists from the first visit.
    projects = shared.get("/api/v1/projects").json()["items"]
    assert [p["code"] for p in projects] == ["CHUNG"] and projects[0]["permissions"]["contribute"] is True

    h = {"X-CSRF-Token": first["csrf_token"]}
    r = shared.post("/api/v1/projects", headers=h, json={"code": "TEAM1", "name": "Dự án nhóm"})
    assert r.status_code == 201, r.text
    assert any(p["code"] == "TEAM1" for p in shared.get("/api/v1/projects").json()["items"])


def test_ai_settings_are_managed_on_the_server(shared, db):
    from sqlalchemy import select

    from app.models import User
    from app.services.audio_capture import resolve_soniox, resolve_stt
    from app.services.provider_config import resolve_provider

    me = _me(shared)
    h = {"X-CSRF-Token": me["csrf_token"]}
    r = shared.put(
        "/api/v1/providers/configs",
        headers=h,
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": "sk-user-0123456789", "remember": True},
    )
    assert r.status_code == 403
    user = db.scalar(select(User).where(User.email == "team@memohub.local"))
    resolved = resolve_provider(db, user.id, None)
    assert resolved.key_source == "server" and resolved.credentials.api_key == SERVER_KEY
    assert resolved.model == "gpt-4.1-mini"
    stt, source = resolve_stt(db, user.id, None)
    assert source == "server" and not stt.is_mock
    with pytest.raises(Exception, match="SONIOX_API_KEY"):
        resolve_soniox(db, user.id, None)


def test_server_key_is_a_fallback_for_users_without_their_own(monkeypatch, db, member):
    from sqlalchemy import select

    from app.models import AIProviderConfiguration, User
    from app.services.provider_config import resolve_provider

    user = db.scalar(select(User).where(User.email == "member@example.com"))
    db.query(AIProviderConfiguration).filter_by(user_id=user.id).delete()
    db.commit()
    with pytest.raises(Exception, match="No AI provider"):
        resolve_provider(db, user.id, None)
    monkeypatch.setattr(get_settings(), "openai_api_key", SERVER_KEY)
    resolved = resolve_provider(db, user.id, None)
    assert resolved.key_source == "server" and resolved.credentials.api_key == SERVER_KEY


def test_shared_mode_in_production_requires_the_server_key():
    base = {
        "environment": "production",
        "auth_mode": "shared",
        "trusted_hosts": ["10.0.0.5"],
        "enable_mock_provider": False,
        "session_cookie_secure": True,
        "secret_encryption_keys": "k1:qxdSuIFZbk90ZEi6UGxEMk9m9AoX7n+Vw2PnnAejq10=",
    }
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        Settings(**base).validate_for_environment()
    Settings(**base, openai_api_key=SERVER_KEY).validate_for_environment()


def test_other_modes_still_require_sign_in(pm):
    from app.main import app

    assert TestClient(app).get("/api/v1/auth/me").status_code == 401
