"""Unit + contract tests for the integration framework (no network)."""

from __future__ import annotations

import hashlib
import hmac
import random
from datetime import timedelta

import httpx
import pytest

from app.integrations.base import ResolvedMeeting
from app.integrations.capabilities import Capability, CapabilityStatus
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.http import ProviderHttp, default_error, parse_retry_after, provider_error_code
from app.integrations.models import CanonicalEvent, EventType
from app.integrations.normalization.event_deduplicator import dedup_key
from app.integrations.normalization.ordering import OrderingBuffer, sort_events
from app.integrations.normalization.transcript_normalizer import events_from_vtt, language_from_code, offset_ms
from app.integrations.oauth import classify_authorization_error, mark_error, mark_success
from app.integrations.orchestration.recovery_service import backoff_delay, next_attempt_at
from app.integrations.registry import all_connectors, get_connector
from app.integrations.zoom import webhook as zw
from app.integrations.zoom.connector import encode_meeting_uuid, parse_meeting_id
from app.models import PlatformConnection
from app.models.enums import ConnectionState
from tests.fakes import fake_providers as fp


def ev(**kw):
    return CanonicalEvent(provider="zoom", provider_meeting_id="m1", original_text="はい。", **kw)


# ---- capabilities -----------------------------------------------------------


@pytest.mark.parametrize("provider", ["teams", "zoom", "google_meet"])
def test_every_connector_declares_every_capability(provider):
    caps = get_connector(provider).get_capabilities(set(), connected=False)
    assert {c.capability for c in caps} == set(Capability)
    assert all(c.message for c in caps)
    assert next(c for c in caps if c.capability == Capability.transcript_import).status == CapabilityStatus.available


def test_live_never_available_for_teams_and_meet_even_with_all_scopes(fake):
    for provider in ("teams", "google_meet"):
        caps = get_connector(provider).get_capabilities({"x", "OnlineMeetingTranscript.Read.All"}, connected=True)
        assert (
            next(c for c in caps if c.capability == Capability.live_transcript).status == CapabilityStatus.not_supported
        )
        assert next(c for c in caps if c.capability == Capability.live_audio).status == CapabilityStatus.not_supported


def test_teams_scope_driven_capabilities(fake):
    teams = get_connector("teams")
    without = {c.capability: c for c in teams.get_capabilities({"Calendars.Read"}, True)}
    assert without[Capability.post_meeting_transcript].status == CapabilityStatus.requires_admin_approval
    full = {
        c.capability: c
        for c in teams.get_capabilities(
            {"https://graph.microsoft.com/OnlineMeetingTranscript.Read.All", "Calendars.Read"}, True
        )
    }
    assert full[Capability.post_meeting_transcript].status == CapabilityStatus.available
    assert full[Capability.list_meetings].status == CapabilityStatus.available


def test_zoom_live_requires_operator_configuration(fake, monkeypatch):
    from app.core.config import get_settings

    zoom = get_connector("zoom")
    assert {c.capability: c for c in zoom.get_capabilities(set(), True)}[
        Capability.live_transcript
    ].status == CapabilityStatus.available
    monkeypatch.setattr(get_settings(), "zoom_webhook_secret_token", "")
    caps = {c.capability: c for c in zoom.get_capabilities(set(), True)}
    assert caps[Capability.live_transcript].status == CapabilityStatus.requires_configuration
    assert "ZOOM_WEBHOOK_SECRET_TOKEN" in caps[Capability.live_transcript].message
    monkeypatch.setattr(get_settings(), "zoom_webhook_secret_token", "zoom-webhook-secret")
    monkeypatch.setattr("app.integrations.zoom.connector.rtms_sdk_available", lambda: False)
    caps = {c.capability: c for c in zoom.get_capabilities(set(), True)}
    assert caps[Capability.live_transcript].status == CapabilityStatus.requires_configuration
    assert "rtms" in caps[Capability.live_transcript].message


# ---- dedup / ordering / normalization ------------------------------------------------


def test_dedup_key_priority_and_legitimate_repeats():
    assert dedup_key(ev(entry_id="a")) == dedup_key(ev(entry_id="a", start_timestamp_ms=5))
    assert dedup_key(ev(entry_id="a")) != dedup_key(ev(entry_id="b"))
    assert dedup_key(ev(provider_sequence=3)) != dedup_key(ev(provider_sequence=4))
    # Same text at different times or by different speakers is NOT a duplicate.
    assert dedup_key(ev(start_timestamp_ms=1000, speaker_id="u1")) != dedup_key(
        ev(start_timestamp_ms=2000, speaker_id="u1")
    )
    assert dedup_key(ev(start_timestamp_ms=1000, speaker_id="u1")) != dedup_key(
        ev(start_timestamp_ms=1000, speaker_id="u2")
    )
    assert dedup_key(ev()) is None  # nothing stable → accept rather than risk dropping
    other_meeting = CanonicalEvent(provider="zoom", provider_meeting_id="m2", original_text="x", entry_id="a")
    assert dedup_key(ev(entry_id="a")) != dedup_key(other_meeting)


def test_sort_events_tolerates_out_of_order_and_missing_times():
    events = [
        ev(start_timestamp_ms=3000),
        ev(start_timestamp_ms=None, provider_sequence=1),
        ev(start_timestamp_ms=1000),
    ]
    assert [e.start_timestamp_ms for e in sort_events(events)] == [1000, 3000, None]


def test_ordering_buffer_bounded_and_marks_late_events():
    now = [0.0]
    buf = OrderingBuffer(max_items=3, max_delay_s=1.0, clock=lambda: now[0])
    assert buf.add(ev(start_timestamp_ms=200, entry_id="2")) == []
    assert buf.add(ev(start_timestamp_ms=100, entry_id="1")) == []
    now[0] = 1.5
    released = buf.release()
    assert [e.start_timestamp_ms for e in released] == [100, 200]
    late = buf.add(ev(start_timestamp_ms=50, entry_id="0"))
    late += buf.flush()
    assert late[0].source_metadata.get("late") is True  # released, not dropped
    for i in range(10):
        buf.add(ev(start_timestamp_ms=1000 + i, entry_id=f"x{i}"))
    assert len(buf) <= 3  # memory bound


def test_events_from_teams_vtt_and_unattributed():
    events = events_from_vtt(fp.TEAMS_VTT, provider="teams", provider_meeting_id="m", transcript_id="t")
    assert [e.speaker_display_name for e in events] == ["田中 太郎", "Nguyen An", "田中 太郎", "Nguyen An"]
    assert events[0].entry_id == "t:0a3b9f21-1c2d-4e5f-8a9b-0c1d2e3f4a5b/12-0"
    assert events[0].start_timestamp_ms == 2120 and events[0].source_language.value == "ja"
    plain = events_from_vtt(fp.TEAMS_UNATTRIBUTED, provider="teams", provider_meeting_id="m", transcript_id="t")
    assert all(e.speaker_display_name is None for e in plain)


def test_language_and_offsets():
    from datetime import UTC, datetime

    assert language_from_code("ja-JP").value == "ja" and language_from_code("vi").value == "vi"
    assert language_from_code("fr-FR") is None and language_from_code(None) is None
    origin = datetime(2026, 10, 15, 1, 0, tzinfo=UTC)
    assert offset_ms("2026-10-15T01:00:02.500Z", origin) == 2500
    assert offset_ms(None, origin) is None and offset_ms("2026-10-15T01:00:00Z", None) is None


# ---- contract: every connector emits the canonical event format -------------------------


@pytest.mark.parametrize(
    ("provider", "reference"),
    [
        ("teams", fp.TEAMS_JOIN_URL),
        ("zoom", fp.ZOOM_MEETING_ID),
        ("google_meet", fp.MEET_CODE),
    ],
)
def test_connectors_emit_canonical_events(fake, provider, reference):
    connector = get_connector(provider)
    token = {"teams": "teams", "zoom": "zoom", "google_meet": "google"}[provider]
    tokens = fake._tokens(token, "x")
    access = tokens["access_token"]
    resolved = connector.resolve_meeting(access, reference)
    result = connector.fetch_transcript(
        access, ResolvedMeeting(resolved.provider_meeting_id, resolved.join_url, resolved.title, resolved.resolved_ids)
    )
    assert result.events
    for e in result.events:
        assert isinstance(e, CanonicalEvent)
        assert e.provider == provider and e.event_type == EventType.transcript_segment
        assert e.provider_meeting_id == resolved.provider_meeting_id and e.entry_id and e.original_text
        assert dedup_key(e) is not None  # every provider event is deduplicable
        CanonicalEvent.model_validate(e.model_dump())  # round-trips under the strict schema


# ---- errors / http ------------------------------------------------------------------


def test_error_mapping_is_safe():
    secret_body = {"error": {"code": "Forbidden", "message": "token=eyJsecret leaked", "innerError": {"code": "X1"}}}
    err = default_error(httpx.Response(403, json=secret_body))
    assert err.category == ErrorCategory.insufficient_scope and "eyJ" not in err.message and err.provider_code == "X1"
    r429 = default_error(httpx.Response(429, json={}, headers={"Retry-After": "42"}))
    assert r429.category == ErrorCategory.rate_limited and r429.retry_after == 42 and r429.retryable
    assert parse_retry_after("bogus") is None and parse_retry_after("99999") == 3600
    assert provider_error_code(httpx.Response(400, json={"error": "invalid_grant"})) == "invalid_grant"
    assert provider_error_code(httpx.Response(400, json={"code": 4711, "message": "x"})) == "4711"
    assert provider_error_code(httpx.Response(400, json={"error": {"code": "has spaces & stuff"}})) is None


def test_provider_http_timeouts_are_normalized():
    from app.integrations.http import set_transport_override

    def boom(request):
        raise httpx.ConnectTimeout("slow")

    set_transport_override(httpx.MockTransport(boom))
    try:
        with pytest.raises(IntegrationError) as exc:
            ProviderHttp().request("GET", "https://example.test/x")
        assert exc.value.category == ErrorCategory.provider_unavailable and exc.value.retryable
    finally:
        set_transport_override(None)


def test_authorization_error_classification():
    assert (
        classify_authorization_error("consent_required", "AADSTS65001: not consented").category
        == ErrorCategory.admin_approval_required
    )
    assert classify_authorization_error("access_denied", "The user denied").category == ErrorCategory.consent_revoked
    assert classify_authorization_error("server_error", "").category == ErrorCategory.invalid_request


# ---- retry policy ---------------------------------------------------------------------


def test_backoff_bounded_with_jitter():
    rng = random.Random(1)
    delays = [backoff_delay(a, base=10, cap=100, rng=rng) for a in range(1, 10)]
    assert all(0 < d <= 100 for d in delays)
    assert 5 <= delays[0] <= 10 and delays[-1] >= 50


def test_next_attempt_respects_budget_permanence_and_retry_after():
    from app.db.base import utcnow

    assert next_attempt_at(1) is not None
    assert next_attempt_at(99) is None  # attempt budget exhausted
    assert next_attempt_at(1, IntegrationError(ErrorCategory.admin_approval_required, "x")) is None
    when = next_attempt_at(1, IntegrationError(ErrorCategory.rate_limited, "x", retry_after=3000))
    assert when is not None and when - utcnow() >= timedelta(seconds=2990)


# ---- connection state transitions ---------------------------------------------------------


def test_connection_state_transitions():
    conn = PlatformConnection(state=ConnectionState.connected, reconnect_count=0)
    mark_error(conn, IntegrationError(ErrorCategory.provider_unavailable, "down"))
    assert conn.state == ConnectionState.temporarily_disconnected
    mark_success(conn)
    assert conn.state == ConnectionState.connected and conn.reconnect_count == 1
    mark_error(conn, IntegrationError(ErrorCategory.admin_approval_required, "x"))
    assert conn.state == ConnectionState.admin_approval_required
    mark_error(conn, IntegrationError(ErrorCategory.consent_revoked, "x"))
    assert conn.state == ConnectionState.error and conn.last_error_category == "consent_revoked"


# ---- Zoom specifics --------------------------------------------------------------------------


def test_zoom_meeting_id_parsing_and_uuid_encoding():
    assert parse_meeting_id("857 4606 5432") == "85746065432"
    assert parse_meeting_id("https://us02web.zoom.us/j/85746065432?pwd=abc") == "85746065432"
    for bad in ("https://zoom.evil.com/j/85746065432", "12", "https://example.com/j/85746065432"):
        with pytest.raises(IntegrationError):
            parse_meeting_id(bad)
    assert encode_meeting_uuid("/ajXp112QmuoKj4854875==") == "%252FajXp112QmuoKj4854875%253D%253D"
    assert encode_meeting_uuid("abc==") == "abc%3D%3D"


def test_zoom_webhook_signature(fake):
    raw = b'{"event":"x"}'
    ts = "1760000000000"
    sig = "v0=" + hmac.new(b"zoom-webhook-secret", f"v0:{ts}:{raw.decode()}".encode(), hashlib.sha256).hexdigest()
    zw.verify_signature(raw, ts, sig, now=1760000000.0)
    for bad_ts, bad_sig in ((ts, sig[:-1] + "0"), (ts, None), (None, sig), ("abc", sig)):
        with pytest.raises(IntegrationError):
            zw.verify_signature(raw, bad_ts, bad_sig, now=1760000000.0)
    with pytest.raises(IntegrationError):  # replay outside the tolerance window
        zw.verify_signature(raw, ts, sig, now=1760000000.0 + 3600)
    assert zw.dedup_key({"event": "a", "event_ts": 1}) != zw.dedup_key({"event": "a", "event_ts": 2})


def test_registry():
    assert {c.provider.value for c in all_connectors()} == {"teams", "zoom", "google_meet"}
    from app.core.errors import NotFound

    with pytest.raises(NotFound):
        get_connector("skype")


def test_malformed_endpoint_overrides_fail_fast():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="integration_endpoint_overrides"):
        Settings(integration_endpoint_overrides="{teams:http://fake}")
    with pytest.raises(ValidationError, match="integration_browser_endpoint_overrides"):
        Settings(integration_browser_endpoint_overrides="[1]")


def test_browser_authorize_override_only_in_sandbox(fake, monkeypatch):
    import urllib.parse

    from app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(), "integration_browser_endpoint_overrides", '{"zoom": "http://localhost:9100/zoom"}'
    )
    url = get_connector("zoom").begin_authorization("st", "ch", "http://localhost:3000/cb")
    assert url.startswith("http://localhost:9100/zoom/authorize?")
    assert urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"] == ["st"]
    # Token/API calls still use the server-side override.
    assert get_connector("zoom").endpoint("token") == "http://fake.local/zoom/token"
