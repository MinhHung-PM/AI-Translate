"""Translation and memo generation on top of any ``AIProvider``."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai.base import (
    AIProvider,
    Credentials,
    MemoGenerationResult,
    MemoRequest,
    ModelParams,
    ProviderError,
    ProviderErrorCode,
    TokenUsage,
    TranslatedSegment,
    TranslationRequest,
    TranslationResult,
)
from app.ai.memo_schema import strip_code_fence
from app.ai.prompts.memo import build_memo_messages
from app.ai.prompts.translation import build_translation_messages


class _TranslationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: int
    text: str
    ambiguity: str | None = None


class _TranslationOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    translations: list[_TranslationItem]


def parse_translation_output(raw: str, expected_refs: list[int]) -> list[TranslatedSegment]:
    """Strictly validate a translation batch: same refs, no gaps, no extras."""
    try:
        parsed = _TranslationOutput.model_validate(json.loads(strip_code_fence(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProviderError(ProviderErrorCode.invalid_output, "Translation output was not valid JSON") from exc
    by_ref = {item.ref: item for item in parsed.translations}
    if sorted(by_ref) != sorted(expected_refs) or len(parsed.translations) != len(expected_refs):
        raise ProviderError(ProviderErrorCode.invalid_output, "Translation output did not match the input segments")
    out: list[TranslatedSegment] = []
    for ref in expected_refs:  # preserve input order regardless of output order
        item = by_ref[ref]
        if not item.text.strip():
            raise ProviderError(ProviderErrorCode.invalid_output, f"Empty translation for segment {ref}")
        note = item.ambiguity.strip() if item.ambiguity and item.ambiguity.strip() else None
        out.append(TranslatedSegment(ref=ref, text=item.text.strip(), ambiguity_note=note))
    return out


class LLMTranslationProvider:
    def __init__(
        self, provider: AIProvider, creds: Credentials, model: str, params: ModelParams, max_attempts: int
    ) -> None:
        self.provider_key = provider.key
        self.model = model
        self._provider = provider
        self._creds = creds
        self._params = params
        self._max_attempts = max_attempts

    def translate(self, request: TranslationRequest) -> TranslationResult:
        system, user = build_translation_messages(request)
        usage = TokenUsage(reported_by_provider=True)
        expected = [s.ref for s in request.segments]
        last_error: ProviderError | None = None
        for attempt in range(1, self._max_attempts + 1):
            result = self._provider.complete_json(self._creds, self.model, system, user, self._params)
            usage.add(result.usage)
            try:
                segments = parse_translation_output(result.text, expected)
                return TranslationResult(segments=segments, usage=usage, model=result.model, attempts=attempt)
            except ProviderError as err:
                last_error = err
        assert last_error is not None
        raise last_error


class LLMMemoGenerator:
    def __init__(self, provider: AIProvider, creds: Credentials, model: str, params: ModelParams) -> None:
        self.provider_key = provider.key
        self.model = model
        self._provider = provider
        self._creds = creds
        self._params = params

    def generate(self, request: MemoRequest, *, repair_hint: str | None = None) -> MemoGenerationResult:
        system, user = build_memo_messages(request, repair_hint)
        result = self._provider.complete_json(self._creds, self.model, system, user, self._params)
        return MemoGenerationResult(raw_json=result.text, usage=result.usage, model=result.model)
