"""Google Meet connector (Meet REST API v2, post-meeting transcripts).

Verified against googleapis/googleapis ``google/apps/meet/v2`` (2026-10-16):

* ``GET /v2/conferenceRecords?filter=space.meeting_code="abc-mnop-xyz"``
* ``GET /v2/{conferenceRecord}/transcripts`` — ``state``: STARTED → ENDED → FILE_GENERATED
* ``GET /v2/{transcript}/entries`` — ``participant``, ``text``, ``language_code``,
  ``start_time``, ``end_time`` (may differ slightly from the Docs transcript file)
* ``GET /v2/{participant}`` — ``signedinUser|anonymousUser|phoneUser.displayName``
* Conference records are deleted 30 days after the conference ends (``expire_time``).
* Scope: ``https://www.googleapis.com/auth/meetings.space.readonly``.

Not supported: real-time transcripts or audio (the Meet Media API is developer
preview, requires every participant to be enrolled and does not provide transcripts),
and push notifications (Workspace Events API via Pub/Sub is not implemented; bounded
polling is used instead).
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

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
from app.integrations.models import CanonicalEvent
from app.integrations.normalization.transcript_normalizer import language_from_code, offset_ms
from app.models.enums import ExternalTranscriptStatus, PlatformProvider
from app.services.transcripts.normalize import clean_text

MEET_SCOPE = "https://www.googleapis.com/auth/meetings.space.readonly"
_CODE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$")
MAX_ENTRY_PAGES = 200


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    return datetime.fromisoformat(v)


def parse_meeting_code(reference: str) -> str:
    ref = reference.strip()
    if ref.startswith("https://"):
        parsed = urllib.parse.urlparse(ref)
        if parsed.hostname != "meet.google.com":
            raise IntegrationError(
                ErrorCategory.invalid_request, "Enter a Google Meet link (meet.google.com) or meeting code."
            )
        ref = parsed.path.strip("/").split("/")[0]
    ref = ref.lower()
    if not _CODE.match(ref):
        raise IntegrationError(ErrorCategory.invalid_request, "Enter a meeting code like abc-mnop-xyz.")
    return ref


class GoogleMeetConnector(Connector):
    provider = PlatformProvider.google_meet
    display_name = "Google Meet"
    default_endpoints = {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "revoke": "https://oauth2.googleapis.com/revoke",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "api": "https://meet.googleapis.com/v2",
    }

    def configuration_problems(self) -> list[str]:
        s = get_settings()
        return [
            n
            for n, v in (("GOOGLE_CLIENT_ID", s.google_client_id), ("GOOGLE_CLIENT_SECRET", s.google_client_secret))
            if not v
        ]

    def client_id(self) -> str:
        return get_settings().google_client_id

    def client_secret(self) -> str:
        return get_settings().google_client_secret

    def requested_scopes(self) -> list[str]:
        return ["openid", "email", MEET_SCOPE]

    def authorization_params(self) -> dict[str, str]:
        return {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}

    def map_error(self, resp: Any) -> IntegrationError:
        from app.integrations.http import default_error, provider_error_code

        code = provider_error_code(resp)
        if resp.status_code == 400 and code == "invalid_grant":
            return IntegrationError(
                ErrorCategory.consent_revoked,
                "Authorization expired or was revoked; reconnect Google.",
                provider_code=code,
            )
        if resp.status_code == 403 and code in {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}:
            return IntegrationError(
                ErrorCategory.insufficient_scope, "The Meet read permission was not granted.", provider_code=code
            )
        if resp.status_code == 403:
            return IntegrationError(
                ErrorCategory.no_meeting_access,
                "Google denied access (your account may not have access to this meeting, or a Workspace administrator "
                "restricts the app).",
                provider_code=code,
            )
        return default_error(resp)

    def get_capabilities(self, scopes: set[str] | None, connected: bool) -> list[CapabilityState]:
        out = [cap(C.transcript_import, S.available, "Import a transcript exported from Google Docs (TXT) or JSON.")]
        if not self.is_configured():
            gate = cap(
                C.post_meeting_transcript,
                S.requires_configuration,
                "The Google OAuth client is not configured.",
                "Create an OAuth client in Google Cloud, enable the Meet REST API, set GOOGLE_CLIENT_ID/SECRET.",
            )
            out += [gate, gate.model_copy(update={"capability": C.list_meetings})]
        elif not connected:
            out += [
                cap(C.list_meetings, S.requires_user_consent, "Connect your Google account."),
                cap(C.post_meeting_transcript, S.requires_user_consent, "Connect your Google account."),
            ]
        elif MEET_SCOPE not in (scopes or set()):
            msg = "The Meet read-only permission was not granted."
            out += [
                cap(C.list_meetings, S.requires_user_consent, msg, "Reconnect and allow access to Meet."),
                cap(C.post_meeting_transcript, S.requires_user_consent, msg, "Reconnect and allow access to Meet."),
            ]
        else:
            out += [
                cap(C.list_meetings, S.available, "Your recent conference records."),
                cap(
                    C.post_meeting_transcript,
                    S.available,
                    "Transcripts are available after the meeting once Google generates the file; records expire after "
                    "30 days. Transcription must have been turned on in the meeting.",
                ),
            ]
        out += [
            cap(
                C.live_transcript,
                S.not_supported,
                "Google provides no real-time transcript API; the Meet Media API is developer preview and has no "
                "transcripts.",
                "Use post-meeting retrieval.",
            ),
            cap(
                C.live_audio,
                S.not_supported,
                "Meet Media API is developer preview only (all participants must enroll).",
            ),
            cap(C.speaker_metadata, S.available, "Participant display names (anonymous/phone users may be unnamed)."),
            cap(
                C.meeting_event_notifications,
                S.not_supported,
                "Workspace Events (Pub/Sub) notifications are not implemented; "
                "availability is polled with bounded backoff.",
            ),
            cap(C.recovery_after_disconnect, S.available, "Post-meeting retrieval is idempotent and can be re-run."),
        ]
        return out

    def fetch_account(self, access_token: str) -> AccountInfo:
        info = self.http.get_json(self.endpoint("userinfo"), token=access_token)
        return AccountInfo(account_id=str(info.get("sub", "")), display=str(info.get("email") or "Google account"))

    def revoke(self, tokens: TokenSet) -> bool:
        self.http.request("POST", self.endpoint("revoke"), data={"token": tokens.refresh_token or tokens.access_token})
        return True

    def list_available_meetings(self, access_token: str) -> list[AvailableMeeting]:
        since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self.http.get_json(
            f"{self.endpoint('api')}/conferenceRecords",
            token=access_token,
            params={"pageSize": "50", "filter": f'start_time>="{since}"'},
        )
        return [
            AvailableMeeting(
                provider_meeting_id=str(r["name"]),
                title=f"Google Meet ({r.get('space', '')})",
                start=_dt(r.get("startTime")),
                end=_dt(r.get("endTime")),
            )
            for r in data.get("conferenceRecords", [])
        ]

    def resolve_meeting(self, access_token: str, reference: str) -> ResolvedMeeting:
        ref = reference.strip()
        if re.fullmatch(r"conferenceRecords/[A-Za-z0-9_\-]+", ref):
            rec = self.http.get_json(f"{self.endpoint('api')}/{ref}", token=access_token)
            return ResolvedMeeting(
                provider_meeting_id=ref, join_url=None, title=None, resolved_ids={"space": str(rec.get("space", ""))}
            )
        code = parse_meeting_code(ref)
        return ResolvedMeeting(provider_meeting_id=code, join_url=f"https://meet.google.com/{code}", title=None)

    def _records(self, access_token: str, ref: ResolvedMeeting) -> list[dict[str, Any]]:
        if ref.provider_meeting_id.startswith("conferenceRecords/"):
            return [self.http.get_json(f"{self.endpoint('api')}/{ref.provider_meeting_id}", token=access_token)]
        data = self.http.get_json(
            f"{self.endpoint('api')}/conferenceRecords",
            token=access_token,
            params={"filter": f'space.meeting_code = "{ref.provider_meeting_id}"', "pageSize": "25"},
        )
        return list(data.get("conferenceRecords", []))

    def fetch_transcript(self, access_token: str, ref: ResolvedMeeting) -> TranscriptFetchResult:
        records = self._records(access_token, ref)
        if not records:
            return TranscriptFetchResult(
                ExternalTranscriptStatus.not_available,
                [],
                "No conference was found for this meeting code with your account.",
            )
        now = datetime.now(UTC)
        ended = sorted((r for r in records if r.get("endTime")), key=lambda r: r.get("startTime", ""), reverse=True)
        if not ended:
            return TranscriptFetchResult(ExternalTranscriptStatus.pending, [], "The meeting is still in progress.")
        record = ended[0]
        expire = _dt(record.get("expireTime"))
        if expire and expire <= now:
            return TranscriptFetchResult(
                ExternalTranscriptStatus.not_available,
                [],
                "The conference record has expired (Google keeps it for 30 days).",
            )
        api = self.endpoint("api")
        transcripts = self.http.get_json(f"{api}/{record['name']}/transcripts", token=access_token).get(
            "transcripts", []
        )
        end_time = _dt(record.get("endTime"))
        if not transcripts:
            recent = end_time is not None and now - end_time < timedelta(hours=2)
            return TranscriptFetchResult(
                ExternalTranscriptStatus.pending if recent else ExternalTranscriptStatus.not_available,
                [],
                "Google has not published a transcript yet."
                if recent
                else "No transcript exists (transcription was not turned on for this meeting).",
            )
        generated = [t for t in transcripts if t.get("state") == "FILE_GENERATED"]
        if not generated:
            return TranscriptFetchResult(
                ExternalTranscriptStatus.pending, [], "Google is still generating the transcript."
            )
        starts = [d for d in (_dt(t.get("startTime")) for t in generated) if d is not None]
        origin = min(starts) if starts else _dt(record.get("startTime"))
        names: dict[str, str | None] = {}
        events: list[CanonicalEvent] = []
        seq = 0
        for t in sorted(generated, key=lambda t: t.get("startTime", "")):
            token: str | None = None
            for _ in range(MAX_ENTRY_PAGES):  # bounded pagination
                params = {"pageSize": "100", **({"pageToken": token} if token else {})}
                page = self.http.get_json(f"{api}/{t['name']}/entries", token=access_token, params=params)
                for e in page.get("transcriptEntries", []):
                    text = clean_text(str(e.get("text") or ""))
                    if not text:
                        continue
                    participant = e.get("participant")
                    if participant and participant not in names:
                        names[participant] = self._participant_name(access_token, participant)
                    seq += 1
                    events.append(
                        CanonicalEvent(
                            provider="google_meet",
                            provider_meeting_id=ref.provider_meeting_id,
                            entry_id=str(e.get("name")),
                            speaker_id=participant,
                            speaker_display_name=names.get(participant) if participant else None,
                            start_timestamp_ms=offset_ms(e.get("startTime"), origin),
                            end_timestamp_ms=offset_ms(e.get("endTime"), origin),
                            source_language=language_from_code(e.get("languageCode")),
                            original_text=text,
                            provider_sequence=seq,
                            source_metadata={
                                "conference_record": record["name"],
                                "transcript": t["name"],
                                "language_code": e.get("languageCode"),
                            },
                        )
                    )
                token = page.get("nextPageToken")
                if not token:
                    break
        return TranscriptFetchResult(
            ExternalTranscriptStatus.available, events, f"{len(events)} transcript entries retrieved from Google Meet."
        )

    def _participant_name(self, access_token: str, participant: str) -> str | None:
        try:
            p = self.http.get_json(f"{self.endpoint('api')}/{participant}", token=access_token)
        except IntegrationError:
            return None  # never invent a name
        for kind in ("signedinUser", "anonymousUser", "phoneUser"):
            if isinstance(p.get(kind), dict) and p[kind].get("displayName"):
                return str(p[kind]["displayName"])
        return None
