from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def key_hint(api_key: str) -> str:
    """Last four characters only — enough for a user to recognise their key."""
    return "…" + api_key[-4:] if len(api_key) >= 12 else "…"
