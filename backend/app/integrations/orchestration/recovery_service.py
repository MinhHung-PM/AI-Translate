"""Bounded retry policy (exponential backoff + full jitter, honouring Retry-After)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.db.base import utcnow
from app.integrations.errors import IntegrationError


def backoff_delay(
    attempt: int, *, base: float | None = None, cap: float | None = None, rng: random.Random | None = None
) -> float:
    s = get_settings()
    base = s.integration_fetch_base_delay_seconds if base is None else base
    cap = s.integration_fetch_max_delay_seconds if cap is None else cap
    ceiling = min(cap, base * (2 ** max(0, attempt - 1)))
    return (rng or random.SystemRandom()).uniform(ceiling / 2, ceiling)


def next_attempt_at(attempt: int, err: IntegrationError | None = None) -> datetime | None:
    """When to try again, or None if the attempt budget is exhausted or the error is permanent."""
    if err is not None and not err.retryable:
        return None
    if attempt >= get_settings().integration_fetch_max_attempts:
        return None
    delay = backoff_delay(attempt)
    if err is not None and err.retry_after is not None:
        delay = max(delay, err.retry_after)
    return utcnow() + timedelta(seconds=delay)
