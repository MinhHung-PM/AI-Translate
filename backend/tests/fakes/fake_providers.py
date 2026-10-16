"""Fake Microsoft Graph / Zoom / Google Meet endpoints for contract tests.

DEVELOPMENT/TEST ONLY. Payload shapes follow the official references read on
2026-10-16 (microsoftgraph/microsoft-graph-docs-contrib, googleapis/googleapis
google/apps/meet/v2, Zoom recording + RTMS webhook payloads). The fake enforces
bearer tokens, PKCE (S256), HTTP Basic client auth for Zoom and refresh-token
rotation, and exposes failure scenarios (``FakeProviders.scenario``).

Usable as ``httpx.MockTransport(fake.handle)`` or served over HTTP
(``python -m tests.fakes.server``) for browser end-to-end tests. Connectors reach it
through ``INTEGRATION_ENDPOINT_OVERRIDES``, which marks every connection SANDBOX.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx

TEAMS_MEETING_ID = "MSo1N2Y5ZGFjYy03MWJmLTQ3NDMtYjQxMy01M2EdFGkdRWHJlQ"
TEAMS_JOIN_URL = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ABC123%40thread.v2/0?context=%7b%7d"
TEAMS_TRANSCRIPT_ID = "MSMjMCMjNzU3ODc2ZDYtOTcwMi00MDhkLWFkNDItOTE2ZDNmZjkwZGY4"
TEAMS_VTT = """WEBVTT

0a3b9f21-1c2d-4e5f-8a9b-0c1d2e3f4a5b/12-0
00:00:02.120 --> 00:00:06.430
<v 田中 太郎>本日は在庫引当の仕様を確認します。</v>

0a3b9f21-1c2d-4e5f-8a9b-0c1d2e3f4a5b/18-0
00:00:07.000 --> 00:00:12.900
<v Nguyen An>来週金曜日までに設計書を更新します。</v>

0a3b9f21-1c2d-4e5f-8a9b-0c1d2e3f4a5b/25-0
00:00:13.100 --> 00:00:15.000
<v 田中 太郎>はい。</v>

0a3b9f21-1c2d-4e5f-8a9b-0c1d2e3f4a5b/31-0
00:00:16.000 --> 00:00:17.500
<v Nguyen An>はい。</v>
"""
TEAMS_UNATTRIBUTED = """WEBVTT

00:00:02.120 --> 00:00:06.430
本日は在庫引当の仕様を確認します。

00:00:07.000 --> 00:00:12.900
来週金曜日までに設計書を更新します。
"""

ZOOM_MEETING_ID = "85746065432"
ZOOM_UUID = "4444AAAiAAAAAiAiAiiAii=="
ZOOM_VTT = """WEBVTT

1
00:00:01.500 --> 00:00:04.000
Sarah Johnson: Thanks everyone, let's confirm the release plan for version 2.0.

2
00:00:04.500 --> 00:00:09.000
Kenji Watanabe: We agreed to move the go-live date to November 15.
"""

MEET_CODE = "abc-mnop-xyz"
MEET_RECORD = "conferenceRecords/cr-7f3a9b"
MEET_TRANSCRIPT = f"{MEET_RECORD}/transcripts/tr-1"


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _json(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


@dataclass
class FakeProviders:
    client_ids: dict[str, str] = field(
        default_factory=lambda: {"teams": "teams-client", "zoom": "zoom-client", "google": "google-client"}
    )
    client_secret: str = "fake-secret"  # noqa: S105 - test fixture
    scenario: dict[str, str] = field(default_factory=dict)  # provider -> scenario name
    issued: dict[str, str] = field(default_factory=dict)  # access token -> provider
    refresh: dict[str, str] = field(default_factory=dict)  # refresh token -> provider
    codes: dict[str, tuple[str, str]] = field(default_factory=dict)  # code -> (provider, challenge)
    revoked: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    teams_scopes: str = (
        "openid profile offline_access https://graph.microsoft.com/User.Read "
        "https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/OnlineMeetings.Read "
        "https://graph.microsoft.com/OnlineMeetingTranscript.Read.All"
    )
    teams_401_once: bool = False
    base_url: str = "http://fake.local"

    # ---- helpers ----------------------------------------------------------
    def _tokens(self, provider: str, scope: str) -> dict[str, Any]:
        at, rt = f"{provider}-at-{secrets.token_hex(6)}", f"{provider}-rt-{secrets.token_hex(6)}"
        self.issued[at] = provider
        self.refresh[rt] = provider
        return {"token_type": "Bearer", "access_token": at, "refresh_token": rt, "expires_in": 3600, "scope": scope}

    def _authorized(self, request: httpx.Request, provider: str) -> bool:
        auth = request.headers.get("authorization", "")
        return auth.startswith("Bearer ") and self.issued.get(auth[7:]) == provider

    def authorize_redirect(self, provider: str, params: dict[str, str]) -> str:
        """Simulates the user consenting at the provider and being redirected back."""
        code = f"code-{secrets.token_hex(8)}"
        self.codes[code] = (provider, params.get("code_challenge", ""))
        q = {"code": code, "state": params.get("state", "")}
        if self.scenario.get(provider) == "consent_denied_admin":
            q = {
                "error": "consent_required",
                "error_description": "AADSTS65001: The user or administrator has not consented to use the application.",
                "state": params.get("state", ""),
            }
        sep = "&" if "?" in params["redirect_uri"] else "?"
        return f"{params['redirect_uri']}{sep}{urllib.parse.urlencode(q)}"

    def _token(self, provider: str, request: httpx.Request, scope: str) -> httpx.Response:
        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        if provider == "zoom":
            expected = "Basic " + base64.b64encode(f"{self.client_ids['zoom']}:{self.client_secret}".encode()).decode()
            if request.headers.get("authorization") != expected:
                return _json({"error": "invalid_client"}, 401)
        elif form.get("client_id") != self.client_ids[provider] or form.get("client_secret") != self.client_secret:
            return _json({"error": "invalid_client"}, 401)
        if form.get("grant_type") == "authorization_code":
            code = form.get("code", "")
            if code in self.codes:
                p, challenge = self.codes.pop(code)
                if p != provider or (challenge and _s256(form.get("code_verifier", "")) != challenge):
                    return _json({"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
            elif not code.startswith("test-code"):
                return _json({"error": "invalid_grant"}, 400)
            return _json(self._tokens(provider, scope))
        if form.get("grant_type") == "refresh_token":
            rt = form.get("refresh_token", "")
            if self.refresh.pop(rt, None) != provider or self.scenario.get(provider) == "revoked":
                return _json({"error": "invalid_grant"}, 400)
            return _json(self._tokens(provider, scope))  # rotation: old refresh token is now invalid
        return _json({"error": "unsupported_grant_type"}, 400)

    # ---- router -------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        for prefix, fn in (("/teams/", self._teams), ("/zoom/", self._zoom), ("/google/", self._google)):
            if path.startswith(prefix):
                if path[len(prefix) :] == "authorize":
                    loc = self.authorize_redirect(prefix.strip("/"), dict(request.url.params))
                    return httpx.Response(302, headers={"location": loc})
                return fn(request, path[len(prefix) :])
        return _json({"error": "not_found"}, 404)

    # ---- Microsoft Graph ------------------------------------------------------
    def _teams(self, request: httpx.Request, sub: str) -> httpx.Response:
        sc = self.scenario.get("teams", "")
        if sub == "token":
            scope = self.teams_scopes
            if sc == "no_admin_consent":
                scope = scope.replace(" https://graph.microsoft.com/OnlineMeetingTranscript.Read.All", "")
            return self._token("teams", request, scope)
        if not self._authorized(request, "teams"):
            return _json({"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty."}}, 401)
        if self.teams_401_once:
            self.teams_401_once = False
            return _json(
                {"error": {"code": "InvalidAuthenticationToken", "message": "Lifetime validation failed"}}, 401
            )
        if sub == "graph/me":
            return _json(
                {
                    "id": "8f2c7b1e-1111-4a2b-9c3d-123456789abc",
                    "displayName": "Trần Minh",
                    "userPrincipalName": "pm@contoso.onmicrosoft.com",
                    "mail": "pm@contoso.com",
                }
            )
        if sub == "graph/me/calendarView":
            return _json(
                {
                    "value": [
                        {
                            "subject": "Định nghĩa yêu cầu",
                            "isOnlineMeeting": True,
                            "start": {"dateTime": "2026-10-15T01:00:00.0000000", "timeZone": "UTC"},
                            "end": {"dateTime": "2026-10-15T02:00:00.0000000", "timeZone": "UTC"},
                            "onlineMeeting": {"joinUrl": TEAMS_JOIN_URL},
                        },
                        {"subject": "Lunch", "isOnlineMeeting": False, "start": {}, "end": {}},
                    ]
                }
            )
        if sub == "graph/me/onlineMeetings":
            flt = request.url.params.get("$filter", "")
            if TEAMS_JOIN_URL in flt or "joinMeetingId eq '1234567890'" in flt:
                return _json(
                    {
                        "value": [
                            {
                                "id": TEAMS_MEETING_ID,
                                "subject": "Định nghĩa yêu cầu",
                                "joinWebUrl": TEAMS_JOIN_URL,
                                "startDateTime": "2026-10-15T01:00:00Z",
                                "endDateTime": "2026-10-15T02:00:00Z",
                            }
                        ]
                    }
                )
            return _json({"value": []})
        base = f"graph/me/onlineMeetings/{TEAMS_MEETING_ID}/transcripts"
        if sc == "transcripts_disabled" and sub.startswith(base):
            return _json(
                {
                    "error": {
                        "code": "Forbidden",
                        "message": "Graph API access to transcripts is disabled.",
                        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
                    }
                },
                403,
            )
        if sub == base:
            if sc == "no_transcript":
                return _json({"value": []})
            return _json(
                {
                    "value": [
                        {
                            "id": TEAMS_TRANSCRIPT_ID,
                            "meetingId": TEAMS_MEETING_ID,
                            "createdDateTime": "2026-10-15T01:00:05.1234567Z",
                            "endDateTime": "2026-10-15T01:58:00Z",
                        }
                    ]
                }
            )
        if sub == f"{base}/{TEAMS_TRANSCRIPT_ID}/content":
            accept = request.headers.get("accept", "")
            if sc == "no_speaker" and "text/vtt" in accept:
                return _json(
                    {
                        "error": {
                            "code": "Forbidden",
                            "message": "Speaker-attributed transcript content is disabled for this tenant.",
                            "innerError": {"code": "SpeakerAttributionNotAllowed"},
                        }
                    },
                    403,
                )
            if "application/vnd.microsoft.graph.transcript+text" in accept:
                return httpx.Response(
                    200,
                    text=TEAMS_UNATTRIBUTED,
                    headers={"content-type": "application/vnd.microsoft.graph.transcript+text"},
                )
            return httpx.Response(200, text=TEAMS_VTT, headers={"content-type": "text/vtt"})
        return _json({"error": {"code": "itemNotFound", "message": "Not found"}}, 404)

    # ---- Zoom ------------------------------------------------------------------------
    def _zoom(self, request: httpx.Request, sub: str) -> httpx.Response:
        sc = self.scenario.get("zoom", "")
        if sub == "token":
            return self._token(
                "zoom", request, "meeting:read:meeting cloud_recording:read:list_recording_files user:read:user"
            )
        if sub == "revoke":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            self.revoked.append(form.get("token", ""))
            return _json({"status": "success"})
        if sub == "rec/download/transcript-1":
            # Zoom serves the file after a redirect; the redirect target must not receive the bearer token.
            if self._authorized(request, "zoom"):
                return httpx.Response(302, headers={"location": f"{self.base_url}/zoom/cdn/transcript-1.vtt"})
            return _json({"code": 124, "message": "Invalid access token."}, 401)
        if sub == "cdn/transcript-1.vtt":
            if request.headers.get("authorization"):
                return _json({"error": "token leaked to CDN"}, 400)
            return httpx.Response(200, text=ZOOM_VTT, headers={"content-type": "text/vtt"})
        if not self._authorized(request, "zoom"):
            return _json({"code": 124, "message": "Invalid access token."}, 401)
        if sub == "api/users/me":
            return _json(
                {
                    "id": "KDcuGIm1QgePTO8WbOqwIQ",
                    "email": "host@example.com",
                    "first_name": "Sarah",
                    "last_name": "Johnson",
                }
            )
        if sub == f"api/meetings/{ZOOM_MEETING_ID}":
            return _json({"uuid": ZOOM_UUID, "id": int(ZOOM_MEETING_ID), "topic": "Release plan v2.0"})
        if sub == "api/users/me/recordings":
            return _json(
                {
                    "meetings": [
                        {
                            "uuid": ZOOM_UUID,
                            "id": int(ZOOM_MEETING_ID),
                            "topic": "Release plan v2.0",
                            "start_time": "2026-10-14T09:00:00Z",
                            "recording_files": [{"file_type": "TRANSCRIPT"}],
                        }
                    ]
                }
            )
        if sub == f"api/meetings/{ZOOM_MEETING_ID}/recordings":
            if sc == "no_recording":
                return _json({"code": 3301, "message": "This recording does not exist."}, 404)
            if sc == "scope_missing":
                return _json({"code": 4711, "message": "Invalid access token, does not contain scopes"}, 400)
            if sc == "rate_limited":
                return _json({"code": 429, "message": "Too many requests"}, 429, {"Retry-After": "120"})
            status = "processing" if sc == "processing" else "completed"
            return _json(
                {
                    "uuid": ZOOM_UUID,
                    "id": int(ZOOM_MEETING_ID),
                    "topic": "Release plan v2.0",
                    "start_time": "2026-10-14T09:00:00Z",
                    "recording_files": [
                        {"id": "rec-mp4", "file_type": "MP4", "status": "completed"},
                        {
                            "id": "transcript-1",
                            "file_type": "TRANSCRIPT",
                            "file_extension": "VTT",
                            "recording_type": "audio_transcript",
                            "status": status,
                            "download_url": f"{self.base_url}/zoom/rec/download/transcript-1",
                        },
                    ],
                }
            )
        return _json({"code": 3001, "message": "Meeting does not exist."}, 404)

    # ---- Google Meet ---------------------------------------------------------------------
    def _google(self, request: httpx.Request, sub: str) -> httpx.Response:
        sc = self.scenario.get("google", "")
        if sub == "token":
            scope = "openid https://www.googleapis.com/auth/userinfo.email"
            if sc != "no_meet_scope":
                scope += " https://www.googleapis.com/auth/meetings.space.readonly"
            return self._token("google", request, scope)
        if sub == "revoke":
            self.revoked.append(dict(urllib.parse.parse_qsl(request.content.decode())).get("token", ""))
            return httpx.Response(200)
        if not self._authorized(request, "google"):
            return _json(
                {
                    "error": {
                        "code": 401,
                        "message": "Request had invalid authentication credentials.",
                        "status": "UNAUTHENTICATED",
                    }
                },
                401,
            )
        if sub == "userinfo":
            return _json({"sub": "110169484474386276334", "email": "pm@example.com", "email_verified": True})
        if sub == "api/conferenceRecords":
            flt = request.url.params.get("filter", "")
            if MEET_CODE not in flt and "start_time" not in flt:
                return _json({})
            record: dict[str, Any] = {
                "name": MEET_RECORD,
                "startTime": "2026-10-15T01:00:00.000Z",
                "endTime": "2026-10-15T02:00:00.000Z",
                "expireTime": "2099-11-14T02:00:00Z",
                "space": "spaces/jQCFfuBOdN5z",
            }
            if sc == "ongoing":
                record.pop("endTime")
            if sc == "expired":
                record["expireTime"] = "2020-01-01T00:00:00Z"
            return _json({"conferenceRecords": [record]})
        if sub == f"api/{MEET_RECORD}/transcripts":
            if sc == "no_transcript":
                return _json({})
            state = "ENDED" if sc == "generating" else "FILE_GENERATED"
            return _json(
                {
                    "transcripts": [
                        {
                            "name": MEET_TRANSCRIPT,
                            "state": state,
                            "startTime": "2026-10-15T01:00:10.000Z",
                            "endTime": "2026-10-15T01:59:00Z",
                            "docsDestination": {"document": "1abc", "exportUri": "https://docs.google.com/x"},
                        }
                    ]
                }
            )
        if sub == f"api/{MEET_TRANSCRIPT}/entries":
            page2 = request.url.params.get("pageToken") == "page-2"
            entries = (
                [
                    {
                        "name": f"{MEET_TRANSCRIPT}/entries/e3",
                        "participant": f"{MEET_RECORD}/participants/p3",
                        "text": "Có nên bổ sung test case không?",
                        "languageCode": "vi-VN",
                        "startTime": "2026-10-15T01:00:40.000Z",
                        "endTime": "2026-10-15T01:00:44.000Z",
                    },
                ]
                if page2
                else [
                    {
                        "name": f"{MEET_TRANSCRIPT}/entries/e1",
                        "participant": f"{MEET_RECORD}/participants/p1",
                        "text": "We agreed to deploy v1.4.0 to staging next Friday.",
                        "languageCode": "en-US",
                        "startTime": "2026-10-15T01:00:12.500Z",
                        "endTime": "2026-10-15T01:00:18.000Z",
                    },
                    {
                        "name": f"{MEET_TRANSCRIPT}/entries/e2",
                        "participant": f"{MEET_RECORD}/participants/p2",
                        "text": "Linh will send the reminder email.",
                        "languageCode": "en-US",
                        "startTime": "2026-10-15T01:00:20.000Z",
                        "endTime": "2026-10-15T01:00:24.000Z",
                    },
                ]
            )
            body: dict[str, Any] = {"transcriptEntries": entries}
            if not page2:
                body["nextPageToken"] = "page-2"
            return _json(body)
        if sub == f"api/{MEET_RECORD}/participants/p1":
            return _json(
                {
                    "name": f"{MEET_RECORD}/participants/p1",
                    "signedinUser": {"user": "users/123", "displayName": "Trần Minh"},
                }
            )
        if sub == f"api/{MEET_RECORD}/participants/p2":
            return _json({"name": f"{MEET_RECORD}/participants/p2", "anonymousUser": {"displayName": "Linh (Guest)"}})
        return _json({"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}}, 404)


def overrides_json(base: str) -> str:
    return json.dumps({"teams": f"{base}/teams", "zoom": f"{base}/zoom", "google_meet": f"{base}/google"})
