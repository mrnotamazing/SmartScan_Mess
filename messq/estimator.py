"""Per-hall state estimated purely from entry scans.

There are no exit scans, so nothing here is measured directly:

* occupancy  = entries in the last N minutes (N ~ typical time spent inside)
* arrival rate = entries in the last few minutes / window length
* backlog (people waiting to be served) = fluid queue: each tick it grows by
  the arrivals and shrinks by the hall's assumed serving capacity. Its accuracy
  depends on the configured service rate, so measure that on site.
"""

from __future__ import annotations

import bisect
from collections import deque


class MessEstimator:
    def __init__(self, occupancy_window_s: float, rate_window_s: float):
        self.occupancy_window_s = occupancy_window_s
        self.rate_window_s = rate_window_s
        self._times: deque[float] = deque()
        self._pending = 0
        self._last_advance: float | None = None
        self.backlog = 0.0

    def add_scan(self, ts: float) -> None:
        if not self._times or ts >= self._times[-1]:
            self._times.append(ts)
        else:  # polled events can arrive slightly out of order
            times = list(self._times)
            bisect.insort(times, ts)
            self._times = deque(times)
        self._pending += 1

    def advance(self, now: float, capacity_per_min: float) -> None:
        """Move the fluid backlog forward to `now` and drop expired scans."""
        if self._last_advance is not None:
            dt_min = max(0.0, now - self._last_advance) / 60.0
            self.backlog = max(0.0, self.backlog + self._pending - capacity_per_min * dt_min)
        else:
            self.backlog += self._pending
        self._pending = 0
        self._last_advance = now
        horizon = now - max(self.occupancy_window_s, self.rate_window_s)
        while self._times and self._times[0] < horizon:
            self._times.popleft()
        self.backlog = min(self.backlog, self.occupancy(now))

    def _count_since(self, start: float, now: float) -> int:
        lo = bisect.bisect_right(self._times, start)
        hi = bisect.bisect_right(self._times, now)
        return hi - lo

    def occupancy(self, now: float) -> int:
        return self._count_since(now - self.occupancy_window_s, now)

    def arrival_rate_per_min(self, now: float) -> float:
        return self._count_since(now - self.rate_window_s, now) / (self.rate_window_s / 60.0)

    def count_last(self, now: float, seconds: float) -> int:
        """Scans in the last `seconds` (used later for 1-min / 5-min surge alerts)."""
        return self._count_since(now - seconds, now)


class Deduplicator:
    """Remembers recent event ids so re-polled events are counted once."""

    def __init__(self, max_size: int = 50_000):
        self._seen: set[str] = set()
        self._order: deque[str] = deque()
        self._max = max_size

    def is_new(self, event_id: str | None) -> bool:
        if event_id is None:
            return True
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        self._order.append(event_id)
        if len(self._order) > self._max:
            self._seen.discard(self._order.popleft())
        return True
