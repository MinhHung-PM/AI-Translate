"""OpenAI Realtime transcription (streaming captions).

The server mints a short-lived client secret for a ``transcription`` session
(``POST /v1/realtime/client_secrets``, contract from openai/openai-openapi,
verified 2026-10-16). The browser then streams audio to OpenAI over WebRTC
(``POST /v1/realtime/calls`` with the ephemeral key) and receives
``conversation.item.input_audio_transcription.delta`` (interim words) and
``...completed`` (final utterance) events. Final utterances are posted back
to Memo Hub for storage and translation. The user's API key never reaches the
browser; the ephemeral key expires after ``ttl_seconds``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.base import Credentials, ProviderError, ProviderErrorCode
from app.audio import stt as stt_module

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeToken:
    value: str
    expires_at: int
    model: str
    # True when the session has no server VAD: the browser must send
    # input_audio_buffer.commit at the end of each utterance.
    client_commits: bool


WHISPER = "gpt-realtime-whisper"  # true streaming: no VAD, text emitted while speaking ("delay")


def _session(
    model: str,
    languages: list[str],
    keywords: list[str],
    noise_reduction: str | None,
    live_model: str,
    delay: str = "low",
) -> dict[str, Any]:
    transcription: dict[str, Any] = {"model": model}
    if model == WHISPER:
        # Per spec: prompt is not supported, turn_detection must be null, "delay" trades latency/accuracy.
        if len(languages) == 1:
            transcription["language"] = languages[0]
        transcription["delay"] = delay
    elif model == live_model:
        if languages:
            transcription["languages"] = languages
        if keywords:
            transcription["keywords"] = keywords
    else:
        if len(languages) == 1:
            transcription["language"] = languages[0]
        if keywords:
            transcription["prompt"] = "Thuật ngữ / 用語 / Terms: " + ", ".join(keywords)
    return {
        "type": "transcription",
        "audio": {
            "input": {
                "transcription": transcription,
                # null turns OpenAI's input noise reduction off (spec: RealtimeTranscriptionSessionCreateRequestGA).
                "noise_reduction": {"type": noise_reduction} if noise_reduction else None,
                "turn_detection": None
                if model == WHISPER
                else {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 350,
                },
            }
        },
    }


def create_transcription_token(
    creds: Credentials,
    *,
    languages: list[str],
    keywords: list[str],
    noise_reduction: str | None,
    models: list[str],
    live_model: str,
    delay: str,
    ttl_seconds: int,
    timeout_s: float,
) -> RealtimeToken:
    """Tries ``models`` in order (e.g. whisper → live-transcribe → gpt-4o-transcribe),
    falling back when the account cannot use one."""
    if not creds.api_key:
        raise ProviderError(ProviderErrorCode.not_configured, "An OpenAI API key is required for live captions")
    base = (creds.base_url or "https://api.openai.com/v1").rstrip("/")
    last: httpx.Response | None = None
    candidates = list(dict.fromkeys(models))
    for idx, candidate in enumerate(candidates):
        body = {
            "expires_after": {"anchor": "created_at", "seconds": ttl_seconds},
            "session": _session(candidate, languages, keywords, noise_reduction, live_model, delay),
        }
        try:
            with httpx.Client(
                timeout=timeout_s,
                headers={"Authorization": f"Bearer {creds.api_key}"},
                transport=stt_module._transport_override,
                follow_redirects=False,
            ) as client:
                resp = client.post(f"{base}/realtime/client_secrets", json=body)
        except httpx.TimeoutException:
            raise ProviderError(ProviderErrorCode.timeout, "OpenAI did not respond in time", retryable=True) from None
        except httpx.HTTPError:
            raise ProviderError(ProviderErrorCode.unavailable, "Could not reach OpenAI", retryable=True) from None
        if resp.status_code == 200:
            data = resp.json()
            value = data.get("value") or (data.get("client_secret") or {}).get("value")
            if not isinstance(value, str) or not value:
                raise ProviderError(ProviderErrorCode.invalid_output, "OpenAI returned no client secret")
            return RealtimeToken(
                value=value,
                expires_at=int(data.get("expires_at") or 0),
                model=candidate,
                client_commits=candidate == WHISPER,
            )
        last = resp
        more = idx < len(candidates) - 1
        if resp.status_code in (400, 404) and more and any(w in resp.text.lower() for w in ("model", "delay", "turn")):
            logger.info("realtime.model_unavailable", extra={"model": candidate})
            continue
        break
    assert last is not None
    status = last.status_code
    if status == 401:
        raise ProviderError(ProviderErrorCode.auth_failed, "The OpenAI API key was rejected")
    if status == 403:
        raise ProviderError(ProviderErrorCode.permission_denied, "This API key cannot use the OpenAI Realtime API")
    if status == 429:
        raise ProviderError(ProviderErrorCode.rate_limited, "OpenAI rate limit or quota exceeded", retryable=True)
    if status >= 500:
        raise ProviderError(ProviderErrorCode.unavailable, f"OpenAI error {status}", retryable=True)
    raise ProviderError(ProviderErrorCode.bad_request, f"OpenAI rejected the live caption session ({status})")
