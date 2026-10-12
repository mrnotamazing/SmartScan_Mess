"""How to split incoming students between halls without causing herding.

If everyone is told "go to the emptier hall", that hall fills up and the advice
flips back and forth (a congestion game). Instead we compute the split of the
incoming flow at which the predicted waits are equal (a Wardrop equilibrium)
and give each student a random draw from that split.
"""

from __future__ import annotations

from typing import Callable, Mapping

WaitFn = Callable[[float], float]  # arrival rate (students/min) -> predicted total minutes


def equilibrium_split(wait_fns: Mapping[str, WaitFn], total_rate: float, iters: int = 30) -> dict[str, float]:
    """Shares s_i (sum 1) such that W_i(s_i * total) is equal for every used hall.

    Water-filling: for a common wait level L, hall i can absorb the largest
    rate with W_i(rate) <= L. Bisect on L until the absorbed rates add up to
    the total. Halls whose wait is above L even with zero arrivals get 0.
    """
    ids = list(wait_fns)
    if total_rate <= 1e-9:
        total_rate = 1e-3

    def absorbed(fn: WaitFn, level: float) -> float:
        if fn(0.0) > level:
            return 0.0
        if fn(total_rate) <= level:
            return total_rate
        lo, hi = 0.0, total_rate
        for _ in range(iters):
            mid = (lo + hi) / 2
            if fn(mid) <= level:
                lo = mid
            else:
                hi = mid
        return lo

    lo = min(wait_fns[i](0.0) for i in ids)
    hi = max(wait_fns[i](total_rate) for i in ids)
    for _ in range(iters):
        mid = (lo + hi) / 2
        if sum(absorbed(wait_fns[i], mid) for i in ids) >= total_rate:
            hi = mid
        else:
            lo = mid
    rates = {i: absorbed(wait_fns[i], hi) for i in ids}
    s = sum(rates.values())
    if s <= 0:
        return {i: 1 / len(ids) for i in ids}
    return {i: r / s for i, r in rates.items()}


def greedy_split(current_waits: Mapping[str, float]) -> dict[str, float]:
    """Everyone to the hall that looks best right now. Kept only as a baseline
    for the simulator: it is the policy that causes herding."""
    best = min(current_waits, key=current_waits.get)
    return {i: 1.0 if i == best else 0.0 for i in current_waits}


def compensate_for_noncompliance(
    target: Mapping[str, float], natural: Mapping[str, float], compliance: float
) -> dict[str, float]:
    """If only a fraction `compliance` follows advice and the rest go where they
    usually go (`natural`), advise shares a such that
    (1 - compliance) * natural + compliance * a  ~=  target."""
    if compliance >= 1.0 or not natural:
        return dict(target)
    k = max(compliance, 1e-6)
    raw = {i: max(0.0, (target[i] - (1 - k) * natural.get(i, 0.0)) / k) for i in target}
    s = sum(raw.values())
    return {i: v / s for i, v in raw.items()} if s > 0 else dict(target)


def apply_floor(shares: Mapping[str, float], floor: float, eligible: set[str]) -> dict[str, float]:
    """Raise every eligible hall to at least `floor` of the flow, taking the
    difference proportionally from the others. Ineligible halls (e.g. food out)
    are not raised, but keep whatever share the wait model gave them."""
    if not eligible or floor <= 0:
        return dict(shares)
    floor = min(floor, 1 / len(shares))
    lifted = {i: max(s, floor) if i in eligible else s for i, s in shares.items()}
    extra = sum(lifted.values()) - 1
    if extra <= 0:
        return lifted
    donors = {i: s - floor if i in eligible else s for i, s in lifted.items()}
    pool = sum(max(0.0, d) for d in donors.values())
    return {i: s - extra * max(0.0, donors[i]) / pool for i, s in lifted.items()}


def smooth(prev: Mapping[str, float] | None, new: Mapping[str, float], alpha: float) -> dict[str, float]:
    if not prev:
        return dict(new)
    out = {i: alpha * new[i] + (1 - alpha) * prev.get(i, new[i]) for i in new}
    s = sum(out.values())
    return {i: v / s for i, v in out.items()}


def door_switch_probs(
    target: Mapping[str, float],
    natural: Mapping[str, float],
    compliance: float,
    waits_here: Mapping[str, float],
    switch_walk_min: float,
    min_saving_min: float,
) -> dict[str, tuple[str | None, float]]:
    """Screens outside each door: what fraction of students arriving at door i
    should be told to walk to another mess, and which one.

    Students reach the mess they usually go to (`natural` split). To turn that
    into the `target` split, the surplus at over-target doors is sent to the
    most under-target mess. Nobody is told to switch unless it saves at least
    `min_saving_min` after the walk, so near-ties never cost anyone a walk.
    """
    k = max(compliance, 1e-6)
    deficit = {j: target.get(j, 0.0) - natural.get(j, 0.0) for j in target}
    out: dict[str, tuple[str | None, float]] = {}
    for i in target:
        h = natural.get(i, 0.0)
        surplus = h - target[i]
        others = [j for j in target if j != i]
        if surplus <= 1e-9 or h <= 0 or not others:
            out[i] = (None, 0.0)
            continue
        dest = max(others, key=lambda j: deficit[j])
        saving = waits_here[i] - (waits_here[dest] + switch_walk_min)
        if deficit[dest] <= 0 or saving < min_saving_min:
            out[i] = (None, 0.0)
            continue
        out[i] = (dest, min(1.0, surplus / h / k))
    return out
