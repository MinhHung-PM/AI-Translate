"""Application configuration, loaded from environment variables only.

No secret has a usable default: production startup fails fast if required
values are missing (see ``Settings.validate_for_environment``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "AI Meeting Translator & Memo Hub"

    database_url: str = "postgresql+psycopg://memohub:memohub@localhost:5432/memohub"

    # --- Authentication -------------------------------------------------
    # "dev" lets a developer pick a seeded user without a password. It is
    # refused at startup when environment == "production".
    auth_mode: Literal["dev", "oidc"] = "oidc"
    session_ttl_minutes: int = 8 * 60
    session_cookie_name: str = "memohub_session"
    session_cookie_secure: bool = True
    oidc_issuer: str | None = None  # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None  # e.g. https://memohub.example.com/api/v1/auth/oidc/callback
    oidc_post_login_redirect: str = "/"
    oidc_default_role: Literal["member"] = "member"

    # --- Secret storage -------------------------------------------------
    # Keyring for AES-256-GCM encryption of user API keys.
    # Format: "kid1:<base64 32 bytes>,kid0:<base64 32 bytes>" — the first key
    # encrypts, all keys decrypt (supports rotation). Empty => the
    # "remember API key" option is disabled.
    secret_encryption_keys: str = ""
    # Operators may disable persistent ("remember") storage even with a keyring.
    allow_persistent_api_keys: bool = True
    # SSRF guard for custom provider base URLs (see app/ai/url_safety.py).
    allow_private_provider_urls: bool = False
    provider_base_url_allowlist: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Web ------------------------------------------------------------
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # --- Uploads / processing --------------------------------------------
    max_upload_bytes: int = 2 * 1024 * 1024
    max_transcript_entries: int = 5000
    max_entry_chars: int = 4000
    translation_chunk_max_entries: int = 20
    translation_chunk_max_chars: int = 6000
    memo_max_transcript_chars: int = 120_000
    ai_output_max_attempts: int = 3

    # --- Rate limiting (per user, per process) ---------------------------
    ai_rate_limit_per_minute: int = 20

    # --- Jobs ------------------------------------------------------------
    embedded_worker: bool = False
    worker_poll_seconds: float = 1.0
    job_max_attempts: int = 2

    # --- AI provider catalog ---------------------------------------------
    provider_catalog_path: Path = BACKEND_ROOT / "app" / "ai" / "catalog.json"
    enable_mock_provider: bool = True
    ai_request_timeout_seconds: float = 60.0

    # --- Retention -------------------------------------------------------
    default_retention_days: int = 365

    log_level: str = "INFO"

    # --- Live audio capture (speech-to-text + speaker diarization) ---------
    stt_model: str = "gpt-4o-transcribe-diarize"  # speaker separation (meeting audio)
    stt_text_model: str = "gpt-transcribe"  # single speaker: supports languages[] + keywords[]
    stt_text_fallback_model: str = "gpt-4o-transcribe"
    # Streaming captions (OpenAI Realtime transcription over WebRTC).
    stt_realtime_model: str = "gpt-live-transcribe"  # VAD-based ("accurate" latency mode)
    stt_realtime_streaming_model: str = "gpt-realtime-whisper"  # words while speaking ("fast"/"balanced")
    stt_realtime_fallback_model: str = "gpt-4o-transcribe"
    stt_realtime_token_ttl_seconds: int = 600
    # Live interpretation (OpenAI translates speech directly; words stream in the target language).
    stt_interpret_model: str = "gpt-realtime-translate"
    stt_interpret_input_transcription_model: str = "gpt-realtime-whisper"  # source-language captions
    # Chunks quieter than this RMS (0..1) are not sent: near-silence makes STT models hallucinate.
    audio_min_rms: float = 0.004
    stt_timeout_seconds: float = 60.0
    audio_chunk_max_seconds: float = 30.0
    audio_chunk_max_bytes: int = 2_000_000
    audio_max_sources: int = 4
    audio_rate_limit_per_minute: int = 120
    audio_session_idle_minutes: int = 30

    # --- Workstream 2: meeting-platform integrations ----------------------
    # Platform app credentials are operator-level settings (an app registered
    # by IT in Entra ID / Zoom Marketplace / Google Cloud). They are NOT user
    # AI keys and are never stored with AI provider configuration.
    # Public origin users reach the app on; OAuth redirect URIs are derived as
    # {PUBLIC_BASE_URL}/api/v1/integrations/{provider}/oauth/callback and must be
    # registered exactly in each provider console.
    public_base_url: str = "http://localhost:3000"
    integration_oauth_state_ttl_minutes: int = 10
    integration_webhook_max_bytes: int = 64 * 1024
    integration_webhook_tolerance_seconds: int = 300
    integration_fetch_max_attempts: int = 8
    integration_fetch_base_delay_seconds: float = 60.0
    integration_fetch_max_delay_seconds: float = 3600.0
    realtime_queue_max: int = 1000

    teams_client_id: str = ""
    teams_client_secret: str = ""
    teams_tenant_id: str = "organizations"
    # Delegated scopes. OnlineMeetingTranscript.Read.All requires tenant admin
    # consent; leave TEAMS_REQUEST_TRANSCRIPT_SCOPE=false where IT has not approved it.
    teams_request_transcript_scope: bool = True

    zoom_client_id: str = ""
    zoom_client_secret: str = ""
    zoom_webhook_secret_token: str = ""
    # Space-separated scopes; empty = scopes configured on the Zoom Marketplace app.
    zoom_scopes: str = ""
    # Operator assertion that RTMS is provisioned for the account/app.
    zoom_rtms_enabled: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""

    # Development/test only: point connectors at a fake provider server. Any
    # override marks every connection as SANDBOX and is refused in production.
    integration_endpoint_overrides: str = ""  # JSON object, e.g. {"google_meet": "http://localhost:9100/google"}
    # Development/test only: base URLs the *browser* uses for the authorize step when it differs from the
    # address the API uses (e.g. Docker: browser → localhost:9100, API → fake-providers:9100).
    integration_browser_endpoint_overrides: str = ""

    @field_validator("integration_endpoint_overrides", "integration_browser_endpoint_overrides")
    @classmethod
    def _valid_overrides(cls, value: str) -> str:
        # Fail fast: a malformed value must never silently fall back to real endpoints.
        if value.strip():
            try:
                mapping = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("INTEGRATION_*ENDPOINT_OVERRIDES must be a JSON object") from exc
            if not isinstance(mapping, dict) or not all(isinstance(v, str) for v in mapping.values()):
                raise ValueError("INTEGRATION_*ENDPOINT_OVERRIDES must map provider names to base URLs")
        return value

    @field_validator("cors_allowed_origins", "trusted_hosts", "provider_base_url_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def secret_storage_available(self) -> bool:
        return bool(self.secret_encryption_keys.strip())

    @property
    def remember_key_supported(self) -> bool:
        return self.secret_storage_available and self.allow_persistent_api_keys

    def validate_for_environment(self) -> None:
        """Refuse insecure combinations before the app starts serving."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.auth_mode == "dev":
            problems.append("AUTH_MODE=dev is not allowed in production")
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true in production")
        if self.auth_mode == "oidc" and not all(
            [self.oidc_issuer, self.oidc_client_id, self.oidc_client_secret, self.oidc_redirect_uri]
        ):
            problems.append("OIDC_* settings are required in production")
        if "*" in self.trusted_hosts:
            problems.append("TRUSTED_HOSTS must be explicit in production")
        if self.allow_private_provider_urls:
            problems.append("ALLOW_PRIVATE_PROVIDER_URLS must be false in production")
        if self.integration_endpoint_overrides.strip():
            problems.append("INTEGRATION_ENDPOINT_OVERRIDES must be empty in production")
        if self.integration_browser_endpoint_overrides.strip():
            problems.append("INTEGRATION_BROWSER_ENDPOINT_OVERRIDES must be empty in production")
        if self.enable_mock_provider:
            problems.append("ENABLE_MOCK_PROVIDER must be false in production")
        if problems:
            raise RuntimeError("Insecure production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
