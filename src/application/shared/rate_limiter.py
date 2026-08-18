from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_calls: int = 100, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        calls = self._calls[key]
        self._calls[key] = [t for t in calls if t > window_start]
        if len(self._calls[key]) >= self.max_calls:
            return False
        self._calls[key].append(now)
        return True
