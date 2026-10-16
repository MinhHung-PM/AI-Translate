"""Zoom webhook authenticity checks.

* Signature: ``x-zm-signature = "v0=" + HMAC_SHA256(secret_token, f"v0:{ts}:{raw_body}")``,
  timestamp header ``x-zm-request-timestamp`` (as in Zoom's official RTMS SDK examples).
* URL validation challenge: ``endpoint.url_validation`` → respond with ``plainToken`` and
  ``encryptedToken = HMAC_SHA256(secret_token, plainToken)`` (hex).
* Replay protection: timestamp must be within ``INTEGRATION_WEBHOOK_TOLERANCE_SECONDS``
  and each event is recorded once in ``provider_events`` (unique dedup key).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from app.core.config import get_settings
from app.integrations.errors import ErrorCategory, IntegrationError


def _hmac(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(
    raw_body: bytes, timestamp: str | None, signature: str | None, *, now: float | None = None
) -> None:
    secret = get_settings().zoom_webhook_secret_token
    if not secret:
        raise IntegrationError(ErrorCategory.not_configured, "Zoom webhooks are not configured")
    if not timestamp or not signature:
        raise IntegrationError(ErrorCategory.invalid_signature, "Missing signature headers")
    try:
        ts = int(timestamp)
    except ValueError:
        raise IntegrationError(ErrorCategory.invalid_signature, "Invalid timestamp") from None
    current = now if now is not None else time.time()
    # Zoom sends milliseconds; accept seconds too.
    ts_s = ts / 1000 if ts > 10**11 else ts
    if abs(current - ts_s) > get_settings().integration_webhook_tolerance_seconds:
        raise IntegrationError(ErrorCategory.invalid_signature, "Stale webhook timestamp")
    expected = "v0=" + _hmac(secret, f"v0:{timestamp}:{raw_body.decode('utf-8', errors='strict')}")
    if not hmac.compare_digest(expected, signature):
        raise IntegrationError(ErrorCategory.invalid_signature, "Invalid webhook signature")


def url_validation_response(payload: dict[str, Any]) -> dict[str, str]:
    plain = str((payload.get("payload") or {}).get("plainToken", ""))
    if not plain or len(plain) > 256:
        raise IntegrationError(ErrorCategory.invalid_request, "Invalid validation challenge")
    return {"plainToken": plain, "encryptedToken": _hmac(get_settings().zoom_webhook_secret_token, plain)}


def dedup_key(payload: dict[str, Any]) -> str:
    event = str(payload.get("event", ""))
    body = payload.get("payload") or {}
    obj = body.get("object") or {}
    parts = [
        event,
        str(payload.get("event_ts", "")),
        str(body.get("meeting_uuid") or obj.get("uuid") or ""),
        str(body.get("rtms_stream_id") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
