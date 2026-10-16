"""Ordering of transcript events by provider time, tolerant of out-of-order delivery."""

from __future__ import annotations

import time
from collections.abc import Iterable

from app.integrations.models import CanonicalEvent


def order_key(e: CanonicalEvent) -> tuple[int, int, int, float]:
    return (
        0 if e.start_timestamp_ms is not None else 1,
        e.start_timestamp_ms if e.start_timestamp_ms is not None else 0,
        e.provider_sequence if e.provider_sequence is not None else 0,
        e.received_at.timestamp(),
    )


def sort_events(events: Iterable[CanonicalEvent]) -> list[CanonicalEvent]:
    return sorted(events, key=order_key)


class OrderingBuffer:
    """Small reorder window for live streams: events are held for at most
    ``max_delay_s`` (or until ``max_items`` are buffered) and released in
    provider-time order. Memory is bounded by ``max_items``. Events that arrive
    after a later event was already released are still released (never
    dropped) and flagged ``late=True`` in source metadata."""

    def __init__(self, max_items: int = 50, max_delay_s: float = 1.5, clock: object = time.monotonic) -> None:
        self.max_items = max_items
        self.max_delay_s = max_delay_s
        self._clock = clock
        self._items: list[tuple[float, CanonicalEvent]] = []
        self._last_released: tuple[int, int, int, float] | None = None

    def __len__(self) -> int:
        return len(self._items)

    def add(self, event: CanonicalEvent) -> list[CanonicalEvent]:
        self._items.append((self._now(), event))
        return self.release()

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def release(self, force: bool = False) -> list[CanonicalEvent]:
        now = self._now()
        self._items.sort(key=lambda it: order_key(it[1]))
        out: list[CanonicalEvent] = []
        while self._items and (
            force or len(self._items) > self.max_items or now - min(t for t, _ in self._items) >= self.max_delay_s
        ):
            _, event = self._items.pop(0)
            key = order_key(event)
            if self._last_released is not None and key < self._last_released:
                event.source_metadata = {**event.source_metadata, "late": True}
            else:
                self._last_released = key
            out.append(event)
        return out

    def flush(self) -> list[CanonicalEvent]:
        return self.release(force=True)
