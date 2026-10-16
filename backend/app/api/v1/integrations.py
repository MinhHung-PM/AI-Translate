"""Meeting-platform integration endpoints (Workstream 2)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, Auth, AuthContext, ai_rate_limit, client_ip
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, PayloadTooLarge
from app.core.rate_limit import rate_limiter
from app.db.session import get_db
from app.integrations import oauth
from app.integrations.capabilities import Capability, CapabilityStatus
from app.integrations.errors import ErrorCategory, IntegrationError
from app.integrations.orchestration import connection_manager as live_svc
from app.integrations.orchestration import external_source_service as source_svc
from app.integrations.orchestration.connection_service import ConnectionView, view
from app.integrations.registry import all_connectors, get_connector
from app.integrations.zoom import webhook as zoom_webhook
from app.models import ExternalMeetingReference, Job, LiveSession, ProviderEvent
from app.models.enums import GlobalRole, JobKind, JobStatus, PlatformProvider
from app.schemas.api import JobOut, LiveSessionOut
from app.services import jobs as job_service
from app.services.audit import record_audit
from app.services.authz import AccessLevel, accessible_project_ids, load_meeting, require_edit_meeting

router = APIRouter(tags=["integrations"])
IntegrationAuth = Annotated[AuthContext, Depends(ai_rate_limit("integration"))]


class ConnectOut(BaseModel):
    authorization_url: str


class TestOut(BaseModel):
    ok: bool
    message: str
    connection: ConnectionView


class AvailableMeetingOut(BaseModel):
    provider_meeting_id: str
    title: str
    start: datetime | None
    end: datetime | None
    join_url: str | None
    has_transcript: bool | None


class LinkIn(BaseModel):
    provider: PlatformProvider
    reference: str = Field(min_length=3, max_length=2048)


class ExternalSourceOut(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    provider: PlatformProvider
    provider_meeting_id: str
    join_url: str | None
    transcript_status: str
    status_message: str | None
    fetch_attempts: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    live_requested: bool
    sandbox: bool
    capabilities: list[dict[str, Any]]
    connection_status: str
    live_session: LiveSessionOut | None


class ProviderEventOut(BaseModel):
    provider: str
    event_type: str
    status: str
    detail: str | None
    meeting_id: uuid.UUID | None
    received_at: datetime


class DiagnosticsOut(BaseModel):
    connection: ConnectionView
    recent_events: list[ProviderEventOut]
    recent_jobs: list[JobOut]


def _http_status(cat: ErrorCategory) -> int:
    return {
        ErrorCategory.not_configured: 409,
        ErrorCategory.not_connected: 409,
        ErrorCategory.admin_approval_required: 403,
        ErrorCategory.insufficient_scope: 403,
        ErrorCategory.no_meeting_access: 403,
        ErrorCategory.consent_revoked: 409,
        ErrorCategory.token_expired: 409,
        ErrorCategory.invalid_credentials: 409,
        ErrorCategory.meeting_not_found: 404,
        ErrorCategory.invalid_request: 422,
        ErrorCategory.rate_limited: 429,
        ErrorCategory.invalid_signature: 401,
        ErrorCategory.unsupported: 409,
        ErrorCategory.unsupported_account: 409,
    }.get(cat, 502)


def integration_error_response(err: IntegrationError) -> JSONResponse:
    details: dict[str, Any] = {"category": err.category.value}
    if err.provider_code:
        details["provider_code"] = err.provider_code
    if err.retry_after is not None:
        details["retry_after_seconds"] = int(err.retry_after)
    return JSONResponse(
        status_code=_http_status(err.category),
        content={"error": {"code": f"integration_{err.category.value}", "message": err.message, "details": details}},
    )


# ---- platform connections -----------------------------------------------------


@router.get("/integrations", response_model=list[ConnectionView])
def list_integrations(auth: Auth, db: DB) -> list[ConnectionView]:
    return [view(db, auth.user, c) for c in all_connectors()]


@router.get("/integrations/{provider}", response_model=ConnectionView)
def get_integration(provider: str, auth: Auth, db: DB) -> ConnectionView:
    return view(db, auth.user, get_connector(provider))


@router.post("/integrations/{provider}/connect", response_model=ConnectOut)
def connect(provider: str, auth: Auth, db: DB) -> ConnectOut:
    connector = get_connector(provider)
    url = oauth.begin(db, auth.user, auth.session, connector)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.connect_start",
        resource_type="platform_connection",
        details={"provider": provider},
        ip=auth.ip,
    )
    db.commit()
    return ConnectOut(authorization_url=url)


@router.get("/integrations/{provider}/oauth/callback", include_in_schema=True)
def oauth_callback(
    provider: str,
    auth: Auth,
    db: DB,
    code: str = "",
    state: str = "",
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Provider redirect target. Requires the same logged-in session that started the
    flow; redirects only to a fixed in-app path (no open redirect)."""
    connector = get_connector(provider)
    target = f"/integrations?provider={connector.provider.value}"
    try:
        oauth.complete(
            db,
            auth.user,
            auth.session,
            connector,
            code=code[:2048],
            state=state[:256],
            error=error,
            error_description=error_description,
        )
        record_audit(
            db,
            actor_id=auth.user.id,
            action="integration.connected",
            resource_type="platform_connection",
            details={"provider": provider},
            ip=auth.ip,
        )
        db.commit()
        return RedirectResponse(f"{target}&result=connected", status_code=302)
    except IntegrationError as err:
        record_audit(
            db,
            actor_id=auth.user.id,
            action="integration.connect_failed",
            resource_type="platform_connection",
            details={"provider": provider, "category": err.category.value},
            ip=auth.ip,
        )
        db.commit()
        return RedirectResponse(f"{target}&result=error&category={err.category.value}", status_code=302)


@router.post("/integrations/{provider}/test", response_model=TestOut)
def test_connection(provider: str, auth: IntegrationAuth, db: DB) -> TestOut:
    connector = get_connector(provider)
    conn = oauth.get_connection(db, auth.user, connector)
    if conn is None:
        raise Conflict("Not connected")
    try:
        result = oauth.call_with_token(db, conn, connector, lambda t: connector.health_check(t, conn.scopes()))
        oauth.mark_success(conn)
        ok, message = result.ok, result.message
    except IntegrationError as err:
        oauth.mark_error(conn, err)
        ok, message = False, err.message
    db.commit()
    return TestOut(ok=ok, message=message, connection=view(db, auth.user, connector))


@router.delete("/integrations/{provider}", response_model=ConnectionView)
def disconnect(provider: str, auth: Auth, db: DB) -> ConnectionView:
    connector = get_connector(provider)
    conn = oauth.get_connection(db, auth.user, connector)
    if conn is None:
        raise NotFound("Not connected")
    revoked = oauth.disconnect(db, conn, connector)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.disconnected",
        resource_type="platform_connection",
        details={"provider": provider, "revoked_at_provider": revoked},
        ip=auth.ip,
    )
    db.commit()
    return view(db, auth.user, connector)


@router.get("/integrations/{provider}/meetings", response_model=list[AvailableMeetingOut])
def list_platform_meetings(provider: str, auth: IntegrationAuth, db: DB) -> list[AvailableMeetingOut]:
    connector = get_connector(provider)
    conn = source_svc.connected_connection(db, auth.user.id, provider)
    try:
        meetings = oauth.call_with_token(db, conn, connector, connector.list_available_meetings)
        oauth.mark_success(conn)
    except IntegrationError as err:
        oauth.mark_error(conn, err)
        db.commit()
        raise
    db.commit()
    return [AvailableMeetingOut(**m.__dict__) for m in meetings]


@router.get("/integrations/{provider}/diagnostics", response_model=DiagnosticsOut)
def diagnostics(provider: str, auth: Auth, db: DB) -> DiagnosticsOut:
    """Safe diagnostics: categories and timestamps only — no tokens, secrets or transcript text."""
    connector = get_connector(provider)
    visible = accessible_project_ids(auth.user, AccessLevel.summary)
    from app.models import Meeting

    q = select(ProviderEvent).where(ProviderEvent.provider == connector.provider)
    if auth.user.role != GlobalRole.admin:
        q = q.where(ProviderEvent.meeting_id.in_(select(Meeting.id).where(Meeting.project_id.in_(visible))))
    events = db.scalars(q.order_by(ProviderEvent.received_at.desc()).limit(20))
    jobs = db.scalars(
        select(Job)
        .where(Job.user_id == auth.user.id, Job.kind.in_([JobKind.fetch_transcript, JobKind.realtime_ingest]))
        .order_by(Job.created_at.desc())
        .limit(10)
    )
    return DiagnosticsOut(
        connection=view(db, auth.user, connector),
        recent_events=[
            ProviderEventOut(
                provider=e.provider.value,
                event_type=e.event_type,
                status=e.status.value,
                detail=e.detail,
                meeting_id=e.meeting_id,
                received_at=e.received_at,
            )
            for e in events
        ],
        recent_jobs=[JobOut.model_validate(j) for j in jobs],
    )


# ---- meeting sources ------------------------------------------------------------


def _source_out(db: Session, auth: AuthContext, ref: ExternalMeetingReference) -> ExternalSourceOut:
    connector = get_connector(ref.provider.value)
    v = view(db, auth.user, connector)
    live = db.scalar(
        select(LiveSession)
        .where(LiveSession.meeting_id == ref.meeting_id, LiveSession.is_demo.is_(False))
        .order_by(LiveSession.started_at.desc())
        .limit(1)
    )
    return ExternalSourceOut(
        id=ref.id,
        meeting_id=ref.meeting_id,
        provider=ref.provider,
        provider_meeting_id=ref.provider_meeting_id,
        join_url=ref.join_url,
        transcript_status=ref.transcript_status.value,
        status_message=ref.status_message,
        fetch_attempts=ref.fetch_attempts,
        last_checked_at=ref.last_checked_at,
        next_check_at=ref.next_check_at,
        live_requested=ref.live_requested,
        sandbox=connector.is_sandbox(),
        capabilities=[c.model_dump() for c in v.capabilities],
        connection_status=v.status.value,
        live_session=LiveSessionOut.model_validate(live) if live else None,
    )


@router.get("/meetings/{meeting_id}/external-source", response_model=ExternalSourceOut | None)
def get_source(meeting_id: uuid.UUID, auth: Auth, db: DB) -> ExternalSourceOut | None:
    meeting, _ = load_meeting(db, auth.user, meeting_id, AccessLevel.summary)
    ref = source_svc.get_ref(db, meeting.id)
    return _source_out(db, auth, ref) if ref else None


@router.post("/meetings/{meeting_id}/external-source", response_model=ExternalSourceOut, status_code=201)
def link_source(meeting_id: uuid.UUID, body: LinkIn, auth: IntegrationAuth, db: DB) -> ExternalSourceOut:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    try:
        ref = source_svc.link(db, meeting, auth.user, body.provider.value, body.reference)
    except IntegrationError:
        db.commit()  # keep connection diagnostics
        raise
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.source_linked",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"provider": body.provider.value},
        ip=auth.ip,
    )
    db.commit()
    return _source_out(db, auth, ref)


@router.delete("/meetings/{meeting_id}/external-source", status_code=204)
def unlink_source(meeting_id: uuid.UUID, auth: Auth, db: DB) -> None:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    ref = source_svc.get_ref(db, meeting.id)
    if ref is None:
        raise NotFound("No linked source")
    live_svc.stop_live(db, meeting)
    source_svc.unlink(db, ref)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.source_unlinked",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        ip=auth.ip,
    )
    db.commit()


def _require_capability(ref: ExternalMeetingReference, db: Session, auth: AuthContext, capability: Capability) -> None:
    v = view(db, auth.user, get_connector(ref.provider.value))
    state = next(c for c in v.capabilities if c.capability == capability)
    if state.status != CapabilityStatus.available:
        raise IntegrationError(
            ErrorCategory.admin_approval_required
            if state.status == CapabilityStatus.requires_admin_approval
            else ErrorCategory.unsupported
            if state.status == CapabilityStatus.not_supported
            else ErrorCategory.not_configured,
            state.message,
        )


@router.post("/meetings/{meeting_id}/external-source/fetch", response_model=JobOut, status_code=202)
def fetch_transcript(meeting_id: uuid.UUID, auth: IntegrationAuth, db: DB) -> Job:
    """Retrieve (or retry retrieving) the post-meeting transcript in the background."""
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    ref = source_svc.get_ref(db, meeting.id)
    if ref is None:
        raise NotFound("No linked source")
    _require_capability(ref, db, auth, Capability.post_meeting_transcript)
    active = job_service.find_active_job(db, JobKind.fetch_transcript, meeting.id)
    if active is not None:
        # A scheduled retry exists: run it now instead of queueing a duplicate.
        active.run_after = None
        db.commit()
        return active
    job = source_svc.enqueue_fetch(db, ref, meeting, auth.user.id, auth.session.id)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.fetch",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"provider": ref.provider.value},
        ip=auth.ip,
    )
    db.commit()
    return job


@router.post("/meetings/{meeting_id}/external-source/live/start", response_model=LiveSessionOut, status_code=202)
def start_live(meeting_id: uuid.UUID, auth: IntegrationAuth, db: DB) -> LiveSession:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    ref = source_svc.get_ref(db, meeting.id)
    if ref is None:
        raise NotFound("No linked source")
    _require_capability(ref, db, auth, Capability.live_transcript)
    live = live_svc.arm_live(db, meeting, ref, auth.user, auth.session)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="integration.live_armed",
        resource_type="meeting",
        resource_id=meeting.id,
        project_id=meeting.project_id,
        details={"provider": ref.provider.value},
        ip=auth.ip,
    )
    db.commit()
    return live


@router.post("/meetings/{meeting_id}/external-source/live/stop", status_code=200)
def stop_live(meeting_id: uuid.UUID, auth: Auth, db: DB) -> dict[str, int]:
    meeting, access = load_meeting(db, auth.user, meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    count = live_svc.stop_live(db, meeting)
    db.commit()
    return {"stopped": count}


@router.post("/jobs/{job_id}/retry", response_model=JobOut, status_code=202)
def retry_job(job_id: uuid.UUID, auth: Auth, db: DB) -> Job:
    """Manual retry of a failed ingestion/translation job (dead-letter recovery)."""
    job = db.get(Job, job_id)
    if job is None or job.meeting_id is None:
        raise NotFound("Job not found")
    meeting, access = load_meeting(db, auth.user, job.meeting_id, AccessLevel.contribute)
    require_edit_meeting(access, meeting, auth.user)
    if job.status != JobStatus.failed or job.kind not in (JobKind.fetch_transcript, JobKind.translation):
        raise Conflict("Only failed retrieval or translation jobs can be retried")
    params = dict(job.params)
    params.pop("rescheduled", None)
    if job.kind == JobKind.fetch_transcript:
        ref = source_svc.get_ref(db, meeting.id)
        if ref is None:
            raise NotFound("No linked source")
        ref.fetch_attempts = 0
    new = job_service.enqueue(
        db,
        kind=job.kind,
        user_id=auth.user.id,
        session_id=auth.session.id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        params=params,
    )
    db.commit()
    return new


# ---- provider webhooks -----------------------------------------------------------------


@router.post("/integrations/zoom/webhook", include_in_schema=True)
async def zoom_webhook_endpoint(request: Request, db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    """Unauthenticated by design; authenticity is proven by Zoom's HMAC signature,
    timestamp freshness and single-use event keys."""
    settings = get_settings()
    ip = client_ip(request) or "unknown"
    rate_limiter.check(f"webhook:zoom:{ip}", 600)
    limit = settings.integration_webhook_max_bytes
    if int(request.headers.get("content-length") or 0) > limit:
        raise PayloadTooLarge("Webhook body too large")
    raw = await request.body()
    if len(raw) > limit:
        raise PayloadTooLarge("Webhook body too large")
    try:
        zoom_webhook.verify_signature(
            raw, request.headers.get("x-zm-request-timestamp"), request.headers.get("x-zm-signature")
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
    except IntegrationError as err:
        return integration_error_response(err)
    except ValueError:
        return integration_error_response(IntegrationError(ErrorCategory.invalid_request, "Invalid JSON"))
    if payload.get("event") == "endpoint.url_validation":
        return JSONResponse(zoom_webhook.url_validation_response(payload))
    ev = live_svc.record_provider_event(
        db, PlatformProvider.zoom, zoom_webhook.dedup_key(payload), str(payload.get("event", ""))
    )
    if ev is None:
        return JSONResponse({"status": "duplicate"})  # replayed delivery: acknowledged, not reprocessed
    try:
        detail = live_svc.dispatch_zoom_event(db, payload, ev)
    except AppError:
        db.rollback()
        raise
    db.commit()
    return JSONResponse({"status": ev.status.value, "detail": detail})
