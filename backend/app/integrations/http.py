"""HTTP client for provider APIs with normalized, redacted errors.

Error messages never include provider response bodies; only a short provider
error *code* is extracted for mapping (e.g. ``GraphAccessToTranscriptsDisabled``).
The transport is injectable so contract tests run against fixtures built from
the official API schemas without network access.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx

from app.integrations.errors import ErrorCategory, IntegrationError

_transport_override: httpx.BaseTransport | None = None
_CODE_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    """Tests / sandbox only."""
    global _transport_override
    _transport_override = transport


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 3600.0))
    except ValueError:
        return None


def provider_error_code(resp: httpx.Response) -> str | None:
    """Extract a short machine code from common error envelopes (Graph, Google, Zoom, OAuth)."""
    try:
        body = resp.json()
    except Exception:
        return None
    candidates: list[Any] = []
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            inner = err.get("innerError") or err.get("innererror") or {}
            if isinstance(inner, dict):
                candidates.append(inner.get("code"))
            candidates += [err.get("status"), err.get("code")]
            for d in err.get("details") or []:
                if isinstance(d, dict):
                    candidates.append(d.get("reason"))
        else:
            candidates.append(err)  # OAuth: {"error": "invalid_grant"}
        candidates.append(body.get("code"))  # Zoom: {"code": 124, "message": ...}
    for c in candidates:
        if c is not None and _CODE_RE.match(str(c)):
            return str(c)
    return None


def default_error(resp: httpx.Response) -> IntegrationError:
    code = provider_error_code(resp)
    status = resp.status_code
    if status == 401:
        return IntegrationError(
            ErrorCategory.token_expired, "The platform rejected the access token", provider_code=code
        )
    if status == 403:
        return IntegrationError(
            ErrorCategory.insufficient_scope, "The account lacks permission for this operation", provider_code=code
        )
    if status == 404:
        return IntegrationError(
            ErrorCategory.meeting_not_found, "The meeting or resource was not found", provider_code=code
        )
    if status == 429:
        return IntegrationError(
            ErrorCategory.rate_limited,
            "The platform rate limit was reached",
            retry_after=parse_retry_after(resp.headers.get("Retry-After")),
            provider_code=code,
        )
    if status >= 500:
        return IntegrationError(
            ErrorCategory.provider_unavailable,
            f"The platform returned an error ({status})",
            retry_after=parse_retry_after(resp.headers.get("Retry-After")),
            provider_code=code,
        )
    return IntegrationError(
        ErrorCategory.invalid_request, f"The platform rejected the request ({status})", provider_code=code
    )


class ProviderHttp:
    def __init__(self, error_mapper: Callable[[httpx.Response], IntegrationError] | None = None, timeout: float = 20.0):
        self._map = error_mapper or default_error
        self._timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json: Any = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        try:
            with httpx.Client(timeout=self._timeout, transport=_transport_override, follow_redirects=False) as client:
                resp = client.request(method, url, headers=h, params=params, data=data, json=json, auth=auth)
                if resp.status_code in (301, 302, 307, 308) and "location" in resp.headers:
                    # Follow one redirect for file downloads WITHOUT forwarding the bearer token.
                    resp = client.get(resp.headers["location"])
        except httpx.TimeoutException:
            raise IntegrationError(ErrorCategory.provider_unavailable, "The platform timed out") from None
        except httpx.HTTPError:
            raise IntegrationError(ErrorCategory.provider_unavailable, "Could not reach the platform") from None
        if resp.status_code >= 400:
            raise self._map(resp)
        return resp

    def get_json(self, url: str, **kw: Any) -> dict[str, Any]:
        resp = self.request("GET", url, **kw)
        try:
            data = resp.json()
        except ValueError:
            raise IntegrationError(
                ErrorCategory.invalid_response, "The platform returned an invalid response"
            ) from None
        if not isinstance(data, dict):
            raise IntegrationError(ErrorCategory.invalid_response, "The platform returned an unexpected response")
        return data
