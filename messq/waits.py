"""Predicted time-to-food for a student who decides *now* to walk to a hall.

    total = walk + serving-queue wait + service + seat wait + food delay

Serving-queue wait combines
  * the estimated current backlog, projected forward by the walk time,
  * fluid growth if arrivals exceed capacity over the decision horizon, and
  * the steady-state M/M/c (Erlang C) wait for the remaining randomness.
All inputs are estimates (see estimator.py), so the output is an estimate too.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EngineConfig, MessConfig
from .events import FoodState
from .queueing import mmc_wait

RHO_CAP = 0.95  # Erlang C explodes near rho = 1; overload is handled by the fluid term


@dataclass(frozen=True)
class HallState:
    backlog: float  # estimated people waiting to be served
    occupancy: float  # estimated people inside (entries in last N min)
    food: FoodState
    food_out_for_min: float = 0.0  # minutes since kitchen tapped "out"


@dataclass(frozen=True)
class WaitBreakdown:
    walk: float
    queue: float
    service: float
    seat: float
    food: float

    @property
    def wait(self) -> float:
        """What we show students: time spent waiting after arriving."""
        return self.queue + self.seat + self.food

    @property
    def total(self) -> float:
        return self.walk + self.queue + self.service + self.seat + self.food


def predict_wait(mess: MessConfig, eng: EngineConfig, state: HallState, lam: float) -> WaitBreakdown:
    """Wait for a student arriving after the walk, if the hall receives `lam` students/min."""
    walk = mess.walk_time_s / 60.0
    mu = mess.service_rate_per_counter_per_min
    cap = mess.capacity_per_min
    if cap <= 0:
        return WaitBreakdown(walk, 1e6, 0.0, 0.0, 0.0)
    horizon = eng.horizon_min

    food_delay = 0.0
    if state.food is FoodState.OUT:
        remaining = max(1.0, mess.food_refill_time_min - state.food_out_for_min)
        # Nobody is served until the refill: the queue keeps growing meanwhile.
        backlog = state.backlog + lam * remaining
        food_delay = max(0.0, remaining - walk)
    else:
        backlog = max(0.0, state.backlog + (lam - cap) * walk)
        if state.food is FoodState.LOW:
            food_delay = eng.food_low_penalty_min

    growth = max(0.0, lam - cap) * horizon / 2  # average extra queue over the horizon
    queue = (backlog + growth) / cap + mmc_wait(min(lam, RHO_CAP * cap), mu, mess.counters)

    seated = max(0.0, state.occupancy - state.backlog)
    turnover = mess.seats / eng.stay_mean_min  # seats freed per minute when full
    projected = seated + (min(lam, cap) - seated / eng.stay_mean_min) * horizon / 2
    seat = max(0.0, projected - mess.seats) / turnover

    return WaitBreakdown(walk=walk, queue=queue, service=1.0 / mu, seat=seat, food=food_delay)
