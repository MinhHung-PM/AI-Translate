"""Zoom connector.

* OAuth (user-managed app): ``https://zoom.us/oauth/authorize`` / ``/oauth/token``
  (client credentials sent with HTTP Basic), revocation at ``/oauth/revoke``.
* Post-meeting: ``GET /v2/meetings/{meetingId}/recordings`` → ``recording_files`` entry
  with ``file_type == "TRANSCRIPT"`` (WebVTT). Requires cloud recording with the
  audio-transcript option (paid plans). Exact granular scopes are configured on the
  Marketplace app (``ZOOM_SCOPES``) — **not verified against Zoom's scope reference**.
* Live: Realtime Media Streams via the official ``rtms`` SDK (see ``rtms.py``), started by
  the signed ``meeting.rtms_started`` webhook. RTMS must be provisioned for the account.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.base import (
    AccountInfo,
    AvailableMeeting,
    Connector,
    ResolvedMeeting,
    TokenSet,
    TranscriptFetchResult,
)
from app.integrations.capabilities import Capability as C
from app.integrations.capabilities import CapabilityState, cap
from app.integrations.capabilities import CapabilityStatus as S
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.http import default_error, provider_error_code
from app.integrations.normalization.transcript_normalizer import events_from_vtt
from app.integrations.zoom.rtms import rtms_sdk_available
from app.models.enums import ExternalTranscriptStatus, PlatformProvider

_ZOOM_HOST = re.compile(r"(^|\.)zoom\.(us|com)$")


def parse_meeting_id(reference: str) -> str:
    ref = reference.strip()
    if ref.startswith("https://"):
        parsed = urllib.parse.urlparse(ref)
        if not _ZOOM_HOST.search(parsed.hostname or ""):
            raise IntegrationError(ErrorCategory.invalid_request, "Enter a Zoom meeting link (zoom.us) or meeting ID.")
        m = re.search(r"/(?:j|s|w|wc/join)/(\d{9,12})", parsed.path)
        if not m:
            raise IntegrationError(ErrorCategory.invalid_request, "The Zoom link does not contain a meeting ID.")
        return m.group(1)
    digits = re.sub(r"[\s-]", "", ref)
    if not re.fullmatch(r"\d{9,12}", digits):
        raise IntegrationError(ErrorCategory.invalid_request, "Enter a Zoom meeting ID (9–12 digits) or meeting link.")
    return digits


def encode_meeting_uuid(uuid: str) -> str:
    """Zoom requires double URL-encoding for UUIDs that start with '/' or contain '//'."""
    once = urllib.parse.quote(uuid, safe="")
    return urllib.parse.quote(once, safe="") if uuid.startswith("/") or "//" in uuid else once


class ZoomConnector(Connector):
    provider = PlatformProvider.zoom
    display_name = "Zoom"
    default_endpoints = {
        "authorize": "https://zoom.us/oauth/authorize",
        "token": "https://zoom.us/oauth/token",
        "revoke": "https://zoom.us/oauth/revoke",
        "api": "https://api.zoom.us/v2",
    }

    def configuration_problems(self) -> list[str]:
        s = get_settings()
        return [
            n for n, v in (("ZOOM_CLIENT_ID", s.zoom_client_id), ("ZOOM_CLIENT_SECRET", s.zoom_client_secret)) if not v
        ]

    def client_id(self) -> str:
        return get_settings().zoom_client_id

    def client_secret(self) -> str:
        return get_settings().zoom_client_secret

    def token_request_auth(self) -> tuple[str, str] | None:
        return (self.client_id(), self.client_secret())

    def requested_scopes(self) -> list[str]:
        return get_settings().zoom_scopes.split()

    def map_error(self, resp: httpx.Response) -> IntegrationError:
        code = provider_error_code(resp)
        if code in {"4711", "4700"} or (resp.status_code == 400 and code == "4711"):
            return IntegrationError(
                ErrorCategory.insufficient_scope,
                "The Zoom app is missing a required scope for this operation.",
                provider_code=code,
            )
        if code == "3301":
            return IntegrationError(
                ErrorCategory.transcript_unavailable, "No cloud recording exists for this meeting.", provider_code=code
            )
        if code == "124":
            return IntegrationError(ErrorCategory.token_expired, "Zoom rejected the access token.", provider_code=code)
        if resp.status_code == 400 and code == "invalid_grant":
            return IntegrationError(
                ErrorCategory.consent_revoked,
                "Authorization expired or was revoked; reconnect Zoom.",
                provider_code=code,
            )
        return default_error(resp)

    def live_problems(self) -> list[str]:
        s = get_settings()
        problems = []
        if not s.zoom_webhook_secret_token:
            problems.append("ZOOM_WEBHOOK_SECRET_TOKEN")
        if not s.zoom_rtms_enabled:
            problems.append("ZOOM_RTMS_ENABLED (RTMS must be provisioned for the Zoom account/app)")
        if not rtms_sdk_available():
            problems.append("the 'rtms' Python SDK (pip install rtms)")
        return problems

    def get_capabilities(self, scopes: set[str] | None, connected: bool) -> list[CapabilityState]:
        out = [cap(C.transcript_import, S.available, "Upload the cloud-recording transcript (.vtt) from Zoom.")]
        if not self.is_configured():
            gate = cap(
                C.post_meeting_transcript,
                S.requires_configuration,
                "The Zoom app is not configured.",
                "Create a user-managed General App in the Zoom Marketplace and set ZOOM_CLIENT_ID/ZOOM_CLIENT_SECRET.",
            )
            out += [gate, gate.model_copy(update={"capability": C.list_meetings})]
        elif not connected:
            out += [
                cap(C.list_meetings, S.requires_user_consent, "Connect your Zoom account."),
                cap(C.post_meeting_transcript, S.requires_user_consent, "Connect your Zoom account."),
            ]
        else:
            out += [
                cap(C.list_meetings, S.available, "Meetings with cloud recordings from the last 30 days."),
                cap(
                    C.post_meeting_transcript,
                    S.available,
                    "Requires cloud recording with 'Create audio transcript' enabled (paid Zoom plans).",
                ),
            ]
        problems = self.live_problems()
        if not self.is_configured() or problems:
            out.append(
                cap(
                    C.live_transcript,
                    S.requires_configuration,
                    "Zoom Realtime Media Streams are not configured: missing " + ", ".join(problems or ["app"]) + ".",
                    "Zoom must enable RTMS for the account; the app needs the RTMS events/scopes and webhook.",
                )
            )
        elif not connected:
            out.append(
                cap(
                    C.live_transcript,
                    S.requires_user_consent,
                    "Connect your Zoom account (the host must install the app).",
                )
            )
        else:
            out.append(
                cap(
                    C.live_transcript,
                    S.available,
                    "RTMS transcript stream after the host starts RTMS (not yet verified against a live account).",
                )
            )
        out += [
            cap(
                C.live_audio,
                S.not_supported,
                "The RTMS transcript stream is used instead of raw audio; no speech-to-text runs in this build.",
            ),
            cap(C.speaker_metadata, S.available, "Speaker names from RTMS metadata (userName) or the VTT transcript."),
            cap(
                C.meeting_event_notifications,
                S.available if get_settings().zoom_webhook_secret_token else S.requires_configuration,
                "Signed webhooks (RTMS start/stop, transcript completed).",
                None if get_settings().zoom_webhook_secret_token else "Set ZOOM_WEBHOOK_SECRET_TOKEN.",
            ),
            cap(
                C.recovery_after_disconnect,
                S.available,
                "Post-meeting retrieval can be re-run. Live: rejoin while the RTMS stream is active; "
                "segments sent while disconnected are not replayed by Zoom "
                "(recover them from the post-meeting transcript).",
            ),
        ]
        return out

    def fetch_account(self, access_token: str) -> AccountInfo:
        me = self.http.get_json(f"{self.endpoint('api')}/users/me", token=access_token)
        name = " ".join(x for x in (me.get("first_name"), me.get("last_name")) if x) or me.get("display_name")
        return AccountInfo(account_id=str(me.get("id", "")), display=str(me.get("email") or name or "Zoom account"))

    def revoke(self, tokens: TokenSet) -> bool:
        self.http.request(
            "POST", self.endpoint("revoke"), data={"token": tokens.access_token}, auth=self.token_request_auth()
        )
        return True

    def list_available_meetings(self, access_token: str) -> list[AvailableMeeting]:
        now = datetime.now(UTC)
        params = {
            "from": (now - timedelta(days=30)).strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            "page_size": "50",
        }
        data = self.http.get_json(f"{self.endpoint('api')}/users/me/recordings", token=access_token, params=params)
        out = []
        for m in data.get("meetings", []):
            files = m.get("recording_files") or []
            start = datetime.fromisoformat(str(m["start_time"]).replace("Z", "+00:00")) if m.get("start_time") else None
            out.append(
                AvailableMeeting(
                    provider_meeting_id=str(m.get("id")),
                    title=str(m.get("topic") or "(no topic)"),
                    start=start,
                    end=None,
                    has_transcript=any(f.get("file_type") == "TRANSCRIPT" for f in files),
                )
            )
        return out

    def resolve_meeting(self, access_token: str, reference: str) -> ResolvedMeeting:
        meeting_id = parse_meeting_id(reference)
        ids: dict[str, str] = {}
        title = None
        try:
            m = self.http.get_json(f"{self.endpoint('api')}/meetings/{meeting_id}", token=access_token)
            title = m.get("topic")
            if m.get("uuid"):
                ids["uuid"] = str(m["uuid"])  # instance UUID, used to match RTMS webhooks
        except IntegrationError as err:
            if err.category != ErrorCategory.meeting_not_found:
                raise  # ended meetings may 404 here; recordings are checked at fetch time
        join = reference.strip() if reference.strip().startswith("https://") else None
        return ResolvedMeeting(provider_meeting_id=meeting_id, join_url=join, title=title, resolved_ids=ids)

    def fetch_transcript(self, access_token: str, ref: ResolvedMeeting) -> TranscriptFetchResult:
        try:
            data = self.http.get_json(
                f"{self.endpoint('api')}/meetings/{ref.provider_meeting_id}/recordings", token=access_token
            )
        except IntegrationError as err:
            if err.category in (ErrorCategory.transcript_unavailable, ErrorCategory.meeting_not_found):
                return TranscriptFetchResult(
                    ExternalTranscriptStatus.not_available, [], "No cloud recording was found for this meeting."
                )
            raise
        files: list[dict[str, Any]] = data.get("recording_files") or []
        transcripts = [f for f in files if f.get("file_type") == "TRANSCRIPT"]
        if not transcripts:
            return TranscriptFetchResult(
                ExternalTranscriptStatus.not_available,
                [],
                "The recording has no audio transcript (enable 'Create audio transcript').",
            )
        done = [f for f in transcripts if f.get("status") == "completed" and f.get("download_url")]
        if not done:
            return TranscriptFetchResult(
                ExternalTranscriptStatus.pending, [], "Zoom is still processing the transcript."
            )
        f = done[0]
        # The bearer token is sent only to the download URL itself, never forwarded on redirects.
        text = self.http.request("GET", str(f["download_url"]), token=access_token).text
        events = events_from_vtt(
            text,
            provider="zoom",
            provider_meeting_id=ref.provider_meeting_id,
            transcript_id=str(f.get("id") or "transcript"),
            metadata={"recording_uuid": data.get("uuid")},
        )
        return TranscriptFetchResult(
            ExternalTranscriptStatus.available,
            events,
            f"{len(events)} transcript segments retrieved from Zoom cloud recording.",
        )
