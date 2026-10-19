"""Request dependencies: authentication, CSRF and rate limiting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, NotAuthenticated
from app.core.rate_limit import rate_limiter
from app.core.security import constant_time_equals
from app.db.base import utcnow
from app.db.session import get_db
from app.models import User, UserSession
from app.services.sessions import resolve_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


@dataclass
class AuthContext:
    user: User
    session: UserSession
    ip: str | None


DB = Annotated[Session, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_auth(request: Request, db: DB) -> AuthContext:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise NotAuthenticated("Authentication required")
    session = resolve_session(db, token)
    if session is None:
        raise NotAuthenticated("Session expired or invalid")
    user = session.user
    if not user.is_active:
        raise NotAuthenticated("Account is disabled")
    # CSRF: cookie-authenticated state-changing requests must echo the
    # per-session token in a header (double-submit pattern). Cross-site
    # forms cannot read or set it.
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not constant_time_equals(header, session.csrf_token):
            raise Forbidden("Missing or invalid CSRF token")
    now = utcnow()
    if (now - session.last_seen_at).total_seconds() > 60:
        session.last_seen_at = now
        db.commit()
    return AuthContext(user=user, session=session, ip=client_ip(request))


Auth = Annotated[AuthContext, Depends(get_auth)]


def rate_key(auth: AuthContext) -> str:
    """Rate limits apply per user — per browser session on a shared team site, where everyone
    signs in as the same shared account."""
    return f"s{auth.session.id}" if get_settings().auth_mode == "shared" else str(auth.user.id)


def ai_rate_limit(bucket: str) -> Callable[[AuthContext], AuthContext]:
    def _check(auth: Auth) -> AuthContext:
        rate_limiter.check(f"{bucket}:{rate_key(auth)}", get_settings().ai_rate_limit_per_minute)
        return auth

    return _check
