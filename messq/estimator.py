"""Per-hall state estimated purely from entry scans.

There are no exit scans, so nothing here is measured directly. A visit is
modelled as two parts:

    time inside = time queueing (grows in a surge) + time eating (fairly fixed)

* backlog (people waiting to be served) = fluid queue: each tick it grows by
  the arrivals and shrinks by what the counters can serve (the hall's assumed
  serving capacity; zero while the kitchen reports the main tray out).
* seated = people served in the last `stay` minutes (they're eating).
* occupancy (people inside) = backlog + seated.

So on a normal day a visit takes about queue + stay (measured: ~18 min), and in a
surge everyone stuck in the queue still counts as inside. A plain "entries in the
last 18 minutes" count would forget them exactly when the hall is busiest.
Accuracy depends on the configured serving rate, so measure that on site.
"""

from __future__ import annotations

import bisect
from collections import deque

SCAN_HISTORY_S = 15 * 60  # scans kept for rate and 1-/5-/10-minute counts


class MessEstimator:
    def __init__(self, stay_s: float, rate_window_s: float):
        self.stay_s = stay_s
        self.rate_window_s = rate_window_s
        self._times: deque[float] = deque()
        self._served: deque[tuple[float, float]] = deque()  # (time, people served in that tick)
        self._seated = 0.0  # running sum of _served
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
        """Move the queue forward to `now`: add new scans, serve what the counters can."""
        waiting = self.backlog + self._pending
        self._pending = 0
        if self._last_advance is not None:
            dt_min = max(0.0, now - self._last_advance) / 60.0
            served = min(waiting, capacity_per_min * dt_min)
        else:
            served = 0.0
        self.backlog = waiting - served
        if served > 0:
            self._served.append((now, served))
            self._seated += served
        self._last_advance = now
        while self._served and self._served[0][0] <= now - self.stay_s:
            self._seated -= self._served.popleft()[1]
        horizon = now - max(SCAN_HISTORY_S, self.rate_window_s)
        while self._times and self._times[0] < horizon:
            self._times.popleft()

    def _count_since(self, start: float, now: float) -> int:
        lo = bisect.bisect_right(self._times, start)
        hi = bisect.bisect_right(self._times, now)
        return hi - lo

    def seated(self) -> float:
        return max(0.0, self._seated)

    def occupancy(self, now: float | None = None) -> float:
        """People inside: still queueing + served recently and eating."""
        return self.backlog + self.seated()

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
