"""Provider-neutral AI interfaces.

Business logic depends only on ``TranslationProvider`` and
``MemoGenerationProvider``. Concrete adapters (OpenAI, OpenAI-compatible,
mock) live in their own modules and keep request formats private.

Layering::

    services.translation / services.memo_generation
        -> TranslationProvider / MemoGenerationProvider   (this module)
            -> LLM-backed implementation (llm.py) -> AIProvider.complete_json
            -> MockProvider (implements both directly, deterministic)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Capability(StrEnum):
    translation = "translation"
    memo_generation = "memo_generation"
    structured_output = "structured_output"
    model_discovery = "model_discovery"
    streaming = "streaming"
    speech_to_text = "speech_to_text"


class ProviderErrorCode(StrEnum):
    auth_failed = "auth_failed"
    permission_denied = "permission_denied"
    rate_limited = "rate_limited"
    quota_exceeded = "quota_exceeded"
    timeout = "timeout"
    unavailable = "unavailable"
    bad_request = "bad_request"
    invalid_output = "invalid_output"
    not_configured = "not_configured"
    unsupported = "unsupported"


class ProviderError(Exception):
    """Normalized provider failure. ``message`` is safe to show to users."""

    def __init__(self, code: ProviderErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Credentials:
    api_key: str | None
    base_url: str | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    # False when the provider did not report usage and counts were estimated.
    reported_by_provider: bool = False

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.reported_by_provider = self.reported_by_provider and other.reported_by_provider


@dataclass
class CompletionResult:
    text: str
    usage: TokenUsage
    model: str


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str
    models: list[str] | None = None


@dataclass(frozen=True)
class ModelParams:
    temperature: float = 0.0
    max_output_tokens: int = 4000
    seed: int | None = 7


@runtime_checkable
class AIProvider(Protocol):
    """Low-level adapter for an LLM API."""

    key: str

    def test_connection(self, creds: Credentials, model: str) -> ConnectionTestResult: ...

    def list_models(self, creds: Credentials) -> list[str] | None: ...

    def complete_json(
        self, creds: Credentials, model: str, system: str, user: str, params: ModelParams
    ) -> CompletionResult: ...


# ---- Translation -----------------------------------------------------------


@dataclass(frozen=True)
class TranslationSegment:
    ref: int  # transcript sequence number, used to map results back
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str
    context: str | None = None


@dataclass(frozen=True)
class TranslationRequest:
    source_language: str
    target_language: str
    segments: list[TranslationSegment]
    context_before: list[TranslationSegment] = field(default_factory=list)
    glossary: list[GlossaryTerm] = field(default_factory=list)
    instructions: str | None = None


@dataclass(frozen=True)
class TranslatedSegment:
    ref: int
    text: str
    ambiguity_note: str | None = None


@dataclass
class TranslationResult:
    segments: list[TranslatedSegment]
    usage: TokenUsage
    model: str
    attempts: int = 1


class TranslationProvider(Protocol):
    provider_key: str
    model: str

    def translate(self, request: TranslationRequest) -> TranslationResult: ...


# ---- Memo generation -------------------------------------------------------


@dataclass(frozen=True)
class MemoTranscriptLine:
    ref: int
    text: str
    speaker: str | None
    start_ms: int | None


@dataclass(frozen=True)
class MemoRequest:
    meeting_title: str
    project_name: str
    meeting_date_iso: str
    timezone: str
    participants: list[str]
    objective: str | None
    memo_language: str
    source_language: str | None
    lines: list[MemoTranscriptLine]
    custom_instructions: str | None = None
    glossary: list[GlossaryTerm] = field(default_factory=list)


@dataclass
class MemoGenerationResult:
    raw_json: str  # validated by the caller against MemoDraft
    usage: TokenUsage
    model: str


class MemoGenerationProvider(Protocol):
    provider_key: str
    model: str

    def generate(self, request: MemoRequest, *, repair_hint: str | None = None) -> MemoGenerationResult: ...


def estimate_tokens(text: str) -> int:
    """Rough token estimate used only when a provider does not report usage.
    CJK text tokenizes denser than Latin text, so weigh it separately."""
    cjk = sum(1 for ch in text if "぀" <= ch <= "鿿" or "＀" <= ch <= "￯")
    return max(1, cjk + (len(text) - cjk) // 4)
