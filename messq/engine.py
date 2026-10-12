"""The live engine: scan events + kitchen signals in, recommendation out.

It only sees what the real system will see (entry scans and kitchen taps),
never ground truth, so the simulator tests the estimator as well as the policy.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from . import routing
from .config import AppConfig, MessConfig
from .estimator import Deduplicator, MessEstimator
from .events import FoodSignal, FoodState, ScanEvent
from .waits import HallState, WaitBreakdown, predict_wait


class Policy(str, Enum):
    NONE = "none"  # no advice (baseline / control group)
    GREEDY = "greedy"  # everyone to the best-looking hall (herding baseline)
    EQUILIBRIUM = "equilibrium"  # probabilistic split that equalises waits


class Status(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


@dataclass(frozen=True)
class HallView:
    mess_id: str
    name: str
    occupancy: int  # estimated
    seats: int
    load: float  # occupancy / seats
    arrival_rate: float  # scans/min over the rate window (measured)
    backlog: float  # estimated people waiting to be served
    food: FoodState
    wait: WaitBreakdown
    status: Status
    share: float  # fraction of students currently advised to go here


@dataclass(frozen=True)
class Snapshot:
    ts: float
    halls: tuple[HallView, ...]

    @property
    def headline(self) -> HallView:
        return max(self.halls, key=lambda h: h.share)

    @property
    def advice(self) -> str:
        """Text for a shared screen. A near-even split means both halls are fine;
        saying "Go to A" there would be noise that costs trust."""
        head = self.headline
        if head.share < 0.6:
            return "Both halls OK - go to either"
        return f"Go to {head.name}"

    def hall(self, mess_id: str) -> HallView:
        return next(h for h in self.halls if h.mess_id == mess_id)


class Engine:
    def __init__(self, cfg: AppConfig, policy: Policy = Policy.EQUILIBRIUM):
        self.cfg = cfg
        self.policy = policy
        e = cfg.engine
        self._est = {m.id: MessEstimator(e.occupancy_window_min * 60, e.rate_window_min * 60) for m in cfg.messes}
        self._food = {m.id: (FoodState.OK, 0.0) for m in cfg.messes}
        self._dedupe = Deduplicator()
        self._shares: dict[str, float] | None = None
        self._last_route_ts: float | None = None
        self.now = 0.0

    # ---- inputs -----------------------------------------------------------
    def ingest(self, events: list[ScanEvent]) -> int:
        n = 0
        for ev in events:
            if ev.mess_id not in self._est or not self._dedupe.is_new(ev.event_id):
                continue
            self._est[ev.mess_id].add_scan(ev.ts)
            n += 1
        return n

    def food_signal(self, sig: FoodSignal) -> None:
        current, since = self._food[sig.mess_id]
        if sig.state is not current:
            self._food[sig.mess_id] = (sig.state, sig.ts)

    def food_state(self, mess_id: str, now: float) -> tuple[FoodState, float]:
        """Kitchen state, with stale taps expired. Staff forget to tap
        "refilled"; without expiry one missed tap would keep a hall marked
        empty and send everyone to the other hall for the rest of the meal."""
        state, since = self._food[mess_id]
        age_min = (now - since) / 60.0
        e = self.cfg.engine
        if state is FoodState.OUT and age_min > self.cfg.mess(mess_id).food_refill_time_min + e.food_out_grace_min:
            return FoodState.OK, since
        if state is FoodState.LOW and age_min > e.food_low_expiry_min:
            return FoodState.OK, since
        return state, since

    # ---- update -----------------------------------------------------------
    def update(self, now: float) -> None:
        self.now = now
        for m in self.cfg.messes:
            cap = 0.0 if self.food_state(m.id, now)[0] is FoodState.OUT else m.capacity_per_min
            self._est[m.id].advance(now, cap)
        due = self._last_route_ts is None or now - self._last_route_ts >= self.cfg.engine.routing_update_s
        if due:
            self._shares = self._route(now)
            self._last_route_ts = now

    def _state(self, m: MessConfig, now: float) -> HallState:
        est = self._est[m.id]
        food, since = self.food_state(m.id, now)
        return HallState(
            backlog=est.backlog,
            occupancy=est.occupancy(now),
            food=food,
            food_out_for_min=(now - since) / 60.0 if food is FoodState.OUT else 0.0,
        )

    def _route(self, now: float) -> dict[str, float]:
        e = self.cfg.engine
        states = {m.id: self._state(m, now) for m in self.cfg.messes}
        rates = {m.id: self._est[m.id].arrival_rate_per_min(now) for m in self.cfg.messes}
        if self.policy is Policy.NONE:
            return {m.id: 1 / len(self.cfg.messes) for m in self.cfg.messes}
        if self.policy is Policy.GREEDY:
            return routing.greedy_split(
                {m.id: predict_wait(m, e, states[m.id], rates[m.id]).total for m in self.cfg.messes}
            )
        fns = {m.id: (lambda lam, m=m: predict_wait(m, e, states[m.id], lam).total) for m in self.cfg.messes}
        target = routing.equilibrium_split(fns, sum(rates.values()))
        advised = routing.compensate_for_noncompliance(target, e.natural_share, e.assumed_compliance)
        open_halls = {i for i, s in states.items() if s.food is not FoodState.OUT}
        advised = routing.apply_floor(advised, e.min_share, open_halls)
        return routing.smooth(self._shares, advised, e.routing_smoothing)

    # ---- outputs ----------------------------------------------------------
    def snapshot(self) -> Snapshot:
        e = self.cfg.engine
        now = self.now
        shares = self._shares or {m.id: 1 / len(self.cfg.messes) for m in self.cfg.messes}
        views = []
        for m in self.cfg.messes:
            st = self._state(m, now)
            rate = self._est[m.id].arrival_rate_per_min(now)
            wb = predict_wait(m, e, st, rate)
            if st.food is FoodState.OUT or wb.wait >= e.red_wait_min:
                status = Status.RED
            elif st.food is FoodState.LOW or wb.wait >= e.amber_wait_min:
                status = Status.AMBER
            else:
                status = Status.GREEN
            views.append(
                HallView(
                    mess_id=m.id,
                    name=m.name,
                    occupancy=int(st.occupancy),
                    seats=m.seats,
                    load=st.occupancy / m.seats,
                    arrival_rate=rate,
                    backlog=st.backlog,
                    food=st.food,
                    wait=wb,
                    status=status,
                    share=shares[m.id],
                )
            )
        return Snapshot(ts=now, halls=tuple(views))

    def shares(self) -> dict[str, float]:
        return dict(self._shares or {m.id: 1 / len(self.cfg.messes) for m in self.cfg.messes})

    def recommend(self, rng: random.Random) -> str:
        """One student's advice: a random draw from the current split."""
        shares = self.shares()
        r, acc = rng.random(), 0.0
        for mess_id, s in shares.items():
            acc += s
            if r < acc:
                return mess_id
        return mess_id

    def scans_last(self, mess_id: str, seconds: float) -> int:
        return self._est[mess_id].count_last(self.now, seconds)
