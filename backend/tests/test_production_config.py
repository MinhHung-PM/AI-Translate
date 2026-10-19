"""Production hardening: who may sign in, required settings, internal hosts, first admin."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.auth import _allowed_identity
from app.core.config import Settings

BASE: dict[str, Any] = {
    "environment": "production",
    "auth_mode": "oidc",
    "oidc_issuer": "https://login.microsoftonline.com/t1/v2.0",
    "oidc_client_id": "c",
    "oidc_client_secret": "s",
    "oidc_redirect_uri": "https://memo.example.com/api/v1/auth/oidc/callback",
    "trusted_hosts": ["memo.example.com"],
    "enable_mock_provider": False,
    "session_cookie_secure": True,
    "secret_encryption_keys": "k1:qxdSuIFZbk90ZEi6UGxEMk9m9AoX7n+Vw2PnnAejq10=",
    "oidc_allowed_email_domains": ["company.com"],
}


def test_complete_production_settings_are_accepted():
    Settings(**BASE).validate_for_environment()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"oidc_allowed_email_domains": [], "oidc_allowed_tenant_ids": []}, "OIDC_ALLOWED_EMAIL_DOMAINS"),
        ({"secret_encryption_keys": ""}, "SECRET_ENCRYPTION_KEYS"),
        ({"trusted_hosts": ["*"]}, "TRUSTED_HOSTS"),
    ],
)
def test_production_refuses_open_or_incomplete_settings(override, message):
    with pytest.raises(RuntimeError, match=message):
        Settings(**{**BASE, **override}).validate_for_environment()


def test_allowed_identity_by_domain_and_tenant():
    domain_only = Settings(**BASE)
    assert _allowed_identity(domain_only, "an@company.com", {})
    assert not _allowed_identity(domain_only, "eve@gmail.com", {})
    assert not _allowed_identity(domain_only, "an@company.com", {"email_verified": False})
    assert not _allowed_identity(domain_only, "an@company.com", {"hd": "other.com"})  # Google Workspace domain
    tenant = Settings(**{**BASE, "oidc_allowed_email_domains": [], "oidc_allowed_tenant_ids": ["T1"]})
    assert _allowed_identity(tenant, "guest@partner.com", {"tid": "t1"})
    assert not _allowed_identity(tenant, "x@company.com", {"tid": "t2"})
    assert _allowed_identity(Settings(), "anyone@x.com", {})  # development: no allow-list


def test_internal_hosts_pass_the_trusted_host_check(monkeypatch):
    from app.core import config

    monkeypatch.setenv("TRUSTED_HOSTS", "memo.example.com")
    config.get_settings.cache_clear()
    try:
        from app.main import create_app

        client = TestClient(create_app())
        for host in ("api:8000", "127.0.0.1", "memo.example.com"):
            assert client.get("/api/v1/health/live", headers={"host": host}).status_code == 200, host
        assert client.get("/api/v1/health/live", headers={"host": "evil.example"}).status_code == 400
    finally:
        config.get_settings.cache_clear()


def test_make_admin_cli(db):
    from sqlalchemy import select

    from app.cli import main
    from app.models import User
    from app.models.enums import GlobalRole

    assert main(["make-admin", "nobody@nowhere.test"]) == 1
    assert main(["make-admin", "Member@Example.com"]) == 0
    db.expire_all()
    assert db.scalar(select(User).where(User.email == "member@example.com")).role == GlobalRole.admin


def test_unreachable_identity_provider_gives_a_clear_503(monkeypatch):
    import httpx

    from app.api.v1 import auth as auth_api
    from app.core import config

    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.invalid/tenant/v2.0")
    monkeypatch.setenv("OIDC_CLIENT_ID", "c")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://memo.example.com/api/v1/auth/oidc/callback")
    config.get_settings.cache_clear()

    def boom(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(auth_api.httpx, "get", boom)
    try:
        from app.main import create_app

        r = TestClient(create_app()).get("/api/v1/auth/oidc/login", follow_redirects=False)
        assert r.status_code == 503 and r.json()["error"]["code"] == "signin_unavailable"
    finally:
        config.get_settings.cache_clear()
