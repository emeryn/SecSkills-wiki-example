"""In-process sliding-window rate limits for expensive administrator actions.

The API runs as a single process; Nginx adds per-IP limits in front. Sign-in throttling, which must
survive restarts and span processes, lives in the database instead (``repositories.throttle``).
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.errors import AppError


class RateLimiter:
    def __init__(
        self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Count one event for ``key``; raises 429 when the window is full."""
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self._window:
                events.popleft()
            if len(events) >= self._max:
                wait = int(self._window - (now - events[0])) + 1
                raise AppError(
                    429, "RATE_LIMITED", f"Too many attempts. Try again in {wait} seconds"
                )
            events.append(now)
