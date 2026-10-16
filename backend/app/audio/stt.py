"""Speech-to-text with speaker diarization.

``OpenAIDiarizingSTT`` calls ``POST {base}/audio/transcriptions`` with
``model=gpt-4o-transcribe-diarize`` and ``response_format=diarized_json``
(contract verified against openai/openai-openapi, 2026-10-16). Up to four
known speakers can be passed as 2–10 s reference clips so labels stay stable
across chunks. ``MockSTT`` is a deterministic DEV/TEST stand-in: it does not
recognise speech and its output is labelled ``[MOCK STT]``.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.ai.base import Credentials, ProviderError, ProviderErrorCode
from app.core.logging import redact_value

logger = logging.getLogger(__name__)

MAX_KNOWN_SPEAKERS = 4
REF_MIN_S, REF_MAX_S = 2.0, 10.0

_transport_override: httpx.BaseTransport | None = None


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    """Tests only: route STT HTTP calls to a mock transport."""
    global _transport_override
    _transport_override = transport


@dataclass(frozen=True)
class KnownSpeaker:
    name: str
    reference_wav: bytes


@dataclass(frozen=True)
class DiarizedSegment:
    text: str
    start_s: float
    end_s: float
    speaker: str | None


@dataclass
class SttResult:
    segments: list[DiarizedSegment]
    duration_s: float
    model: str
    known_names: list[str] = field(default_factory=list)


class SpeechToText(Protocol):
    key: str
    model: str
    is_mock: bool

    def transcribe(
        self, wav: bytes, *, language: str | None, known: list[KnownSpeaker], diarize: bool
    ) -> SttResult: ...


def _data_url(wav: bytes) -> str:
    return "data:audio/wav;base64," + base64.b64encode(wav).decode()


class OpenAIDiarizingSTT:
    is_mock = False

    def __init__(self, creds: Credentials, model: str, timeout_s: float, key: str = "openai") -> None:
        if not creds.api_key:
            raise ProviderError(ProviderErrorCode.not_configured, "An OpenAI API key is required for speech-to-text")
        self.key = key
        self.model = model
        self._creds = creds
        self._timeout = timeout_s

    def _error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError(ProviderErrorCode.timeout, "Speech-to-text timed out", retryable=True)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            try:
                detail = str(exc.response.json().get("error", {}).get("message", ""))[:200]
            except Exception:
                detail = ""
            detail = redact_value(detail, self._creds.api_key)
            if status == 401:
                return ProviderError(ProviderErrorCode.auth_failed, "The OpenAI API key was rejected")
            if status == 403:
                return ProviderError(
                    ProviderErrorCode.permission_denied, f"The API key cannot use {self.model} for speech-to-text"
                )
            if status == 429:
                code = ProviderErrorCode.quota_exceeded if "quota" in detail.lower() else ProviderErrorCode.rate_limited
                return ProviderError(code, "The speech-to-text rate limit or quota was exceeded", retryable=True)
            if status >= 500:
                return ProviderError(ProviderErrorCode.unavailable, f"Speech-to-text error {status}", retryable=True)
            return ProviderError(
                ProviderErrorCode.bad_request, f"Speech-to-text rejected the audio ({status}) {detail}"
            )
        if isinstance(exc, httpx.HTTPError):
            return ProviderError(
                ProviderErrorCode.unavailable, "Could not reach the speech-to-text service", retryable=True
            )
        return ProviderError(ProviderErrorCode.unavailable, "Unexpected speech-to-text failure")

    def transcribe(self, wav: bytes, *, language: str | None, known: list[KnownSpeaker], diarize: bool) -> SttResult:
        known = known[:MAX_KNOWN_SPEAKERS] if diarize else []
        data: dict[str, str | list[str]] = {"model": self.model, "response_format": "diarized_json"}
        data["chunking_strategy"] = "auto"
        if language:
            data["language"] = language
        if known:
            data["known_speaker_names[]"] = [k.name for k in known]
            data["known_speaker_references[]"] = [_data_url(k.reference_wav) for k in known]
        base = (self._creds.base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            with httpx.Client(
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._creds.api_key}"},
                transport=_transport_override,
                follow_redirects=False,
            ) as client:
                resp = client.post(
                    f"{base}/audio/transcriptions", data=data, files={"file": ("chunk.wav", wav, "audio/wav")}
                )
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            raise self._error(exc) from None
        try:
            segments = [
                DiarizedSegment(
                    text=str(s.get("text") or "").strip(),
                    start_s=float(s.get("start") or 0.0),
                    end_s=float(s.get("end") or s.get("start") or 0.0),
                    speaker=(str(s["speaker"]) if s.get("speaker") not in (None, "") else None) if diarize else None,
                )
                for s in body.get("segments") or []
            ]
            if not segments and body.get("text"):
                segments = [DiarizedSegment(str(body["text"]).strip(), 0.0, float(body.get("duration") or 0), None)]
            duration = float(body.get("duration") or 0.0)
        except (TypeError, ValueError, AttributeError):
            raise ProviderError(ProviderErrorCode.invalid_output, "Unexpected speech-to-text response") from None
        return SttResult(
            segments=[s for s in segments if s.text],
            duration_s=duration,
            model=self.model,
            known_names=[k.name for k in known],
        )


class MockSTT:
    """DEV/TEST ONLY. Does not recognise speech: returns one labelled segment
    per chunk so the capture → diarization → translation pipeline can be
    exercised without an API key."""

    key = "mock"
    model = "mock-stt"
    is_mock = True

    def transcribe(self, wav: bytes, *, language: str | None, known: list[KnownSpeaker], diarize: bool) -> SttResult:
        from app.audio.wav import parse_wav

        audio = parse_wav(wav, max_seconds=3600)
        speaker = (known[0].name if known else "A") if diarize else None
        text = f"[MOCK STT] Đoạn âm thanh {audio.duration_s:.1f} giây (không nhận dạng giọng nói thật)."
        return SttResult(
            segments=[DiarizedSegment(text, 0.0, audio.duration_s, speaker)],
            duration_s=audio.duration_s,
            model=self.model,
            known_names=[k.name for k in known],
        )
