"""Test fixtures: a real PostgreSQL database migrated with Alembic, the real
FastAPI app, the dev login, and inline execution of background jobs.
External AI providers are always mocked; no test makes a network call."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://memohub:memohub@localhost:5432/memohub_test"
        ),
        "AUTH_MODE": "dev",
        "SESSION_COOKIE_SECURE": "false",
        "SECRET_ENCRYPTION_KEYS": "ktest:" + base64.b64encode(b"t" * 32).decode(),
        "ENABLE_MOCK_PROVIDER": "true",
        "EMBEDDED_WORKER": "false",
        "AI_RATE_LIMIT_PER_MINUTE": "1000",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.rate_limit import rate_limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND.parent / "samples"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(alembic_config(), "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_db(migrated_db: None) -> Iterator[None]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    from app.seed import seed

    with get_sessionmaker()() as db:
        seed(db)
    rate_limiter.reset()
    yield


@pytest.fixture
def db() -> Iterator[Any]:
    with get_sessionmaker()() as session:
        yield session


class ApiClient:
    def __init__(self, email: str | None) -> None:
        from app.main import app

        self.client = TestClient(app)
        self.csrf = ""
        self.user: dict[str, Any] = {}
        if email:
            r = self.client.post("/api/v1/auth/dev/login", json={"email": email})
            assert r.status_code == 200, r.text
            self.csrf = r.json()["csrf_token"]
            self.user = r.json()["user"]

    def _h(self, headers: dict[str, str] | None) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf, **(headers or {})}

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get("/api/v1" + url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self.client.post("/api/v1" + url, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self.client.put("/api/v1" + url, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url: str, **kw: Any) -> Any:
        return self.client.patch("/api/v1" + url, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url: str, **kw: Any) -> Any:
        return self.client.delete("/api/v1" + url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture
def login() -> Any:
    return ApiClient


@pytest.fixture
def pm() -> ApiClient:
    return ApiClient("pm@example.com")


@pytest.fixture
def member() -> ApiClient:
    return ApiClient("member@example.com")


@pytest.fixture
def outsider() -> ApiClient:
    return ApiClient("outsider@example.com")


@pytest.fixture
def admin() -> ApiClient:
    return ApiClient("admin@example.com")


@pytest.fixture
def divmgr() -> ApiClient:
    return ApiClient("divmgr@example.com")


def run_jobs() -> int:
    from app.worker import run_pending

    return run_pending()


def project_id(client: ApiClient, code: str = "ALPHA") -> str:
    r = client.get("/projects", params={"q": code})
    assert r.status_code == 200, r.text
    return next(p["id"] for p in r.json()["items"] if p["code"] == code)


def create_meeting(client: ApiClient, code: str = "ALPHA", **overrides: Any) -> dict[str, Any]:
    body = {
        "project_id": project_id(client, code),
        "title": "Định nghĩa yêu cầu - Sprint 14",
        "meeting_type": "client_meeting",
        "scheduled_at": datetime(2026, 10, 14, 10, 0, tzinfo=UTC).isoformat(),
        "timezone": "Asia/Tokyo",
        "platform": "manual_import",
        "source_language": None,
        "target_language": "vi",
        "memo_language": "vi",
        "participants": [{"display_name": "田中"}, {"display_name": "Nguyen An"}, {"display_name": "佐藤"}],
        **overrides,
    }
    r = client.post("/meetings", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def upload_sample(client: ApiClient, meeting_id: str, name: str = "ja_client_meeting.vtt", **form: Any) -> Any:
    data = (SAMPLES / name).read_bytes()
    return client.post(
        f"/meetings/{meeting_id}/transcript/upload",
        files={"file": (name, data)},
        data={k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()},
    )


# ---- Workstream 2: fake platform providers (contract fixtures, no network) ----------


@pytest.fixture
def fake(monkeypatch: Any) -> Any:
    import httpx

    from app.core.config import get_settings
    from app.integrations.http import set_transport_override
    from tests.fakes.fake_providers import FakeProviders, overrides_json

    providers = FakeProviders()
    s = get_settings()
    for key, value in {
        "teams_client_id": "teams-client",
        "teams_client_secret": "fake-secret",
        "zoom_client_id": "zoom-client",
        "zoom_client_secret": "fake-secret",
        "zoom_webhook_secret_token": "zoom-webhook-secret",
        "zoom_rtms_enabled": True,
        "google_client_id": "google-client",
        "google_client_secret": "fake-secret",
        "integration_endpoint_overrides": overrides_json(providers.base_url),
        "public_base_url": "http://localhost:3000",
    }.items():
        monkeypatch.setattr(s, key, value)
    set_transport_override(httpx.MockTransport(providers.handle))
    yield providers
    set_transport_override(None)


def connect_platform(client: ApiClient, fake: Any, provider: str) -> Any:
    """Run the real OAuth flow against the fake provider: begin → provider redirect → callback."""
    import urllib.parse

    r = client.post(f"/integrations/{provider}/connect")
    assert r.status_code == 200, r.text
    url = urllib.parse.urlparse(r.json()["authorization_url"])
    params = dict(urllib.parse.parse_qsl(url.query))
    back = urllib.parse.urlparse(fake.authorize_redirect({"google_meet": "google"}.get(provider, provider), params))
    cb = client.client.get(f"{back.path}?{back.query}", follow_redirects=False)
    return cb, params
