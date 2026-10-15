"""In-process sliding-window rate limiter for expensive (AI) endpoints.

Per-process state is adequate for a single API replica. For multiple
replicas, swap ``RateLimiter`` for a Redis-backed implementation with the
same interface (documented in docs/architecture.md).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import RateLimited


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window_seconds - (now - hits[0])) + 1
                raise RateLimited("Too many AI requests; please retry later", details={"retry_after_seconds": retry})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
