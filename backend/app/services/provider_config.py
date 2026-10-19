"""User AI provider configuration and API-key handling.

Key handling rules (see docs/security.md):

* A plaintext key is accepted only in a request body, used, encrypted and
  dropped. It is never returned by any endpoint, logged, or put in a URL.
* ``remember=false`` (default): the key is encrypted into ``session_secrets``
  bound to the current login session; logout or expiry deletes it.
* ``remember=true``: allowed only when ``remember_key_supported`` (keyring
  configured and persistent storage enabled); encrypted with AES-256-GCM,
  associated data binds the ciphertext to the configuration row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.base import (
    Credentials,
    MemoGenerationProvider,
    ModelParams,
    ProviderError,
    ProviderErrorCode,
    TranslationProvider,
)
from app.ai.catalog import ProviderInfo, get_catalog
from app.ai.llm import LLMMemoGenerator, LLMTranslationProvider
from app.ai.mock import MockProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.url_safety import validate_provider_base_url
from app.core.config import get_settings
from app.core.crypto import CryptoError, KeyRing
from app.core.errors import Conflict, NotFound, ProviderNotConfigured, ValidationFailed
from app.core.security import key_hint
from app.db.base import utcnow
from app.models import AIProviderConfiguration, SessionSecret, User, UserSession
from app.models.enums import KeyStorage


@lru_cache
def get_keyring() -> KeyRing | None:
    spec = get_settings().secret_encryption_keys
    return KeyRing.parse(spec) if spec.strip() else None


def _aad(config: AIProviderConfiguration, session_id: uuid.UUID | None = None) -> str:
    base = f"provider-config:{config.id}:{config.user_id}"
    return f"{base}:session:{session_id}" if session_id else base


def provider_info_or_404(key: str) -> ProviderInfo:
    info = get_catalog().get(key)
    if info is None:
        raise NotFound("Unknown AI provider")
    return info


def list_configs(db: Session, user: User) -> list[AIProviderConfiguration]:
    return list(
        db.scalars(
            select(AIProviderConfiguration)
            .where(AIProviderConfiguration.user_id == user.id)
            .order_by(AIProviderConfiguration.created_at)
        )
    )


def session_has_key(db: Session, config: AIProviderConfiguration, session_id: uuid.UUID | None) -> bool:
    if config.key_storage == KeyStorage.persistent:
        return config.encrypted_api_key is not None
    if config.key_storage == KeyStorage.session and session_id is not None:
        return (
            db.scalar(
                select(SessionSecret.id).where(
                    SessionSecret.session_id == session_id, SessionSecret.provider_config_id == config.id
                )
            )
            is not None
        )
    return False


def _validate_model_and_url(info: ProviderInfo, model: str, base_url: str | None) -> str | None:
    if not info.allow_custom_model and info.model_info(model) is None:
        raise ValidationFailed("Model is not available for this provider")
    if not model.strip() or len(model) > 128:
        raise ValidationFailed("Model is required")
    if base_url:
        if not info.allow_custom_base_url:
            raise ValidationFailed("This provider does not accept a custom base URL")
        settings = get_settings()
        try:
            return validate_provider_base_url(
                base_url,
                allow_private=settings.allow_private_provider_urls,
                allowlist=settings.provider_base_url_allowlist,
            )
        except ProviderError as err:
            raise ValidationFailed(err.message) from None
    if info.allow_custom_base_url and not info.default_base_url:
        raise ValidationFailed("A base URL is required for this provider")
    return None


def upsert_config(
    db: Session,
    user: User,
    session: UserSession,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    remember: bool,
    make_default: bool,
) -> AIProviderConfiguration:
    info = provider_info_or_404(provider)
    clean_url = _validate_model_and_url(info, model, base_url)
    config = db.scalar(
        select(AIProviderConfiguration).where(
            AIProviderConfiguration.user_id == user.id, AIProviderConfiguration.provider == provider
        )
    )
    if config is None:
        config = AIProviderConfiguration(id=uuid.uuid4(), user_id=user.id, provider=provider, model=model)
        db.add(config)
    config.model = model
    config.base_url = clean_url

    if api_key is not None:
        api_key = api_key.strip()
        if not info.requires_api_key:
            raise ValidationFailed("This provider does not use an API key")
        if len(api_key) < 8 or len(api_key) > 512 or any(c.isspace() for c in api_key):
            raise ValidationFailed("API key format is invalid")
        store_key(db, config, session, api_key, remember)

    if is_speech_only(info):
        # Speech-recognition-only providers (Soniox) can never translate or write memos.
        if make_default:
            raise ValidationFailed("This provider is used only for speech recognition and cannot be the default")
    elif make_default or not db.scalar(
        select(AIProviderConfiguration.id).where(
            AIProviderConfiguration.user_id == user.id,
            AIProviderConfiguration.is_default.is_(True),
            AIProviderConfiguration.id != config.id,
        )
    ):
        db.execute(
            update(AIProviderConfiguration)
            .where(AIProviderConfiguration.user_id == user.id, AIProviderConfiguration.id != config.id)
            .values(is_default=False)
        )
        config.is_default = True
    db.flush()
    return config


def store_key(db: Session, config: AIProviderConfiguration, session: UserSession, api_key: str, remember: bool) -> None:
    settings = get_settings()
    keyring = get_keyring()
    if keyring is None:
        raise Conflict(
            "Secure key storage is not configured on this server (SECRET_ENCRYPTION_KEYS); API keys cannot be accepted"
        )
    if remember and not settings.remember_key_supported:
        raise Conflict("Remembering API keys is disabled on this server")
    _clear_key_material(db, config)
    if remember:
        config.encrypted_api_key = keyring.encrypt(api_key, _aad(config))
        config.key_storage = KeyStorage.persistent
    else:
        db.flush()
        db.add(
            SessionSecret(
                session_id=session.id,
                provider_config_id=config.id,
                encrypted_api_key=keyring.encrypt(api_key, _aad(config, session.id)),
            )
        )
        config.key_storage = KeyStorage.session
    config.key_hint = key_hint(api_key)
    config.key_updated_at = utcnow()
    config.last_test_ok = None


def _clear_key_material(db: Session, config: AIProviderConfiguration) -> None:
    config.encrypted_api_key = None
    for secret in db.scalars(select(SessionSecret).where(SessionSecret.provider_config_id == config.id)):
        db.delete(secret)


def remove_key(db: Session, config: AIProviderConfiguration) -> None:
    _clear_key_material(db, config)
    config.key_storage = KeyStorage.none
    config.key_hint = None
    config.key_updated_at = utcnow()
    config.last_test_ok = None


@dataclass(frozen=True)
class ResolvedProvider:
    info: ProviderInfo
    config: AIProviderConfiguration | None
    model: str
    credentials: Credentials
    key_source: str  # "byok" or "none"


def resolve_provider(
    db: Session, user_id: uuid.UUID, session_id: uuid.UUID | None, config_id: uuid.UUID | None = None
) -> ResolvedProvider:
    """Find the user's provider (explicit or default) and decrypt its key. In "shared" mode
    everyone uses the server key; otherwise the server key is the fallback."""
    if get_settings().auth_mode == "shared":
        server = server_provider()
        if server is None:
            raise ProviderNotConfigured("The site administrator has not configured the OpenAI key (OPENAI_API_KEY).")
        return server
    q = select(AIProviderConfiguration).where(AIProviderConfiguration.user_id == user_id)
    q = (
        q.where(AIProviderConfiguration.id == config_id)
        if config_id
        else q.where(AIProviderConfiguration.is_default.is_(True))
    )
    config = db.scalar(q)
    if config is None:
        server = None if config_id else server_provider()
        if server is not None:
            return server
        raise ProviderNotConfigured("No AI provider is configured. Open Settings to choose a provider.")
    info = get_catalog().get(config.provider)
    if info is None:
        raise ProviderNotConfigured("The configured AI provider is no longer available")
    api_key: str | None = None
    if info.requires_api_key:
        api_key = _decrypt_key(db, config, session_id)
        if api_key is None:
            raise ProviderNotConfigured(
                "The API key for this provider is not available in this session. Enter it again in Settings."
            )
    creds = Credentials(api_key=api_key, base_url=config.base_url or info.default_base_url)
    return ResolvedProvider(
        info=info, config=config, model=config.model, credentials=creds, key_source="byok" if api_key else "none"
    )


def server_provider() -> ResolvedProvider | None:
    """OpenAI with the server-wide key (OPENAI_API_KEY), if configured."""
    s = get_settings()
    info = get_catalog().get("openai")
    if not s.openai_api_key or info is None:
        return None
    return ResolvedProvider(
        info=info,
        config=None,
        model=s.server_ai_model,
        credentials=Credentials(api_key=s.openai_api_key, base_url=info.default_base_url),
        key_source="server",
    )


def _decrypt_key(db: Session, config: AIProviderConfiguration, session_id: uuid.UUID | None) -> str | None:
    keyring = get_keyring()
    if keyring is None:
        return None
    try:
        if config.key_storage == KeyStorage.persistent and config.encrypted_api_key:
            return keyring.decrypt(config.encrypted_api_key, _aad(config))
        if config.key_storage == KeyStorage.session and session_id is not None:
            secret = db.scalar(
                select(SessionSecret).where(
                    SessionSecret.session_id == session_id, SessionSecret.provider_config_id == config.id
                )
            )
            if secret is not None:
                return keyring.decrypt(secret.encrypted_api_key, _aad(config, session_id))
    except CryptoError:
        return None
    return None


def rotate_persistent_keys(db: Session) -> int:
    """Re-encrypt persistent and session secrets with the primary key."""
    keyring = get_keyring()
    if keyring is None:
        raise RuntimeError("SECRET_ENCRYPTION_KEYS is not configured")
    count = 0
    for config in db.scalars(
        select(AIProviderConfiguration).where(AIProviderConfiguration.encrypted_api_key.is_not(None))
    ):
        assert config.encrypted_api_key is not None
        if keyring.needs_rotation(config.encrypted_api_key):
            plain = keyring.decrypt(config.encrypted_api_key, _aad(config))
            config.encrypted_api_key = keyring.encrypt(plain, _aad(config))
            count += 1
    for secret in db.scalars(select(SessionSecret)):
        if keyring.needs_rotation(secret.encrypted_api_key):
            cfg = db.get(AIProviderConfiguration, secret.provider_config_id)
            assert cfg is not None
            aad = _aad(cfg, secret.session_id)
            secret.encrypted_api_key = keyring.encrypt(keyring.decrypt(secret.encrypted_api_key, aad), aad)
            count += 1
    return count


# ---- Provider factory --------------------------------------------------------

_mock = MockProvider()


def is_speech_only(info: ProviderInfo) -> bool:
    return "translation" not in info.capabilities and "memo_generation" not in info.capabilities


def build_ai_provider(info: ProviderInfo) -> OpenAIProvider:
    if info.adapter == "openai":
        return OpenAIProvider(info.key, info.default_base_url, get_settings().ai_request_timeout_seconds)
    raise ProviderError(ProviderErrorCode.unsupported, f"No adapter for provider {info.key}")


def translation_provider(resolved: ResolvedProvider, params: ModelParams) -> TranslationProvider:
    if resolved.info.adapter == "mock":
        return _mock
    return LLMTranslationProvider(
        build_ai_provider(resolved.info),
        resolved.credentials,
        resolved.model,
        params,
        get_settings().ai_output_max_attempts,
    )


def memo_provider(resolved: ResolvedProvider, params: ModelParams) -> MemoGenerationProvider:
    if resolved.info.adapter == "mock":
        return _mock
    return LLMMemoGenerator(build_ai_provider(resolved.info), resolved.credentials, resolved.model, params)
