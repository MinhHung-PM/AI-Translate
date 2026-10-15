from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.ai.base import Capability
from app.core.config import get_settings


class ModelInfo(BaseModel):
    id: str
    label: str | None = None
    input_per_1m: Decimal | None = None
    output_per_1m: Decimal | None = None


class ProviderInfo(BaseModel):
    key: str
    display_name: str
    adapter: str
    default_base_url: str | None = None
    requires_api_key: bool = True
    allow_custom_base_url: bool = False
    allow_custom_model: bool = False
    dev_only: bool = False
    capabilities: list[Capability] = Field(default_factory=list)
    models: list[ModelInfo] = Field(default_factory=list)

    def model_info(self, model_id: str) -> ModelInfo | None:
        return next((m for m in self.models if m.id == model_id), None)


class Catalog(BaseModel):
    providers: list[ProviderInfo]

    def get(self, key: str) -> ProviderInfo | None:
        return next((p for p in self.providers if p.key == key), None)


def load_catalog(path: Path) -> Catalog:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Catalog.model_validate({"providers": data["providers"]})


@lru_cache
def get_catalog() -> Catalog:
    settings = get_settings()
    catalog = load_catalog(settings.provider_catalog_path)
    if not settings.enable_mock_provider:
        catalog = Catalog(providers=[p for p in catalog.providers if not p.dev_only])
    return catalog


def estimate_cost(provider_key: str, model: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    """Estimated cost in USD from configured prices; None if unpriced."""
    provider = get_catalog().get(provider_key)
    info = provider.model_info(model) if provider else None
    if info is None or info.input_per_1m is None or info.output_per_1m is None:
        return None
    million = Decimal(1_000_000)
    cost = (Decimal(input_tokens or 0) * info.input_per_1m + Decimal(output_tokens or 0) * info.output_per_1m) / million
    return cost.quantize(Decimal("0.000001"))
