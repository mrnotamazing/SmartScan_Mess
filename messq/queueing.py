"""M/M/c queueing formulas (Erlang C). Times are in minutes, rates per minute."""

from __future__ import annotations

import math


def erlang_c(c: int, offered_load: float) -> float:
    """Probability an arrival has to wait in an M/M/c queue.

    offered_load a = lambda / mu; requires a < c. Uses the numerically stable
    Erlang-B recursion instead of factorials.
    """
    if c < 1:
        raise ValueError("need at least one server")
    if offered_load <= 0:
        return 0.0
    if offered_load >= c:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):
        b = offered_load * b / (k + offered_load * b)
    return c * b / (c - offered_load * (1 - b))


def mmc_wait(lam: float, mu: float, c: int) -> float:
    """Expected time in queue (before service starts), Wq = C(c, a) / (c*mu - lambda)."""
    if lam <= 0:
        return 0.0
    if lam >= c * mu:
        return math.inf
    return erlang_c(c, lam / mu) / (c * mu - lam)
