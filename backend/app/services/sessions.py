from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_token, new_token
from app.db.base import utcnow
from app.models import OidcLoginState, User, UserSession


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    settings = get_settings()
    token = new_token()
    session = UserSession(
        token_hash=hash_token(token),
        csrf_token=new_token(24),
        user_id=user.id,
        expires_at=utcnow() + timedelta(minutes=settings.session_ttl_minutes),
        ip_address=ip,
        user_agent=(user_agent or "")[:256] or None,
    )
    user.last_login_at = utcnow()
    db.add(session)
    db.flush()
    return token, session


def resolve_session(db: Session, token: str) -> UserSession | None:
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None:
        return None
    expires = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    return session


def revoke_session(db: Session, session: UserSession) -> None:
    # Deleting the row cascades to session_secrets: session-only API keys
    # are destroyed at logout.
    db.delete(session)


def purge_expired_sessions(db: Session) -> int:
    now = utcnow()
    result = db.execute(
        delete(UserSession).where(or_(UserSession.expires_at <= now, UserSession.revoked_at.is_not(None)))
    )
    db.execute(delete(OidcLoginState).where(OidcLoginState.created_at <= now - timedelta(minutes=15)))
    return int(getattr(result, "rowcount", 0) or 0)
