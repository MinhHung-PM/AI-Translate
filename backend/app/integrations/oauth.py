"""OAuth for platform connections: state, PKCE, encrypted token storage,
refresh with rotation, and disconnect.

Security properties:
* ``state`` is random, single-use, expires after ``INTEGRATION_OAUTH_STATE_TTL_MINUTES``
  and is bound to the user **and** the login session that started the flow.
* PKCE (S256) is used for every provider; the verifier never leaves the server.
* The redirect URI is derived from ``PUBLIC_BASE_URL`` only (never from the request) and
  must match the URI registered at the provider.
* Tokens are AES-256-GCM encrypted with the existing keyring; associated data binds the
  ciphertext to the connection and token kind. Tokens are never returned by any API.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import CryptoError
from app.core.errors import Conflict, NotAuthenticated
from app.db.base import utcnow
from app.integrations.base import Connector, TokenSet
from app.integrations.errors import ErrorCategory, IntegrationError
from app.models import PlatformConnection, PlatformCredential, PlatformOAuthState, User, UserSession
from app.models.enums import ConnectionState
from app.services.provider_config import get_keyring

REFRESH_MARGIN = timedelta(seconds=90)


def redirect_uri(provider: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
        raise IntegrationError(ErrorCategory.not_configured, "PUBLIC_BASE_URL is not a valid origin")
    if get_settings().is_production and parsed.scheme != "https":
        raise IntegrationError(ErrorCategory.not_configured, "PUBLIC_BASE_URL must use HTTPS in production")
    return f"{base}/api/v1/integrations/{provider}/oauth/callback"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _aad(connection: PlatformConnection, kind: str) -> str:
    return f"platform-credential:{connection.id}:{connection.user_id}:{kind}"


def get_connection(db: Session, user: User, connector: Connector) -> PlatformConnection | None:
    return db.scalar(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user.id, PlatformConnection.provider == connector.provider
        )
    )


def begin(db: Session, user: User, session: UserSession, connector: Connector) -> str:
    if not connector.is_configured():
        raise IntegrationError(
            ErrorCategory.not_configured, f"{connector.display_name} is not configured on this server"
        )
    if get_keyring() is None:
        raise IntegrationError(
            ErrorCategory.not_configured, "Secure token storage is not configured (SECRET_ENCRYPTION_KEYS)"
        )
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    ttl = timedelta(minutes=get_settings().integration_oauth_state_ttl_minutes)
    db.execute(delete(PlatformOAuthState).where(PlatformOAuthState.created_at < utcnow() - ttl))
    db.add(
        PlatformOAuthState(
            state=state, provider=connector.provider, user_id=user.id, session_id=session.id, code_verifier=verifier
        )
    )
    conn = get_connection(db, user, connector)
    if conn is None:
        conn = PlatformConnection(user_id=user.id, provider=connector.provider)
        db.add(conn)
    if conn.state != ConnectionState.connected:
        conn.state = ConnectionState.awaiting_authorization
    conn.last_attempt_at = utcnow()
    conn.is_sandbox = connector.is_sandbox()
    db.flush()
    return connector.begin_authorization(state, challenge, redirect_uri(connector.provider.value))


def _consume_state(db: Session, user: User, session: UserSession, connector: Connector, state: str) -> str:
    row = db.scalar(select(PlatformOAuthState).where(PlatformOAuthState.state == state)) if state else None
    if row is None:
        raise NotAuthenticated("Invalid or expired authorization state")
    db.delete(row)
    db.commit()  # single use: consumed even when validation below fails
    ttl = timedelta(minutes=get_settings().integration_oauth_state_ttl_minutes)
    if (
        row.provider != connector.provider
        or row.user_id != user.id
        or row.session_id != session.id
        or row.created_at < utcnow() - ttl
    ):
        raise NotAuthenticated("Invalid or expired authorization state")
    return row.code_verifier


def classify_authorization_error(error: str, description: str) -> IntegrationError:
    text = f"{error} {description}"
    if (
        any(
            code in text
            for code in ("AADSTS65001", "AADSTS90094", "AADSTS90008", "admin_policy_enforced", "AADSTS65004")
        )
        or "admin" in description.lower()
    ):
        return IntegrationError(
            ErrorCategory.admin_approval_required,
            "An administrator must approve this app's permissions before you can connect.",
        )
    if error in {"access_denied", "consent_required"}:
        return IntegrationError(ErrorCategory.consent_revoked, "Authorization was declined.")
    return IntegrationError(ErrorCategory.invalid_request, "The platform returned an authorization error.")


def complete(
    db: Session,
    user: User,
    session: UserSession,
    connector: Connector,
    *,
    code: str,
    state: str,
    error: str | None,
    error_description: str | None,
) -> PlatformConnection:
    verifier = _consume_state(db, user, session, connector, state)
    conn = get_connection(db, user, connector)
    if conn is None:
        raise Conflict("No pending connection")
    conn.last_attempt_at = utcnow()
    try:
        if error:
            raise classify_authorization_error(error[:100], (error_description or "")[:500])
        if not code:
            raise IntegrationError(ErrorCategory.invalid_request, "Missing authorization code")
        tokens = connector.complete_authorization(code, verifier, redirect_uri(connector.provider.value))
        account = connector.fetch_account(tokens.access_token)  # a real API call = connection test
    except IntegrationError as err:
        conn.state = (
            ConnectionState.admin_approval_required
            if err.category == ErrorCategory.admin_approval_required
            else ConnectionState.error
        )
        conn.last_error_category = err.category.value
        conn.last_error_message = err.message[:500]
        raise
    store_tokens(conn, tokens)
    conn.account_id = account.account_id[:255]
    conn.account_display = account.display[:320]
    conn.granted_scopes = " ".join(sorted(tokens.scopes))
    conn.state = ConnectionState.connected
    conn.last_success_at = utcnow()
    conn.last_error_category = None
    conn.last_error_message = None
    conn.is_sandbox = connector.is_sandbox()
    db.flush()
    return conn


def store_tokens(conn: PlatformConnection, tokens: TokenSet) -> None:
    keyring = get_keyring()
    if keyring is None:
        raise IntegrationError(ErrorCategory.not_configured, "Secure token storage is not configured")
    cred = conn.credential or PlatformCredential(connection_id=conn.id)
    cred.encrypted_access_token = keyring.encrypt(tokens.access_token, _aad(conn, "access"))
    if tokens.refresh_token:  # rotation: keep the newest refresh token
        cred.encrypted_refresh_token = keyring.encrypt(tokens.refresh_token, _aad(conn, "refresh"))
    cred.access_token_expires_at = utcnow() + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    conn.credential = cred


def _decrypt(conn: PlatformConnection, kind: str, value: str | None) -> str | None:
    keyring = get_keyring()
    if keyring is None or value is None:
        return None
    try:
        return keyring.decrypt(value, _aad(conn, kind))
    except CryptoError:
        return None


def access_token(db: Session, conn: PlatformConnection, connector: Connector, *, force_refresh: bool = False) -> str:
    """Return a valid access token, refreshing (and rotating) when near expiry."""
    if conn.state != ConnectionState.connected or conn.credential is None:
        raise IntegrationError(ErrorCategory.not_connected, f"{connector.display_name} is not connected")
    cred = conn.credential
    token = _decrypt(conn, "access", cred.encrypted_access_token)
    expires = cred.access_token_expires_at
    expired = expires is not None and expires - REFRESH_MARGIN <= utcnow()
    if token and not expired and not force_refresh:
        return token
    refresh = _decrypt(conn, "refresh", cred.encrypted_refresh_token)
    if not refresh:
        mark_error(conn, IntegrationError(ErrorCategory.token_expired, "The authorization expired; reconnect."))
        raise IntegrationError(ErrorCategory.token_expired, "The authorization expired; reconnect the platform.")
    try:
        tokens = connector.refresh_credentials(refresh)
    except IntegrationError as err:
        if not err.retryable or err.category == ErrorCategory.token_expired:
            mark_error(
                conn,
                IntegrationError(
                    ErrorCategory.consent_revoked, "Authorization was revoked or expired; reconnect the platform."
                ),
            )
            db.flush()
            raise IntegrationError(
                ErrorCategory.consent_revoked, "Authorization was revoked or expired; reconnect."
            ) from None
        raise
    store_tokens(conn, tokens)
    if tokens.scopes:
        conn.granted_scopes = " ".join(sorted(tokens.scopes))
    db.flush()
    return tokens.access_token


def mark_error(conn: PlatformConnection, err: IntegrationError) -> None:
    conn.last_error_category = err.category.value
    conn.last_error_message = err.message[:500]
    if err.category in (ErrorCategory.consent_revoked, ErrorCategory.token_expired, ErrorCategory.invalid_credentials):
        conn.state = ConnectionState.error
    elif err.category == ErrorCategory.admin_approval_required:
        conn.state = ConnectionState.admin_approval_required
    elif err.category in (ErrorCategory.provider_unavailable, ErrorCategory.rate_limited):
        conn.state = ConnectionState.temporarily_disconnected if conn.state == ConnectionState.connected else conn.state


def mark_success(conn: PlatformConnection) -> None:
    conn.last_success_at = utcnow()
    if conn.state == ConnectionState.temporarily_disconnected:
        conn.state = ConnectionState.connected
        conn.reconnect_count += 1


def disconnect(db: Session, conn: PlatformConnection, connector: Connector) -> bool:
    """Revoke at the provider where supported (best effort), then delete tokens."""
    revoked = False
    if conn.credential is not None:
        access = _decrypt(conn, "access", conn.credential.encrypted_access_token)
        refresh = _decrypt(conn, "refresh", conn.credential.encrypted_refresh_token)
        if access:
            try:
                revoked = connector.revoke(TokenSet(access, refresh, None, set()))
            except IntegrationError:
                revoked = False
    db.delete(conn)  # cascades to platform_credentials
    db.flush()
    return revoked


def call_with_token[T](db: Session, conn: PlatformConnection, connector: Connector, fn: Callable[[str], T]) -> T:
    """Run ``fn(access_token)``; on a 401 refresh once (rotating tokens) and retry."""
    token = access_token(db, conn, connector)
    try:
        return fn(token)
    except IntegrationError as err:
        if err.category != ErrorCategory.token_expired:
            raise
    return fn(access_token(db, conn, connector, force_refresh=True))
