"""Outbound URL validation for user-configurable provider endpoints.

A user-supplied ``base_url`` is an SSRF vector: without checks a user could
make the server call cloud metadata endpoints or internal services and read
the response through error messages. We require HTTPS and refuse hosts that
resolve to private, loopback, link-local or reserved addresses unless the
operator explicitly allows it (local LLM servers in development).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.ai.base import ProviderError, ProviderErrorCode


def validate_provider_base_url(url: str, *, allow_private: bool, allowlist: list[str]) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ProviderError(ProviderErrorCode.bad_request, "Base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ProviderError(ProviderErrorCode.bad_request, "Base URL must not contain credentials")
    host = parsed.hostname.lower()
    if allowlist and host not in {h.lower() for h in allowlist}:
        raise ProviderError(ProviderErrorCode.bad_request, "Base URL host is not in the allowed list")
    if parsed.scheme != "https" and not allow_private:
        raise ProviderError(ProviderErrorCode.bad_request, "Base URL must use HTTPS")
    if not allow_private:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ProviderError(ProviderErrorCode.bad_request, "Base URL host cannot be resolved") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ProviderError(ProviderErrorCode.bad_request, "Base URL resolves to a non-public address")
    return url.strip().rstrip("/")
