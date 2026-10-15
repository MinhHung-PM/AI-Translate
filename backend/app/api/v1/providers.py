from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.ai.base import ProviderError, TokenUsage
from app.ai.catalog import get_catalog
from app.api.deps import DB, Auth, AuthContext, ai_rate_limit
from app.core.config import get_settings
from app.core.errors import NotFound, ProviderNotConfigured
from app.db.base import utcnow
from app.models import AIProviderConfiguration
from app.schemas.api import (
    ConnectionTestOut,
    ProviderCatalogOut,
    ProviderConfigIn,
    ProviderConfigOut,
    ProviderSettingsOut,
)
from app.services import provider_config as svc
from app.services.audit import record_audit
from app.services.usage import DbUsageMeter, UsageContext

router = APIRouter(prefix="/providers", tags=["ai-providers"])
TestAuth = Annotated[AuthContext, Depends(ai_rate_limit("provider-test"))]


def _out(db: DB, auth: AuthContext, config: AIProviderConfiguration) -> ProviderConfigOut:
    info = get_catalog().get(config.provider)
    out = ProviderConfigOut.model_validate(config)
    out.has_usable_key = bool(info and not info.requires_api_key) or svc.session_has_key(db, config, auth.session.id)
    return out


def _own_config(db: DB, auth: AuthContext, config_id: uuid.UUID) -> AIProviderConfiguration:
    config = db.get(AIProviderConfiguration, config_id)
    if config is None or config.user_id != auth.user.id:
        raise NotFound("Provider configuration not found")
    return config


@router.get("", response_model=ProviderSettingsOut)
def catalog(auth: Auth) -> ProviderSettingsOut:
    settings = get_settings()
    return ProviderSettingsOut(
        providers=[ProviderCatalogOut.model_validate(p, from_attributes=True) for p in get_catalog().providers],
        secret_storage_available=settings.secret_storage_available,
        remember_key_supported=settings.remember_key_supported,
    )


@router.get("/configs", response_model=list[ProviderConfigOut])
def list_configs(auth: Auth, db: DB) -> list[ProviderConfigOut]:
    return [_out(db, auth, c) for c in svc.list_configs(db, auth.user)]


@router.put("/configs", response_model=ProviderConfigOut)
def save_config(body: ProviderConfigIn, auth: Auth, db: DB) -> ProviderConfigOut:
    config = svc.upsert_config(
        db,
        auth.user,
        auth.session,
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
        remember=body.remember,
        make_default=body.make_default,
    )
    record_audit(
        db,
        actor_id=auth.user.id,
        action="provider.config_save",
        resource_type="ai_provider_configuration",
        resource_id=config.id,
        details={
            "provider": config.provider,
            "model": config.model,
            "key_supplied": body.api_key is not None,
            "key_storage": config.key_storage.value,
        },
        ip=auth.ip,
    )
    db.commit()
    return _out(db, auth, config)


@router.post("/configs/{config_id}/default", response_model=ProviderConfigOut)
def make_default(config_id: uuid.UUID, auth: Auth, db: DB) -> ProviderConfigOut:
    config = _own_config(db, auth, config_id)
    for other in db.scalars(select(AIProviderConfiguration).where(AIProviderConfiguration.user_id == auth.user.id)):
        other.is_default = other.id == config.id
    db.commit()
    return _out(db, auth, config)


@router.delete("/configs/{config_id}/key", response_model=ProviderConfigOut)
def remove_key(config_id: uuid.UUID, auth: Auth, db: DB) -> ProviderConfigOut:
    config = _own_config(db, auth, config_id)
    svc.remove_key(db, config)
    record_audit(
        db,
        actor_id=auth.user.id,
        action="provider.key_remove",
        resource_type="ai_provider_configuration",
        resource_id=config.id,
        details={"provider": config.provider},
        ip=auth.ip,
    )
    db.commit()
    return _out(db, auth, config)


@router.delete("/configs/{config_id}", status_code=204)
def delete_config(config_id: uuid.UUID, auth: Auth, db: DB) -> None:
    config = _own_config(db, auth, config_id)
    db.delete(config)  # cascades to session secrets
    record_audit(
        db,
        actor_id=auth.user.id,
        action="provider.config_delete",
        resource_type="ai_provider_configuration",
        resource_id=config_id,
        details={"provider": config.provider},
        ip=auth.ip,
    )
    db.commit()


@router.post("/configs/{config_id}/test", response_model=ConnectionTestOut)
def test_connection(config_id: uuid.UUID, auth: TestAuth, db: DB) -> ConnectionTestOut:
    config = _own_config(db, auth, config_id)
    try:
        resolved = svc.resolve_provider(db, auth.user.id, auth.session.id, config.id)
    except ProviderNotConfigured as exc:
        return ConnectionTestOut(ok=False, message=exc.message)
    started = time.monotonic()
    if resolved.info.adapter == "mock":
        result = ConnectionTestOut(
            ok=True,
            message="Mock provider is available (no external calls are made)",
            models=[m.id for m in resolved.info.models],
        )
    else:
        try:
            raw = svc.build_ai_provider(resolved.info).test_connection(resolved.credentials, resolved.model)
            result = ConnectionTestOut(ok=raw.ok, message=raw.message, models=raw.models)
        except ProviderError as err:
            result = ConnectionTestOut(ok=False, message=err.message)
        DbUsageMeter(db).record(
            UsageContext(auth.user.id, None, None, None, resolved.info.key, resolved.model, resolved.key_source),
            "connection_test",
            TokenUsage(),
            duration_ms=int((time.monotonic() - started) * 1000),
            success=result.ok,
        )
    config.last_test_ok = result.ok
    config.last_test_message = result.message[:300]
    config.last_tested_at = utcnow()
    db.commit()
    return result
