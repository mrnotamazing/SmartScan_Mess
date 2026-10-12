"""The live engine: scan events + kitchen signals in, recommendation out.

It only sees what the real system will see (entry scans and kitchen taps),
never ground truth, so the simulator tests the estimator as well as the policy.
Everything it knows about a hall comes from people who have already scanned in;
people still outside are invisible to it by design.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from enum import Enum

from . import routing
from .config import AppConfig, MessConfig
from .estimator import Deduplicator, MessEstimator
from .events import FoodSignal, FoodState, ScanEvent
from .waits import HallState, WaitBreakdown, predict_wait

FRESH_BATCH_MIN = 10  # after a "refilled" tap, screens may say "fresh batch just out" for this long
_SEVERITY = {FoodState.OK: 0, FoodState.LOW: 1, FoodState.OUT: 2}


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
    occupancy: int  # people who scanned in during the last N minutes (estimate of people inside)
    seats: int
    load: float  # occupancy / seats
    arrival_rate: float  # scans/min over the rate window (measured)
    backlog: float  # estimated people waiting to be served
    food: FoodState
    fresh: bool  # kitchen tapped "refilled" in the last few minutes
    wait: WaitBreakdown  # for someone already at this door (no walk)
    status: Status
    share: float  # fraction of students the system wants in this hall

    @property
    def space(self) -> int:
        return max(0, self.seats - self.occupancy)


@dataclass(frozen=True)
class DoorAdvice:
    """What the screen outside one mess says."""

    at: str
    go_to: str | None  # the mess to suggest walking to, or None = come in here
    p_switch: float  # share of arriving students that should switch
    saving_min: float  # minutes saved by switching, after the walk

    @property
    def level(self) -> str:
        """strong: "Mess B is faster, go there"; soft: "in a hurry? B is faster"; stay."""
        if self.go_to is None or self.p_switch < 0.15:
            return "stay"
        return "strong" if self.p_switch >= 0.5 else "soft"


@dataclass(frozen=True)
class Snapshot:
    ts: float
    halls: tuple[HallView, ...]
    doors: dict[str, DoorAdvice]
    mode: str

    @property
    def headline(self) -> HallView:
        return max(self.halls, key=lambda h: h.share)

    @property
    def advice(self) -> str:
        """Text for one shared (hallway) screen. A near-even split means both
        halls are fine; saying "Go to A" there would be noise that costs trust."""
        head = self.headline
        if head.share < 0.6:
            return "Both halls OK, go to either"
        return f"Go to {head.name}"

    def hall(self, mess_id: str) -> HallView:
        return next(h for h in self.halls if h.mess_id == mess_id)


class Engine:
    def __init__(self, cfg: AppConfig, policy: Policy = Policy.EQUILIBRIUM):
        self.cfg = cfg
        self.policy = policy
        e = cfg.engine
        self._est = {m.id: MessEstimator(e.occupancy_window_min * 60, e.rate_window_min * 60) for m in cfg.messes}
        self._trays = {(m.id, item): (FoodState.OK, -1e9) for m in cfg.messes for item in m.items}
        self._fresh_since = {m.id: -1e9 for m in cfg.messes}
        self.kitchen_log: deque[FoodSignal] = deque(maxlen=500)
        self._dedupe = Deduplicator()
        self._shares: dict[str, float] | None = None
        self._door: dict[str, tuple[str | None, float]] = {m.id: (None, 0.0) for m in cfg.messes}
        self._last_route_ts: float | None = None
        # Where students go by habit. Needed by door screens; a replayed log sets it from real counts.
        self.natural = dict(e.natural_share) or {m.id: 1 / len(cfg.messes) for m in cfg.messes}
        self.now = 0.0

    @property
    def doors_mode(self) -> bool:
        return self.cfg.layout.mode == "doors"

    def _walk_s(self, m: MessConfig) -> float:
        return 0.0 if self.doors_mode else m.walk_time_s

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
        """A kitchen tap. item=None means the main tray, or every tray for "refilled"."""
        m = self.cfg.mess(sig.mess_id)
        items = m.items if (sig.item is None and sig.state is FoodState.OK) else [sig.item or m.items[0]]
        was_short = any(self.tray_state(m.id, i, sig.ts)[0] is not FoodState.OK for i in items)
        for item in items:
            if (m.id, item) in self._trays:
                self._trays[(m.id, item)] = (sig.state, sig.ts)
        if sig.state is FoodState.OK and was_short:
            self._fresh_since[m.id] = sig.ts
        self.kitchen_log.append(sig)

    def tray_state(self, mess_id: str, item: str, now: float) -> tuple[FoodState, float]:
        """One tray's state, with stale taps expired. Staff forget to tap
        "refilled"; without expiry one missed tap would keep a hall marked
        empty and send everyone to the other hall for the rest of the meal."""
        state, since = self._trays[(mess_id, item)]
        age_min = (now - since) / 60.0
        e = self.cfg.engine
        if state is FoodState.OUT and age_min > self.cfg.mess(mess_id).food_refill_time_min + e.food_out_grace_min:
            return FoodState.OK, since
        if state is FoodState.LOW and age_min > e.food_low_expiry_min:
            return FoodState.OK, since
        return state, since

    def food_state(self, mess_id: str, now: float) -> tuple[FoodState, float]:
        """Whole-hall state: the worst tray. Only the main tray running out stops
        service; any other tray being out just slows it, so it counts as LOW."""
        m = self.cfg.mess(mess_id)
        worst, since = FoodState.OK, 0.0
        for idx, item in enumerate(m.items):
            st, ts = self.tray_state(mess_id, item, now)
            if st is FoodState.OUT and idx > 0:
                st = FoodState.LOW
            if _SEVERITY[st] > _SEVERITY[worst]:
                worst, since = st, ts
        return worst, since

    def trays(self, mess_id: str, now: float) -> list[tuple[str, FoodState, float]]:
        return [(item, *self.tray_state(mess_id, item, now)) for item in self.cfg.mess(mess_id).items]

    # ---- update -----------------------------------------------------------
    def update(self, now: float) -> None:
        self.now = now
        for m in self.cfg.messes:
            cap = 0.0 if self.food_state(m.id, now)[0] is FoodState.OUT else m.capacity_per_min
            self._est[m.id].advance(now, cap)
        due = self._last_route_ts is None or now - self._last_route_ts >= self.cfg.engine.routing_update_s
        if due:
            self._route(now)
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

    def _route(self, now: float) -> None:
        e, messes = self.cfg.engine, self.cfg.messes
        states = {m.id: self._state(m, now) for m in messes}
        rates = {m.id: self._est[m.id].arrival_rate_per_min(now) for m in messes}
        if self.policy is Policy.NONE:
            self._shares = {m.id: 1 / len(messes) for m in messes}
            return
        waits_now = {m.id: predict_wait(m, e, states[m.id], rates[m.id], self._walk_s(m)).total for m in messes}
        if self.policy is Policy.GREEDY:
            target = routing.greedy_split(waits_now)
        else:
            fns = {m.id: (lambda lam, m=m: predict_wait(m, e, states[m.id], lam, self._walk_s(m)).total) for m in messes}
            target = routing.equilibrium_split(fns, sum(rates.values()))

        if self.doors_mode:
            self._shares = target
            lay = self.cfg.layout
            new = routing.door_switch_probs(
                target, self.natural, e.assumed_compliance, waits_now, lay.switch_walk_s / 60, lay.min_saving_min
            )
            a = 1.0  # no smoothing at doors: the min-saving rule already keeps advice stable (smoothing measured worse)
            for door, (dest, p) in new.items():
                # Ramp switch advice up smoothly, but drop it at once when it stops
                # paying off: never ask someone to walk for a saving that isn't there.
                old_dest, old_p = self._door[door]
                if dest is not None:
                    p = a * p + (1 - a) * (old_p if old_dest == dest else 0.0)
                self._door[door] = (dest, p)
            return

        advised = routing.compensate_for_noncompliance(target, e.natural_share, e.assumed_compliance)
        if self.policy is Policy.EQUILIBRIUM:
            open_halls = {i for i, s in states.items() if s.food is not FoodState.OUT}
            advised = routing.apply_floor(advised, e.min_share, open_halls)
            advised = routing.smooth(self._shares, advised, e.routing_smoothing)
        self._shares = advised

    # ---- outputs ----------------------------------------------------------
    def snapshot(self) -> Snapshot:
        e = self.cfg.engine
        now = self.now
        shares = self.shares()
        views = []
        for m in self.cfg.messes:
            st = self._state(m, now)
            rate = self._est[m.id].arrival_rate_per_min(now)
            wb = predict_wait(m, e, st, rate, self._walk_s(m))
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
                    fresh=st.food is FoodState.OK and now - self._fresh_since[m.id] < FRESH_BATCH_MIN * 60,
                    wait=wb,
                    status=status,
                    share=shares[m.id],
                )
            )
        by_id = {v.mess_id: v for v in views}
        walk_min = self.cfg.layout.switch_walk_s / 60
        doors = {}
        for door, (dest, p) in self._door.items():
            saving = by_id[door].wait.wait - (by_id[dest].wait.wait + walk_min) if dest else 0.0
            if dest and saving < self.cfg.layout.min_saving_min:  # waits moved since the last routing update
                dest, p, saving = None, 0.0, 0.0
            doors[door] = DoorAdvice(at=door, go_to=dest, p_switch=p, saving_min=saving)
        return Snapshot(ts=now, halls=tuple(views), doors=doors, mode=self.cfg.layout.mode)

    def shares(self) -> dict[str, float]:
        return dict(self._shares or {m.id: 1 / len(self.cfg.messes) for m in self.cfg.messes})

    def recommend(self, rng: random.Random) -> str:
        """Hallway layout: one student's advice, a random draw from the split."""
        shares = self.shares()
        r, acc = rng.random(), 0.0
        for mess_id, s in shares.items():
            acc += s
            if r < acc:
                return mess_id
        return mess_id

    def recommend_at(self, door: str, rng: random.Random) -> str:
        """Doors layout: advice for one student standing at `door`."""
        dest, p = self._door.get(door, (None, 0.0))
        return dest if dest is not None and rng.random() < p else door

    def scans_last(self, mess_id: str, seconds: float) -> int:
        return self._est[mess_id].count_last(self.now, seconds)
