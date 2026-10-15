"""Adapter for the OpenAI Chat Completions API and compatible endpoints.

Only this module knows the wire format. Errors are mapped to
``ProviderError`` and every message is redacted (upstream bodies can echo
request headers on some gateways).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.ai.base import (
    CompletionResult,
    ConnectionTestResult,
    Credentials,
    ModelParams,
    ProviderError,
    ProviderErrorCode,
    TokenUsage,
    estimate_tokens,
)
from app.core.logging import redact_value

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(
        self,
        key: str,
        default_base_url: str | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.key = key
        self._default_base_url = default_base_url
        self._timeout = timeout_seconds
        self._transport = transport  # injectable for tests

    def _client(self, creds: Credentials) -> httpx.Client:
        base_url = creds.base_url or self._default_base_url
        if not base_url:
            raise ProviderError(ProviderErrorCode.not_configured, "Provider base URL is not configured")
        if not creds.api_key:
            raise ProviderError(ProviderErrorCode.not_configured, "API key is required for this provider")
        return httpx.Client(
            base_url=base_url,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {creds.api_key}"},
            transport=self._transport,
            follow_redirects=False,  # redirects could bounce the Authorization header elsewhere
        )

    def _map_error(self, exc: Exception, creds: Credentials) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError(ProviderErrorCode.timeout, "The AI provider timed out", retryable=True)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            detail = ""
            try:
                body = exc.response.json()
                detail = str(body.get("error", {}).get("message", ""))[:200]
            except Exception:  # noqa: S110 - body is optional diagnostic detail
                pass
            detail = redact_value(detail, creds.api_key)
            if status == 401:
                return ProviderError(ProviderErrorCode.auth_failed, "The API key was rejected by the provider")
            if status == 403:
                return ProviderError(ProviderErrorCode.permission_denied, "The API key lacks permission for this model")
            if status == 429:
                code = ProviderErrorCode.quota_exceeded if "quota" in detail.lower() else ProviderErrorCode.rate_limited
                return ProviderError(code, "The provider rate limit or quota was exceeded", retryable=True)
            if status >= 500:
                return ProviderError(ProviderErrorCode.unavailable, f"Provider error {status}", retryable=True)
            return ProviderError(ProviderErrorCode.bad_request, f"Provider rejected the request ({status}) {detail}")
        if isinstance(exc, httpx.HTTPError):
            return ProviderError(ProviderErrorCode.unavailable, "Could not reach the AI provider", retryable=True)
        return ProviderError(ProviderErrorCode.unavailable, "Unexpected provider failure")

    def list_models(self, creds: Credentials) -> list[str] | None:
        try:
            with self._client(creds) as client:
                resp = client.get("/models")
                resp.raise_for_status()
                data = resp.json().get("data", [])
                return sorted(str(m.get("id")) for m in data if m.get("id"))
        except Exception as exc:
            raise self._map_error(exc, creds) from None

    def test_connection(self, creds: Credentials, model: str) -> ConnectionTestResult:
        try:
            models = self.list_models(creds)
        except ProviderError as err:
            if err.code in {ProviderErrorCode.auth_failed, ProviderErrorCode.not_configured}:
                return ConnectionTestResult(ok=False, message=err.message)
            models = None  # some compatible servers do not implement /models
        try:
            self.complete_json(
                creds,
                model,
                'Reply with the JSON object {"ok": true}.',
                "ping",
                ModelParams(temperature=0, max_output_tokens=20),
            )
        except ProviderError as err:
            return ConnectionTestResult(ok=False, message=err.message, models=models)
        return ConnectionTestResult(ok=True, message="Connection succeeded", models=models)

    def complete_json(
        self, creds: Credentials, model: str, system: str, user: str, params: ModelParams
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": params.temperature,
            "max_tokens": params.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if params.seed is not None:
            payload["seed"] = params.seed
        try:
            with self._client(creds) as client:
                resp = client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            raise self._map_error(exc, creds) from None
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(ProviderErrorCode.invalid_output, "Provider response had no message content") from None
        usage_raw = body.get("usage") or {}
        if "prompt_tokens" in usage_raw:
            usage = TokenUsage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0)),
                output_tokens=int(usage_raw.get("completion_tokens", 0)),
                reported_by_provider=True,
            )
        else:
            usage = TokenUsage(estimate_tokens(system + user), estimate_tokens(text), reported_by_provider=False)
        return CompletionResult(text=text, usage=usage, model=str(body.get("model") or model))
