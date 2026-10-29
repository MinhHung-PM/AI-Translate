from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, Auth, client_ip, get_auth
from app.core.config import Settings, get_settings
from app.core.errors import AppError, Forbidden, NotAuthenticated, NotFound
from app.core.security import new_token, pkce_challenge
from app.db.base import utcnow
from app.integrations.registry import all_connectors
from app.models import OidcLoginState, Project, ProjectMembership, User
from app.models.enums import GlobalRole, ProjectRole
from app.schemas.api import DevLoginIn, DevUserOut, SessionInfo, UserOut
from app.services.audit import record_audit
from app.services.sessions import create_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,  # not readable by JavaScript
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _features() -> dict[str, bool]:
    s = get_settings()
    return {
        "remember_api_key": s.remember_key_supported,
        "secret_storage": s.secret_storage_available,
        "mock_provider": s.enable_mock_provider,
        "dev_auth": s.auth_mode == "dev",
        # No sign-in; AI keys are managed on the server (the AI settings menu is hidden).
        "shared_mode": s.auth_mode == "shared",
        "server_openai": bool(s.openai_api_key),
        "server_soniox": bool(s.soniox_api_key),
        # At least one meeting platform (Teams / Zoom / Meet) is configured on this server;
        # otherwise the integration pages and links are hidden (nothing there could work).
        "integrations": any(c.is_configured() for c in all_connectors()),
        # The transcript replay demo is for trying the product, not for production sites.
        "replay_demo": s.environment != "production",
    }


def _shared_user(db: Session) -> User:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == s.shared_user_email))
    if user is None:
        # Project managers can create projects and run every meeting workflow; not an admin.
        user = User(email=s.shared_user_email, display_name=s.shared_user_name, role=GlobalRole.project_manager)
        db.add(user)
        db.flush()
        # A ready-to-use project, so colleagues can start a live translation right away.
        if db.scalar(select(Project).where(Project.code == "CHUNG")) is None:
            project = Project(code="CHUNG", name="Dự án chung", created_by_id=user.id)
            db.add(project)
            db.flush()
            db.add(ProjectMembership(project_id=project.id, user_id=user.id, role=ProjectRole.manager))
    return user


@router.get("/me", response_model=SessionInfo)
def me(request: Request, response: Response, db: DB) -> SessionInfo:
    try:
        auth = get_auth(request, db)
        user, session = auth.user, auth.session
    except NotAuthenticated:
        if get_settings().auth_mode != "shared":
            raise
        # No sign-in on a shared team site: every browser gets a session for the shared account.
        user = _shared_user(db)
        token, session = create_session(db, user, client_ip(request), request.headers.get("user-agent"))
        db.commit()
        _set_cookie(response, token)
    return SessionInfo(
        user=UserOut.model_validate(user),
        csrf_token=session.csrf_token,
        auth_mode=get_settings().auth_mode,
        expires_at=session.expires_at,
        features=_features(),
    )


@router.post("/logout", status_code=204)
def logout(auth: Auth, db: DB, response: Response) -> Response:
    record_audit(db, actor_id=auth.user.id, action="auth.logout", resource_type="session", ip=auth.ip)
    revoke_session(db, auth.session)
    db.commit()
    response.status_code = 204
    s = get_settings()
    response.delete_cookie(
        s.session_cookie_name, path="/", secure=s.session_cookie_secure, httponly=True, samesite="lax"
    )
    return response


# ---- Development-only authentication ---------------------------------------


def _require_dev() -> None:
    settings = get_settings()
    if settings.auth_mode != "dev" or settings.is_production:
        raise NotFound("Not found")


@router.get("/dev/users", response_model=list[DevUserOut])
def dev_users(db: DB) -> list[User]:
    """Lists seeded users for the dev login picker. Disabled unless AUTH_MODE=dev."""
    _require_dev()
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.role, User.email)))


@router.post("/dev/login", response_model=SessionInfo)
def dev_login(body: DevLoginIn, request: Request, response: Response, db: DB) -> SessionInfo:
    _require_dev()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        raise NotAuthenticated("Unknown or inactive user")
    token, session = create_session(db, user, client_ip(request), request.headers.get("user-agent"))
    record_audit(
        db,
        actor_id=user.id,
        action="auth.login",
        resource_type="session",
        details={"mode": "dev"},
        ip=client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return SessionInfo(
        user=UserOut.model_validate(user),
        csrf_token=session.csrf_token,
        auth_mode="dev",
        expires_at=session.expires_at,
        features=_features(),
    )


# ---- OpenID Connect (Microsoft Entra ID or any compliant IdP) ----------------


@lru_cache
def _discovery(issuer: str) -> dict[str, Any]:
    try:
        resp = httpx.get(issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # IdP unreachable or OIDC_ISSUER misconfigured: a clear message instead of a 500.
        logger.warning("OIDC discovery failed: %s", type(exc).__name__)
        raise SignInUnavailable(
            "The sign-in service is unreachable. Try again later or contact the administrator."
        ) from None
    return data


class SignInUnavailable(AppError):
    status_code = 503
    code = "signin_unavailable"


@lru_cache
def _jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_uri)


def _require_oidc() -> None:
    s = get_settings()
    if s.auth_mode != "oidc" or not all([s.oidc_issuer, s.oidc_client_id, s.oidc_client_secret, s.oidc_redirect_uri]):
        raise NotFound("OIDC login is not configured")


@router.get("/oidc/login")
def oidc_login(db: DB) -> RedirectResponse:
    _require_oidc()
    s = get_settings()
    assert s.oidc_issuer and s.oidc_client_id and s.oidc_redirect_uri
    meta = _discovery(s.oidc_issuer)
    state, nonce, verifier = new_token(24), new_token(24), secrets.token_urlsafe(64)
    db.add(OidcLoginState(state=state, nonce=nonce, code_verifier=verifier))
    db.commit()
    params = {
        "client_id": s.oidc_client_id,
        "response_type": "code",
        "redirect_uri": s.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "response_mode": "query",
    }
    return RedirectResponse(f"{meta['authorization_endpoint']}?{urlencode(params)}", status_code=302)


def _allowed_identity(s: Settings, email: str, claims: dict[str, Any]) -> bool:
    """Only the configured company tenants / e-mail domains may sign in (none configured = allowed,
    which production refuses at startup)."""
    domains = {d.lower().lstrip("@") for d in s.oidc_allowed_email_domains}
    tenants = {t.lower() for t in s.oidc_allowed_tenant_ids}
    if not domains and not tenants:
        return True
    if tenants and str(claims.get("tid") or "").lower() in tenants:
        return True
    if domains and email.rsplit("@", 1)[-1] in domains:
        # Google accounts: also require a verified address of the hosted domain.
        if claims.get("email_verified") is False:
            return False
        hd = claims.get("hd")
        return hd is None or str(hd).lower() in domains
    return False


@router.get("/oidc/callback")
def oidc_callback(request: Request, db: DB, code: str = "", state: str = "") -> RedirectResponse:
    _require_oidc()
    s = get_settings()
    assert s.oidc_issuer and s.oidc_client_id and s.oidc_client_secret and s.oidc_redirect_uri
    login_state = db.scalar(select(OidcLoginState).where(OidcLoginState.state == state)) if state else None
    if login_state is None or not code:
        raise NotAuthenticated("Invalid or expired login state")
    expired = utcnow() - login_state.created_at > timedelta(minutes=10)
    db.delete(login_state)  # one-time use
    db.commit()
    if expired:
        raise NotAuthenticated("The sign-in took too long; please try again")
    meta = _discovery(s.oidc_issuer)
    try:
        token_resp = httpx.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": s.oidc_redirect_uri,
                "client_id": s.oidc_client_id,
                "client_secret": s.oidc_client_secret,
                "code_verifier": login_state.code_verifier,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        id_token = token_resp.json()["id_token"]
        signing_key = _jwks_client(meta["jwks_uri"]).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=s.oidc_client_id,
            issuer=meta.get("issuer", s.oidc_issuer),
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except (httpx.HTTPError, KeyError, jwt.PyJWTError) as exc:
        logger.warning("OIDC callback failed: %s", type(exc).__name__)
        raise NotAuthenticated("Sign-in failed") from None
    if claims.get("nonce") != login_state.nonce:
        raise NotAuthenticated("Sign-in failed (nonce mismatch)")
    subject = str(claims.get("oid") or claims["sub"])  # Entra 'oid' is stable across apps
    email = str(claims.get("email") or claims.get("preferred_username") or "").lower()
    if not email:
        raise AppError("The identity provider did not return an email address")
    if not _allowed_identity(s, email, claims):
        logger.warning("OIDC login refused: identity outside the allowed tenants/domains")
        raise Forbidden("This account is not allowed to use this site. Ask your administrator for access.")
    user = db.scalar(select(User).where(User.oidc_subject == subject))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and user.oidc_subject and user.oidc_subject != subject:
            raise Forbidden("This email is linked to a different identity")
        if user is None:
            # Just-in-time provisioning with least privilege; admins grant roles/projects.
            user = User(email=email, display_name=str(claims.get("name") or email), role=GlobalRole.member)
            db.add(user)
        user.oidc_subject = subject
    if not user.is_active:
        raise NotAuthenticated("Account is disabled")
    token, _ = create_session(db, user, client_ip(request), request.headers.get("user-agent"))
    record_audit(
        db,
        actor_id=user.id,
        action="auth.login",
        resource_type="session",
        details={"mode": "oidc"},
        ip=client_ip(request),
    )
    db.commit()
    response = RedirectResponse(s.oidc_post_login_redirect, status_code=302)
    _set_cookie(response, token)
    return response
