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
from .names import NameMaker
from .privacy import pseudonymise


@dataclass
class Student:
    key: str
    decided_at: float
    habit: str
    advised: str | None
    hall: str
    arrived_at: float = 0.0  # reached the mess door (joins the scanner queue)
    scanned_at: float | None = None  # scanned in: the time the biometric log records
    service_start: float | None = None
    seated_at: float | None = None
    left_at: float | None = None
    name: str | None = None  # made-up for simulated students; from the log only if privacy.show_names


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
    def __init__(self, cfg: MessConfig, sim: SimConfig, rng: random.Random, signal, on_scan=None):
        self.cfg, self.sim, self.rng, self.signal = cfg, sim, rng, signal
        self.on_scan = on_scan or (lambda s: None)
        # Entrance: a queue for the face scanner(s). It is outside the hall and the
        # system cannot see it: a student only exists for the engine once scanned.
        self.scan_queue: deque[Student] = deque()
        self.scan_free_at = [0.0] * cfg.scanners
        self._scanning: list[tuple[float, int, Student]] = []
        self.peak_scan_queue = 0
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

    def force_run_out(self, now: float) -> None:
        if self.stock <= 0:
            return
        self.stock = 0
        self.out_since = now
        self.outages += 1
        if self.refill_eta is None:
            self.refill_eta = now + self.cfg.food_refill_time_min * 60
        self.signal(FoodSignal(now, self.cfg.id, FoodState.OUT))  # demo: staff always tap this one

    def true_in_hall(self) -> int:
        """People inside (scanned in): what the engine tries to estimate."""
        return len(self.queue) + len(self.serving) + len(self.seated) + len(self.seat_queue)

    def outside_queue(self) -> int:
        return len(self.scan_queue) + len(self._scanning)

    def _scan_time(self) -> float:
        k = 1 / 0.3**2  # scans are fairly regular (cv 0.3)
        return self.rng.gammavariate(k, self.cfg.scan_time_s / k)

    def advance(self, t1: float) -> None:
        # 0. Entrance scanner(s): one student at a time per scanner.
        while self.scan_queue:
            k = min(range(len(self.scan_free_at)), key=self.scan_free_at.__getitem__)
            start = max(self.scan_free_at[k], self.scan_queue[0].arrived_at)
            if start >= t1:
                break
            s = self.scan_queue.popleft()
            finish = start + self._scan_time()
            self.scan_free_at[k] = finish
            self._tie += 1
            heapq.heappush(self._scanning, (finish, self._tie, s))
        while self._scanning and self._scanning[0][0] <= t1:
            finish, _, s = heapq.heappop(self._scanning)
            s.scanned_at = finish
            self.queue.append(s)
            self.on_scan(s)
        self.peak_scan_queue = max(self.peak_scan_queue, self.outside_queue())

        # 1. Serving, one service start at a time on the earliest-free counter.
        while True:
            k = min(range(len(self.free_at)), key=self.free_at.__getitem__)
            start = max(self.free_at[k], self.queue[0].scanned_at) if self.queue else math.inf
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
        s.left_at = t + self._stay_time()
        heapq.heappush(self.seated, s.left_at)


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
    compliance_rate: float  # of students advised to go somewhere new, share who did (nan without advice)
    switch_rate: float  # went somewhere other than their habit
    occupancy_mae: float  # |estimated - true people in hall|, averaged
    peak_scan_queue: int = 0  # largest queue outside, waiting to scan in (invisible to the system)
    hall_counts: dict[str, int] = field(default_factory=dict)
    unfinished: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)
    students_list: list[Student] = field(default_factory=list, repr=False)


class Simulation:
    """One simulated meal, advanced step by step (the live demo drives this;
    `simulate` runs it to the end). Arrivals and habits use their own random
    stream, so two policies run with the same seed see identical students."""

    def __init__(
        self,
        cfg: AppConfig,
        slot: MealSlot,
        policy: Policy,
        compliance: float | None = None,
        seed: int = 0,
        arrivals: list[tuple] | None = None,
    ):
        """`arrivals`: replay mode. (seconds since slot start, mess id[, name]) for
        each scan in a real log. The mess in the log is taken as where that student
        was heading (their habit); policies may then redirect them."""
        self.cfg, self.slot, self.policy, self.seed = cfg, slot, policy, seed
        self._replay = deque(sorted(arrivals, key=lambda a: a[0])) if arrivals is not None else None
        self._names = NameMaker(seed)
        sim = cfg.simulation
        self.compliance = sim.compliance if compliance is None else compliance
        self._arrivals = random.Random(seed)
        self._choices = random.Random(f"choices-{seed}")
        self._salt = self._arrivals.randbytes(16)
        self.engine = Engine(cfg, policy)
        self.scanner = SimulatedScanner()
        self._signals: list[FoodSignal] = []
        hall_seed = random.Random(f"halls-{seed}")
        self.halls = {
            m.id: Hall(m, sim, random.Random(hall_seed.random()), self._signals.append, self._emit_scan) for m in cfg.messes
        }
        self._walk = {m.id: m.walk_time_s for m in cfg.messes}
        self._doors = cfg.layout.mode == "doors"
        self._habit_ids, self._habit_w = list(sim.habit_share), list(sim.habit_share.values())
        self.students: list[Student] = []
        self._in_transit: list[tuple[float, int, Student]] = []
        self._abs_err: list[float] = []
        self.t = 0.0
        self.end = slot.duration_min * 60
        self._hard_stop = self.end + 90 * 60
        self._n_events = 0
        self.engine.update(0.0)

    @property
    def finished(self) -> bool:
        if self.t >= self._hard_stop:
            return True
        return self.t >= self.end and not self._replay and not self._in_transit and all(
            not h.queue and not h.serving and not h.seat_queue and not h.outside_queue() for h in self.halls.values()
        )

    def _emit_scan(self, s: Student) -> None:
        self._n_events += 1
        self.scanner.emit(ScanEvent(s.scanned_at, s.hall, s.key, event_id=f"e{self._n_events}"))

    def step(self) -> None:
        dt = self.cfg.simulation.step_s
        t, t1 = self.t, self.t + dt
        engine = self.engine
        # New students reach a screen and pick a hall. Doors layout: the screen is
        # outside the mess they were heading to. Hallway: one screen before the fork.
        if self._replay is not None:
            new = []
            while self._replay and self._replay[0][0] < t1:
                new.append(self._replay.popleft())
        else:
            n = poisson(self._arrivals, arrival_rate_per_min(self.slot, (t + dt / 2) / 60) * dt / 60)
            new = [
                (t + self._arrivals.random() * dt, self._arrivals.choices(self._habit_ids, self._habit_w)[0], self._names.next())
                for _ in range(n)
            ]
        for ts, habit, *label in new:
            follows = self._arrivals.random() < self.compliance
            if self.policy is Policy.NONE:
                advised = None
            elif self._doors:
                advised = engine.recommend_at(habit, self._choices)
            else:
                advised = engine.recommend(self._choices)
            hall = advised if advised is not None and follows else habit
            if self._doors:
                decided, arrive = ts, ts + (self.cfg.layout.switch_walk_s if hall != habit else 0.0)
            else:  # in a replayed log the scan time is the arrival; the decision came a walk earlier
                decided = ts - self._walk[habit] if self._replay is not None else ts
                arrive = decided + self._walk[hall]
            s = Student(pseudonymise(f"S{len(self.students)}", self._salt), decided, habit, advised, hall)
            s.name = label[0] if label else None
            self.students.append(s)
            s.arrived_at = max(arrive, t)
            heapq.heappush(self._in_transit, (s.arrived_at, len(self.students), s))
        # Arrivals at the mess door: queue for the scanner; the hall emits the scan.
        while self._in_transit and self._in_transit[0][0] <= t1:
            _, _, s = heapq.heappop(self._in_transit)
            self.halls[s.hall].scan_queue.append(s)
        for h in self.halls.values():
            h.advance(t1)
        # The engine sees only polled scans and kitchen taps.
        engine.ingest(self.scanner.poll())
        for sig in self._signals:
            engine.food_signal(sig)
        self._signals.clear()
        engine.update(t1)
        if t1 <= self.end:
            for m in self.cfg.messes:
                truth = self.halls[m.id].true_in_hall()
                self._abs_err.append(abs(engine._est[m.id].occupancy(t1) - truth))
        self.t = t1

    def force_run_out(self, mess_id: str) -> None:
        """Demo control: the hall's food runs out right now."""
        self.halls[mess_id].force_run_out(self.t)
        for sig in self._signals:  # the kitchen's "out" tap reaches the engine immediately
            self.engine.food_signal(sig)
        self._signals.clear()

    def result(self, snapshots: list[Snapshot] | None = None, keep_students: bool = False) -> SimResult:
        students = self.students
        done = [s for s in students if s.seated_at is not None]
        waits = sorted((s.seated_at - s.arrived_at) / 60 for s in done)
        redirected = [s for s in students if s.advised is not None and s.advised != s.habit]
        halls = self.halls
        return SimResult(
            policy=self.policy.value,
            compliance=self.compliance if self.policy is not Policy.NONE else 0.0,
            seed=self.seed,
            students=len(students),
            mean_wait_min=mean(waits) if waits else 0.0,
            p90_wait_min=waits[int(0.9 * (len(waits) - 1))] if waits else 0.0,
            mean_trip_min=mean((s.seated_at - s.decided_at) / 60 for s in done) if done else 0.0,
            peak_queue=max(h.peak_queue for h in halls.values()),
            peak_scan_queue=max(h.peak_scan_queue for h in halls.values()),
            outages=sum(h.outages for h in halls.values()),
            outage_minutes=sum(h.outage_minutes for h in halls.values()),
            compliance_rate=(sum(s.hall == s.advised for s in redirected) / len(redirected)) if redirected else math.nan,
            switch_rate=sum(s.hall != s.habit for s in students) / max(1, len(students)),
            occupancy_mae=mean(self._abs_err) if self._abs_err else 0.0,
            hall_counts={m.id: sum(s.hall == m.id for s in students) for m in self.cfg.messes},
            unfinished=len(students) - len(done),
            snapshots=snapshots or [],
            students_list=list(students) if keep_students else [],
        )


def simulate(
    cfg: AppConfig,
    slot: MealSlot,
    policy: Policy,
    compliance: float | None = None,
    seed: int = 0,
    snapshot_every_s: float | None = None,
    arrivals: list[tuple[float, str]] | None = None,
    keep_students: bool = False,
    natural: dict[str, float] | None = None,
) -> SimResult:
    sim = Simulation(cfg, slot, policy, compliance, seed, arrivals)
    if natural:
        sim.engine.natural = natural
    snapshots: list[Snapshot] = []
    while not sim.finished:
        sim.step()
        if snapshot_every_s and int(sim.t) % int(snapshot_every_s) == 0 and sim.t <= sim.end:
            snapshots.append(sim.engine.snapshot())
    return sim.result(snapshots, keep_students)
