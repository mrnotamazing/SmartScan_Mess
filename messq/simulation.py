"""Discrete-time simulation of the halls, with fake students and fake scans.

Ground truth (real queues, real seats, real food stock) lives here. The engine
only receives what the real deployment would: entry scans at each hall and
kitchen "tray low / out / refilled" taps (which staff sometimes forget).

Per hall: arrival -> scan at entrance -> serving queue (c counters, food stock
with batch refills) -> seat (or wait for one) -> eat -> leave.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass, field
from statistics import mean

from .adapters import SimulatedScanner
from .config import AppConfig, MealSlot, MessConfig, SimConfig
from .engine import Engine, Policy, Snapshot
from .events import FoodSignal, FoodState, ScanEvent
from .privacy import pseudonymise


@dataclass
class Student:
    key: str
    decided_at: float
    habit: str
    advised: str | None
    hall: str
    arrived_at: float = 0.0
    service_start: float | None = None
    seated_at: float | None = None


def arrival_rate_per_min(slot: MealSlot, t_min: float) -> float:
    """Truncated-normal arrival profile scaled to expected_students over the slot."""
    if t_min < 0 or t_min > slot.duration_min:
        return 0.0
    mu, sd, d = slot.peak_offset_min, slot.spread_min, slot.duration_min
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    z = phi((d - mu) / sd) - phi(-mu / sd)
    dens = math.exp(-0.5 * ((t_min - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
    return slot.expected_students * dens / z


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:  # normal approximation for large means
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class Hall:
    def __init__(self, cfg: MessConfig, sim: SimConfig, rng: random.Random, signal):
        self.cfg, self.sim, self.rng, self.signal = cfg, sim, rng, signal
        self.queue: deque[Student] = deque()
        self.free_at = [0.0] * cfg.counters
        self.serving: list[tuple[float, int, Student]] = []  # (finish, tiebreak, student)
        self.seated: list[float] = []  # heap of leave times
        self.seat_queue: deque[Student] = deque()
        self.stock = cfg.food_batch
        self.refill_eta: float | None = None
        self.out_since: float | None = None
        self.outages = 0
        self.outage_minutes = 0.0
        self.peak_queue = 0
        self._tie = 0
        sigma2 = math.log(1 + (sim.stay_sd_min / sim.stay_mean_min) ** 2)
        self._stay_mu, self._stay_sigma = math.log(sim.stay_mean_min) - sigma2 / 2, math.sqrt(sigma2)

    # Staff only sometimes tap the kitchen page.
    def _tap(self, ts: float, state: FoodState) -> None:
        if self.rng.random() < self.sim.staff_signal_prob:
            self.signal(FoodSignal(ts, self.cfg.id, state))

    def _service_time(self) -> float:
        mean_s = 60.0 / self.cfg.service_rate_per_counter_per_min
        cv = self.sim.service_cv
        k = 1 / (cv * cv)
        return self.rng.gammavariate(k, mean_s / k)

    def _stay_time(self) -> float:
        return 60.0 * self.rng.lognormvariate(self._stay_mu, self._stay_sigma)

    def _refill(self) -> None:
        eta = self.refill_eta
        self.stock += self.cfg.food_batch
        self.refill_eta = None
        if self.out_since is not None:
            self.outage_minutes += (eta - self.out_since) / 60.0
            self.out_since = None
        self._tap(eta, FoodState.OK)

    def true_in_hall(self) -> int:
        return len(self.queue) + len(self.serving) + len(self.seated) + len(self.seat_queue)

    def advance(self, t1: float) -> None:
        # 1. Serving, one service start at a time on the earliest-free counter.
        while True:
            k = min(range(len(self.free_at)), key=self.free_at.__getitem__)
            start = max(self.free_at[k], self.queue[0].arrived_at) if self.queue else math.inf
            if self.stock <= 0:
                start = max(start, self.refill_eta if self.refill_eta is not None else math.inf)
            if self.refill_eta is not None and self.refill_eta <= min(start, t1):
                self._refill()
                continue
            if start >= t1:
                break
            s = self.queue.popleft()
            s.service_start = start
            self.stock -= 1
            finish = start + self._service_time()
            self.free_at[k] = finish
            self._tie += 1
            heapq.heappush(self.serving, (finish, self._tie, s))
            if self.stock <= self.cfg.food_refill_trigger and self.refill_eta is None:
                self.refill_eta = start + self.cfg.food_refill_time_min * 60
                self._tap(start, FoodState.LOW)
            if self.stock == 0:
                self.out_since = start
                self.outages += 1
                self._tap(start, FoodState.OUT)

        # 2. Seating: merge "finished serving" and "left seat" events in time order.
        while True:
            next_done = self.serving[0][0] if self.serving else math.inf
            next_leave = self.seated[0] if self.seated else math.inf
            t = min(next_done, next_leave)
            if t > t1:
                break
            if next_leave <= next_done:
                heapq.heappop(self.seated)
                if self.seat_queue:
                    self._sit(self.seat_queue.popleft(), t)
            else:
                _, _, s = heapq.heappop(self.serving)
                if len(self.seated) < self.cfg.seats:
                    self._sit(s, t)
                else:
                    self.seat_queue.append(s)
        self.peak_queue = max(self.peak_queue, len(self.queue))

    def _sit(self, s: Student, t: float) -> None:
        s.seated_at = t
        heapq.heappush(self.seated, t + self._stay_time())


@dataclass
class SimResult:
    policy: str
    compliance: float
    seed: int
    students: int
    mean_wait_min: float  # scan at hall -> seated with food
    p90_wait_min: float
    mean_trip_min: float  # decision point -> seated (includes walk)
    peak_queue: int  # largest serving queue in any hall
    outages: int  # food run-out incidents
    outage_minutes: float
    compliance_rate: float  # went where advised (nan without advice)
    switch_rate: float  # went somewhere other than their habit
    occupancy_mae: float  # |estimated - true people in hall|, averaged
    hall_counts: dict[str, int] = field(default_factory=dict)
    unfinished: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)


def simulate(
    cfg: AppConfig,
    slot: MealSlot,
    policy: Policy,
    compliance: float | None = None,
    seed: int = 0,
    snapshot_every_s: float | None = None,
) -> SimResult:
    sim = cfg.simulation
    compliance = sim.compliance if compliance is None else compliance
    rng = random.Random(seed)
    salt = rng.randbytes(16)
    engine = Engine(cfg, policy)
    scanner = SimulatedScanner()
    signals: list[FoodSignal] = []
    halls = {m.id: Hall(m, sim, random.Random(rng.random()), signals.append) for m in cfg.messes}
    walk = {m.id: m.walk_time_s for m in cfg.messes}
    habit_ids, habit_w = list(sim.habit_share), list(sim.habit_share.values())

    students: list[Student] = []
    in_transit: list[tuple[float, int, Student]] = []
    abs_err: list[float] = []
    snapshots: list[Snapshot] = []
    dt = sim.step_s
    end = slot.duration_min * 60
    hard_stop = end + 90 * 60
    t, n_events = 0.0, 0
    engine.update(0.0)
    while t < hard_stop:
        t1 = t + dt
        # New students reach the decision point (screen) and pick a hall.
        for _ in range(poisson(rng, arrival_rate_per_min(slot, (t + dt / 2) / 60) * dt / 60)):
            ts = t + rng.random() * dt
            habit = rng.choices(habit_ids, habit_w)[0]
            advised = None if policy is Policy.NONE else engine.recommend(rng)
            hall = advised if advised is not None and rng.random() < compliance else habit
            s = Student(pseudonymise(f"S{len(students)}", salt), ts, habit, advised, hall)
            students.append(s)
            s.arrived_at = ts + walk[hall]
            heapq.heappush(in_transit, (s.arrived_at, len(students), s))
        # Arrivals at halls: scanned at the entrance, then join the serving queue.
        while in_transit and in_transit[0][0] <= t1:
            _, _, s = heapq.heappop(in_transit)
            n_events += 1
            scanner.emit(ScanEvent(s.arrived_at, s.hall, s.key, event_id=f"e{n_events}"))
            halls[s.hall].queue.append(s)
        for h in halls.values():
            h.advance(t1)
        # The engine sees only polled scans and kitchen taps.
        engine.ingest(scanner.poll())
        for sig in signals:
            engine.food_signal(sig)
        signals.clear()
        engine.update(t1)
        if t1 <= end:
            for m in cfg.messes:
                truth = halls[m.id].true_in_hall()
                abs_err.append(abs(engine._est[m.id].occupancy(t1) - truth))
        if snapshot_every_s and int(t1) % int(snapshot_every_s) == 0 and t1 <= end:
            snapshots.append(engine.snapshot())
        t = t1
        if t >= end and not in_transit and all(not h.queue and not h.serving and not h.seat_queue for h in halls.values()):
            break

    done = [s for s in students if s.seated_at is not None]
    waits = sorted((s.seated_at - s.arrived_at) / 60 for s in done)
    advised = [s for s in students if s.advised is not None]
    return SimResult(
        policy=policy.value,
        compliance=compliance if policy is not Policy.NONE else 0.0,
        seed=seed,
        students=len(students),
        mean_wait_min=mean(waits) if waits else 0.0,
        p90_wait_min=waits[int(0.9 * (len(waits) - 1))] if waits else 0.0,
        mean_trip_min=mean((s.seated_at - s.decided_at) / 60 for s in done) if done else 0.0,
        peak_queue=max(h.peak_queue for h in halls.values()),
        outages=sum(h.outages for h in halls.values()),
        outage_minutes=sum(h.outage_minutes for h in halls.values()),
        compliance_rate=(sum(s.hall == s.advised for s in advised) / len(advised)) if advised else math.nan,
        switch_rate=sum(s.hall != s.habit for s in students) / max(1, len(students)),
        occupancy_mae=mean(abs_err) if abs_err else 0.0,
        hall_counts={m.id: sum(s.hall == m.id for s in students) for m in cfg.messes},
        unfinished=len(students) - len(done),
        snapshots=snapshots,
    )
