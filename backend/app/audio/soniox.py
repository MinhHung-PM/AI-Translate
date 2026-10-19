"""Soniox real-time speech recognition + translation (alternative to OpenAI).

Contract taken from Soniox's official SDKs (``soniox`` 2.10.0 on PyPI, which ships
the API's OpenAPI document, and ``@soniox/speech-to-text-web`` 1.4.0), checked
2026-10-19:

* ``POST {base}/auth/temporary-api-key`` ``{usage_type: "transcribe_websocket",
  expires_in_seconds (1–3600), single_use, max_session_duration_seconds (≤ 18000)}``
  → 201 ``{api_key, expires_at}``. The user's key never reaches the browser.
* The browser opens ``wss://stt-rt.soniox.com/transcribe-websocket``, sends the JSON
  config (with the temporary ``api_key``) as the first message, then raw audio.
  Responses carry ``tokens[]`` ``{text, start_ms, end_ms, is_final, speaker,
  language, translation_status: original|translation|none}``; ``<end>`` marks an
  endpoint when ``enable_endpoint_detection`` is on.

The session config is built here (server side) so glossary terms and limits stay
under the server's control; the browser only adds the temporary key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.ai.base import Credentials, ProviderError, ProviderErrorCode
from app.audio import stt as stt_module

logger = logging.getLogger(__name__)

WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class SonioxToken:
    value: str
    expires_at: str
    model: str
    websocket_url: str
    config: dict[str, Any] = field(default_factory=dict)


def build_config(
    *,
    model: str,
    target_language: str | None,
    language_hints: list[str],
    diarize: bool,
    terms: list[str],
    translation_terms: list[tuple[str, str]],
    domain: str | None,
) -> dict[str, Any]:
    """Session config (everything but ``api_key``), sent by the browser as the first message."""
    context: dict[str, Any] = {}
    if domain:
        context["general"] = [{"key": "domain", "value": domain[:200]}]
    if terms:
        context["terms"] = terms[:100]
    if translation_terms and target_language:
        context["translation_terms"] = [{"source": s, "target": t} for s, t in translation_terms[:100]]
    config: dict[str, Any] = {
        "model": model,
        "audio_format": "pcm_s16le",
        "sample_rate": SAMPLE_RATE,
        "num_channels": 1,
        "enable_language_identification": True,
        "enable_speaker_diarization": diarize,
        "enable_endpoint_detection": True,
    }
    if language_hints:
        config["language_hints"] = language_hints
    if context:
        config["context"] = context
    if target_language:
        config["translation"] = {"type": "one_way", "target_language": target_language}
    return config


def create_temporary_key(
    creds: Credentials, *, ttl_seconds: int, max_session_seconds: int, timeout_s: float
) -> tuple[str, str]:
    if not creds.api_key:
        raise ProviderError(ProviderErrorCode.not_configured, "A Soniox API key is required")
    base = (creds.base_url or "https://api.soniox.com/v1").rstrip("/")
    body = {
        "usage_type": "transcribe_websocket",
        "expires_in_seconds": max(1, min(ttl_seconds, 3600)),
        "single_use": True,
        "max_session_duration_seconds": max(1, min(max_session_seconds, 18000)),
    }
    try:
        with httpx.Client(
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {creds.api_key}"},
            transport=stt_module._transport_override,
            follow_redirects=False,
        ) as client:
            resp = client.post(f"{base}/auth/temporary-api-key", json=body)
    except httpx.TimeoutException:
        raise ProviderError(ProviderErrorCode.timeout, "Soniox did not respond in time", retryable=True) from None
    except httpx.HTTPError:
        raise ProviderError(ProviderErrorCode.unavailable, "Could not reach Soniox", retryable=True) from None
    status = resp.status_code
    if status in (200, 201):
        data = resp.json()
        value = data.get("api_key")
        if not isinstance(value, str) or not value:
            raise ProviderError(ProviderErrorCode.invalid_output, "Soniox returned no temporary key")
        return value, str(data.get("expires_at") or "")
    if status == 401:
        raise ProviderError(ProviderErrorCode.auth_failed, "The Soniox API key was rejected")
    if status == 403:
        raise ProviderError(
            ProviderErrorCode.permission_denied,
            "This Soniox API key may not create temporary keys (enable the 'Temporary API keys' permission)",
        )
    if status == 429:
        raise ProviderError(ProviderErrorCode.rate_limited, "Soniox rate limit or quota exceeded", retryable=True)
    if status >= 500:
        raise ProviderError(ProviderErrorCode.unavailable, f"Soniox error {status}", retryable=True)
    raise ProviderError(ProviderErrorCode.bad_request, f"Soniox rejected the request ({status})")
