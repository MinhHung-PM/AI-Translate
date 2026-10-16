"""Microsoft Teams connector (delegated Microsoft Graph).

Verified against microsoftgraph/microsoft-graph-docs-contrib (2026-10-16):

* ``GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`` — delegated ``OnlineMeetings.Read``
  (no admin consent).
* ``GET /me/onlineMeetings/{id}/transcripts`` and ``…/transcripts/{tid}/content`` —
  delegated ``OnlineMeetingTranscript.Read.All`` (**admin consent required**). Tenants can
  disable access (403 ``GraphAccessToTranscriptsDisabled``) or speaker attribution
  (403 ``SpeakerAttributionNotAllowed`` → retry with the unattributed format).
* ``GET /me/calendarView`` — delegated ``Calendars.Read`` (no admin consent).
* Real-time media needs application ``Calls.AccessMedia.All`` + a hosted media bot:
  not supported here (application permissions are not assumed to be available).
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
    TranscriptFetchResult,
)
from app.integrations.capabilities import Capability as C
from app.integrations.capabilities import CapabilityState, cap
from app.integrations.capabilities import CapabilityStatus as S
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.http import default_error, provider_error_code
from app.integrations.normalization.transcript_normalizer import events_from_vtt
from app.models.enums import ExternalTranscriptStatus, PlatformProvider

GRAPH_PREFIX = "https://graph.microsoft.com/"
TRANSCRIPT_SCOPE = "OnlineMeetingTranscript.Read.All"
BASE_SCOPES = ["openid", "profile", "offline_access", "User.Read", "Calendars.Read", "OnlineMeetings.Read"]
UNATTRIBUTED = "application/vnd.microsoft.graph.transcript+text"
_JOIN_HOSTS = {"teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)  # Graph may return 7 fractional digits
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize_scope(scope: str) -> str:
    return scope[len(GRAPH_PREFIX) :] if scope.startswith(GRAPH_PREFIX) else scope


class TeamsConnector(Connector):
    provider = PlatformProvider.teams
    display_name = "Microsoft Teams"

    @property
    def default_endpoints(self) -> dict[str, str]:  # type: ignore[override]
        tenant = get_settings().teams_tenant_id or "organizations"
        return {
            "authorize": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            "token": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            "graph": "https://graph.microsoft.com/v1.0",
        }

    def configuration_problems(self) -> list[str]:
        s = get_settings()
        return [
            n
            for n, v in (("TEAMS_CLIENT_ID", s.teams_client_id), ("TEAMS_CLIENT_SECRET", s.teams_client_secret))
            if not v
        ]

    def client_id(self) -> str:
        return get_settings().teams_client_id

    def client_secret(self) -> str:
        return get_settings().teams_client_secret

    def requested_scopes(self) -> list[str]:
        scopes = list(BASE_SCOPES)
        if get_settings().teams_request_transcript_scope:
            scopes.append(TRANSCRIPT_SCOPE)
        return scopes

    def authorization_params(self) -> dict[str, str]:
        return {"response_mode": "query"}

    def map_error(self, resp: httpx.Response) -> IntegrationError:
        code = provider_error_code(resp)
        if resp.status_code == 403 and code == "GraphAccessToTranscriptsDisabled":
            return IntegrationError(
                ErrorCategory.admin_approval_required,
                "A tenant administrator has disabled Microsoft Graph access to meeting transcripts.",
                provider_code=code,
            )
        if resp.status_code == 403 and code == "SpeakerAttributionNotAllowed":
            return IntegrationError(
                ErrorCategory.insufficient_scope, "Speaker attribution is disabled", provider_code=code
            )
        if resp.status_code == 400 and code in {"invalid_grant", "interaction_required"}:
            return IntegrationError(
                ErrorCategory.consent_revoked,
                "Authorization expired or was revoked; reconnect Teams.",
                provider_code=code,
            )
        return default_error(resp)

    def get_capabilities(self, scopes: set[str] | None, connected: bool) -> list[CapabilityState]:
        scopes = {normalize_scope(s) for s in (scopes or set())}
        out = [cap(C.transcript_import, S.available, "Upload the WebVTT transcript downloaded from Teams.")]
        if not self.is_configured():
            gate = cap(
                C.post_meeting_transcript,
                S.requires_configuration,
                "The Teams app registration is not configured.",
                "IT registers an Entra ID app and sets TEAMS_CLIENT_ID/TEAMS_CLIENT_SECRET.",
            )
            out += [gate, gate.model_copy(update={"capability": C.list_meetings})]
        elif not connected:
            out += [
                cap(C.list_meetings, S.requires_user_consent, "Connect your Microsoft account."),
                cap(C.post_meeting_transcript, S.requires_user_consent, "Connect your Microsoft account."),
            ]
        else:
            out.append(
                cap(C.list_meetings, S.available, "Online meetings from your calendar (Calendars.Read).")
                if "Calendars.Read" in scopes
                else cap(
                    C.list_meetings, S.requires_user_consent, "Calendars.Read was not granted.", "Reconnect and accept."
                )
            )
            out.append(
                cap(
                    C.post_meeting_transcript,
                    S.available,
                    "Transcripts of meetings you organized or attended (tenant settings can still block access).",
                )
                if TRANSCRIPT_SCOPE in scopes
                else cap(
                    C.post_meeting_transcript,
                    S.requires_admin_approval,
                    "OnlineMeetingTranscript.Read.All (delegated) requires tenant administrator consent.",
                    "Ask IT to grant admin consent for this app, then reconnect. Until then, import the VTT file.",
                )
            )
        live_msg = (
            "Real-time Teams media requires the application permission Calls.AccessMedia.All and a hosted "
            "media bot; application permissions are not available to this deployment."
        )
        out += [
            cap(C.live_transcript, S.not_supported, live_msg, "Use post-meeting transcript retrieval or file import."),
            cap(C.live_audio, S.not_supported, live_msg),
            cap(
                C.speaker_metadata,
                S.available,
                "Speaker names from WebVTT voice tags; if the tenant disables speaker attribution, text is imported "
                "without speakers.",
            ),
            cap(
                C.meeting_event_notifications,
                S.not_supported,
                "Transcript change notifications require application permissions; retrieval is user-initiated.",
            ),
            cap(C.recovery_after_disconnect, S.available, "Post-meeting retrieval is idempotent and can be re-run."),
        ]
        return out

    def fetch_account(self, access_token: str) -> AccountInfo:
        me = self.http.get_json(f"{self.endpoint('graph')}/me", token=access_token)
        return AccountInfo(
            account_id=str(me.get("id", "")),
            display=str(me.get("userPrincipalName") or me.get("mail") or me.get("displayName") or "Microsoft account"),
        )

    def list_available_meetings(self, access_token: str) -> list[AvailableMeeting]:
        now = datetime.now(UTC)
        params = {
            "startDateTime": (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "$select": "subject,start,end,isOnlineMeeting,onlineMeeting",
            "$orderby": "start/dateTime desc",
            "$top": "50",
        }
        data = self.http.get_json(
            f"{self.endpoint('graph')}/me/calendarView",
            token=access_token,
            params=params,
            headers={"Prefer": 'outlook.timezone="UTC"'},
        )
        out: list[AvailableMeeting] = []
        for ev in data.get("value", []):
            join = (ev.get("onlineMeeting") or {}).get("joinUrl")
            if not ev.get("isOnlineMeeting") or not join:
                continue
            out.append(
                AvailableMeeting(
                    provider_meeting_id=join,
                    title=str(ev.get("subject") or "(no subject)"),
                    start=_parse_dt((ev.get("start") or {}).get("dateTime")),
                    end=_parse_dt((ev.get("end") or {}).get("dateTime")),
                    join_url=join,
                )
            )
        return out

    def resolve_meeting(self, access_token: str, reference: str) -> ResolvedMeeting:
        ref = reference.strip()
        if ref.startswith("https://"):
            host = urllib.parse.urlparse(ref).hostname or ""
            if host not in _JOIN_HOSTS:
                raise IntegrationError(
                    ErrorCategory.invalid_request, "Enter a Teams meeting join link (teams.microsoft.com)."
                )
            flt = f"JoinWebUrl eq '{ref.replace(chr(39), chr(39) * 2)}'"
        elif re.fullmatch(r"[0-9 ]{9,20}", ref):
            flt = f"joinMeetingIdSettings/joinMeetingId eq '{ref.replace(' ', '')}'"
        else:
            raise IntegrationError(ErrorCategory.invalid_request, "Enter a Teams join link or the numeric meeting ID.")
        data = self.http.get_json(
            f"{self.endpoint('graph')}/me/onlineMeetings", token=access_token, params={"$filter": flt}
        )
        items = data.get("value") or []
        if not items:
            raise IntegrationError(
                ErrorCategory.meeting_not_found,
                "Meeting not found, or your account is not its organizer or an invited attendee.",
            )
        m = items[0]
        return ResolvedMeeting(
            provider_meeting_id=str(m["id"]),
            join_url=m.get("joinWebUrl") or (ref if ref.startswith("https://") else None),
            title=m.get("subject"),
            resolved_ids={k: str(m[k]) for k in ("startDateTime", "endDateTime") if m.get(k)},
        )

    def _content(self, access_token: str, url: str) -> tuple[str, bool]:
        try:
            return self.http.request("GET", url, token=access_token, headers={"Accept": "text/vtt"}).text, True
        except IntegrationError as err:
            if err.provider_code != "SpeakerAttributionNotAllowed":
                raise
        # Tenant disallows speaker attribution: the unattributed format still works.
        return self.http.request("GET", url, token=access_token, headers={"Accept": UNATTRIBUTED}).text, False

    def fetch_transcript(self, access_token: str, ref: ResolvedMeeting) -> TranscriptFetchResult:
        base = f"{self.endpoint('graph')}/me/onlineMeetings/{urllib.parse.quote(ref.provider_meeting_id, safe='')}"
        listing = self.http.get_json(f"{base}/transcripts", token=access_token)
        transcripts: list[dict[str, Any]] = sorted(
            listing.get("value") or [], key=lambda t: t.get("createdDateTime") or ""
        )
        if not transcripts:
            end = _parse_dt(ref.resolved_ids.get("endDateTime"))
            recent = end is None or datetime.now(UTC) - end < timedelta(hours=24)
            return TranscriptFetchResult(
                ExternalTranscriptStatus.pending if recent else ExternalTranscriptStatus.not_available,
                [],
                "No transcript is available yet."
                if recent
                else "No transcript exists for this meeting (transcription was probably not started).",
            )
        events = []
        attributed = True
        first_created = _parse_dt(transcripts[0].get("createdDateTime"))
        for t in transcripts:
            tid = str(t["id"])
            text, with_speakers = self._content(
                access_token, f"{base}/transcripts/{urllib.parse.quote(tid, safe='')}/content"
            )
            attributed = attributed and with_speakers
            batch = events_from_vtt(
                text,
                provider="teams",
                provider_meeting_id=ref.provider_meeting_id,
                transcript_id=tid,
                metadata={"speaker_attribution": with_speakers},
            )
            created = _parse_dt(t.get("createdDateTime"))
            shift = int((created - first_created).total_seconds() * 1000) if created and first_created else 0
            for e in batch:  # keep multiple transcripts (transcription restarted) on one timeline
                if e.start_timestamp_ms is not None:
                    e.start_timestamp_ms += shift
                if e.end_timestamp_ms is not None:
                    e.end_timestamp_ms += shift
            events += batch
        msg = f"{len(events)} transcript segments retrieved from Microsoft Graph."
        if not attributed:
            msg += " Speaker attribution is disabled by the tenant; speakers were not imported."
        return TranscriptFetchResult(ExternalTranscriptStatus.available, events, msg, speaker_attribution=attributed)
