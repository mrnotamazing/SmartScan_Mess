"""Discrete-time simulation of the halls, with fake students and fake scans.

Ground truth (real queues, real seats, real food stock) lives here. The engine
only receives what the real deployment would: entry scans at each hall and
the mess manager's "running low / out / refilled" taps (sometimes forgotten).

Per hall, the four stages of a visit:
  1. entrance: queue for the face scanner -> scan -> collect a plate
  2. food: queue for a serving station (c stations, food stock with batch
     refills) -> served -> walk the rest of the food line
  3. eat: take a seat (or wait for one) -> eat
  4. dispose of leftovers and the plate -> leave
Waiting = time spent in a queue (scanner, serving station, seat); the rest of
the visit is activity time. Throughput time = door to leaving.
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
    scan_start: float | None = None  # reached the scanner
    scanned_at: float | None = None  # scanned in: the time the biometric log records
    queue_join: float | None = None  # has a plate; joins the serving queue
    service_start: float | None = None  # reached a serving station
    food_at: float | None = None  # has all the food (end of the food line)
    seated_at: float | None = None
    table_left: float | None = None  # finished eating, seat free
    left_at: float | None = None  # disposed of the plate and left

    @property
    def queue_wait_min(self) -> float | None:
        """Minutes spent queueing: for the scanner, a serving station, and a seat."""
        if self.seated_at is None:
            return None
        return ((self.scan_start - self.arrived_at) + (self.service_start - self.queue_join)
                + (self.seated_at - self.food_at)) / 60.0

    @property
    def time_to_food_min(self) -> float | None:
        return None if self.food_at is None else (self.food_at - self.arrived_at) / 60.0

    @property
    def throughput_min(self) -> float | None:
        """Door to leaving: all four stages, queues included."""
        return None if self.left_at is None else (self.left_at - self.arrived_at) / 60.0
    name: str | None = None  # made-up for simulated students; from the log only if privacy.show_names


def _truncated_normal(n: float, t: float, mu: float, sd: float, lo: float, hi: float) -> float:
    """n × the density at t of Normal(mu, sd) cut to [lo, hi]."""
    if t < lo or t > hi:
        return 0.0
    phi = lambda x: 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))  # noqa: E731
    dens = math.exp(-0.5 * ((t - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
    return n * dens / (phi(hi) - phi(lo))


def arrival_rate_per_min(slot: MealSlot, t_min: float) -> float:
    """Arrivals per minute at t_min after opening, adding up to expected_students:
    one curve per department (from its lunch break), else one bell curve."""
    if t_min < 0 or t_min > slot.duration_min:
        return 0.0
    if slot.groups:
        return sum(_truncated_normal(n, t_min, a + slot.lag_mean_min, slot.lag_sd_min, max(a, 0), min(b, slot.duration_min))
                   for _name, n, a, b in slot.cohorts())
    return _truncated_normal(slot.expected_students, t_min, slot.peak_offset_min, slot.spread_min, 0, slot.duration_min)


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
        self._plating: list[tuple[float, int, Student]] = []  # scanned, collecting a plate
        self.peak_scan_queue = 0
        self.queue: deque[Student] = deque()
        self.free_at = [0.0] * cfg.counters
        self.serving: list[tuple[float, int, Student]] = []  # (has all food, tiebreak, student)
        self.seated: list[tuple[float, int, Student]] = []  # (finishes eating, tiebreak, student)
        self._disposing: list[float] = []  # heap of leave times (after the plate is returned)
        self.seat_queue: deque[Student] = deque()
        self.stock = cfg.food_batch
        self.refill_eta: float | None = None
        self.out_since: float | None = None
        self.outages = 0
        self.outage_minutes = 0.0
        self.peak_queue = 0
        self._tie = 0
        self.busy_s: dict[int, float] = {}  # station-seconds busy, per 10-min bin
        self.joins: dict[int, int] = {}  # students joining the serving queue, per 10-min bin

    # The manager only sometimes taps the food-status page.
    def _tap(self, ts: float, state: FoodState) -> None:
        if self.rng.random() < self.sim.staff_signal_prob:
            self.signal(FoodSignal(ts, self.cfg.id, state))

    def _service_time(self) -> float:
        mean_s = 60.0 / self.cfg.service_rate_per_counter_per_min
        cv = self.sim.service_cv
        k = 1 / (cv * cv)
        return self.rng.gammavariate(k, mean_s / k)

    def _uniform_s(self, rng_range: tuple[float, float], scale: float = 1.0) -> float:
        return scale * self.rng.uniform(*rng_range)

    def _lead_time_s(self) -> float:
        """Minutes from the call to the kitchen until the refill arrives, in seconds."""
        if self.rng.random() < self.cfg.food_ready_prob:
            return 60.0 * self.rng.uniform(*self.cfg.food_ready_refill_min)  # already made: just sent
        return 60.0 * self.cfg.food_refill_time_min  # has to be made, then sent

    def _refill(self) -> None:
        eta = self.refill_eta
        self.stock += self.cfg.food_batch
        self.refill_eta = None
        if self.out_since is not None:
            # Nobody was served during the run-out: stations restart when the food arrives.
            self.free_at = [max(f, eta) for f in self.free_at]
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
            self.refill_eta = now + self._lead_time_s()
        self.signal(FoodSignal(now, self.cfg.id, FoodState.OUT))  # demo: staff always tap this one

    def true_in_hall(self) -> int:
        """People inside (scanned in): what the engine tries to estimate."""
        return (len(self._plating) + len(self.queue) + len(self.serving) + len(self.seated)
                + len(self.seat_queue) + len(self._disposing))

    def busy(self) -> bool:
        """Anyone still between the door and the exit."""
        return bool(self.scan_queue or self._scanning or self._plating or self.queue or self.serving
                    or self.seat_queue or self.seated or self._disposing)

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
            s.scan_start = start
            finish = start + self._scan_time()
            self.scan_free_at[k] = finish
            self._tie += 1
            heapq.heappush(self._scanning, (finish, self._tie, s))
        while self._scanning and self._scanning[0][0] <= t1:
            finish, _, s = heapq.heappop(self._scanning)
            s.scanned_at = finish
            self.on_scan(s)
            s.queue_join = finish + self._uniform_s(self.sim.plate_pickup_s)
            self._tie += 1
            heapq.heappush(self._plating, (s.queue_join, self._tie, s))
        self.peak_scan_queue = max(self.peak_scan_queue, self.outside_queue())
        while self._plating and self._plating[0][0] <= t1:
            _, _, s = heapq.heappop(self._plating)
            self.queue.append(s)
            b = int(s.queue_join // 600)
            self.joins[b] = self.joins.get(b, 0) + 1

        # 1. Serving, one service start at a time on the earliest-free counter.
        while True:
            k = min(range(len(self.free_at)), key=self.free_at.__getitem__)
            start = max(self.free_at[k], self.queue[0].queue_join) if self.queue else math.inf
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
            b = int(start // 600)
            self.busy_s[b] = self.busy_s.get(b, 0.0) + (finish - start)
            s.food_at = finish + self._uniform_s(self.sim.food_line_s)
            self._tie += 1
            heapq.heappush(self.serving, (s.food_at, self._tie, s))
            if self.stock <= self.cfg.food_refill_trigger and self.refill_eta is None:
                self.refill_eta = start + self._lead_time_s()
                self._tap(start, FoodState.LOW)
            if self.stock == 0:
                self.out_since = start
                self.outages += 1
                self._tap(start, FoodState.OUT)

        # 2. Seating: merge "finished serving" and "left seat" events in time order.
        while True:
            next_done = self.serving[0][0] if self.serving else math.inf
            next_leave = self.seated[0][0] if self.seated else math.inf
            t = min(next_done, next_leave)
            if t > t1:
                break
            if next_leave <= next_done:
                _, _, done = heapq.heappop(self.seated)
                heapq.heappush(self._disposing, done.left_at)
                if self.seat_queue:
                    self._sit(self.seat_queue.popleft(), t)
            else:
                _, _, s = heapq.heappop(self.serving)
                if len(self.seated) < self.cfg.seats:
                    self._sit(s, t)
                else:
                    self.seat_queue.append(s)
        while self._disposing and self._disposing[0] <= t1:
            heapq.heappop(self._disposing)
        self.peak_queue = max(self.peak_queue, len(self.queue))

    def _sit(self, s: Student, t: float) -> None:
        s.seated_at = t
        s.table_left = t + self._uniform_s(self.sim.eat_min, 60.0)
        s.left_at = s.table_left + self._uniform_s(self.sim.dispose_min, 60.0)
        self._tie += 1
        heapq.heappush(self.seated, (s.table_left, self._tie, s))


@dataclass
class SimResult:
    policy: str
    compliance: float
    seed: int
    students: int
    mean_wait_min: float  # minutes queueing: scanner + serving station + seat
    p90_wait_min: float
    mean_trip_min: float  # decision point -> has food (includes any walk to the other mess)
    peak_queue: int  # largest serving queue in any hall
    outages: int  # food run-out incidents
    outage_minutes: float
    compliance_rate: float  # of students advised to go somewhere new, share who did (nan without advice)
    switch_rate: float  # went somewhere other than their habit
    occupancy_mae: float  # |estimated - true people in hall|, averaged
    peak_scan_queue: int = 0  # largest queue outside, waiting to scan in (invisible to the system)
    mean_throughput_min: float = 0.0  # door -> leaving, all four stages
    p90_throughput_min: float = 0.0
    mean_total_min: float = 0.0  # decision point -> leaving (throughput + any walk)
    quiet_throughput_min: float = 0.0  # throughput for students arriving in the first 30 minutes
    peak_throughput_min: float = 0.0  # throughput for students arriving within 15 min of the peak
    redirected: int = 0  # students who walked to the other mess because of a screen
    unsuccessful_rate: float = math.nan  # of those, share who waited longer than students who stayed
    util: dict[str, float] = field(default_factory=dict)  # stations busy, share of 11:30-14:30
    peak_load: dict[str, float] = field(default_factory=dict)  # busiest 30 min: arrivals / capacity
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
        use_food: bool = True,
    ):
        """`use_food=False`: the engine never hears the manager's food taps (the
        "queue information only" scenario). `arrivals`: replay mode. (seconds since slot start, mess id[, name]) for
        each scan in a real log. The mess in the log is taken as where that student
        was heading (their habit); policies may then redirect them."""
        self.cfg, self.slot, self.policy, self.seed = cfg, slot, policy, seed
        self.use_food = use_food
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
        self._peak = slot.peak_min()
        self._hard_stop = self.end + 90 * 60
        self._n_events = 0
        self.engine.update(0.0)

    @property
    def finished(self) -> bool:
        if self.t >= self._hard_stop:
            return True
        # Done once everyone has food and a seat (eating and leaving don't change any result).
        return self.t >= self.end and not self._replay and not self._in_transit and all(
            not (h.scan_queue or h._scanning or h._plating or h.queue or h.serving or h.seat_queue)
            for h in self.halls.values()
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
        # The engine sees only polled scans and the manager's food-status taps.
        engine.ingest(self.scanner.poll())
        if self.use_food:
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
        if self.use_food:
            for sig in self._signals:  # the manager's "out" tap reaches the engine immediately
                self.engine.food_signal(sig)
        self._signals.clear()

    def result(self, snapshots: list[Snapshot] | None = None, keep_students: bool = False) -> SimResult:
        students = self.students
        done = [s for s in students if s.seated_at is not None]
        waits = sorted(s.queue_wait_min for s in done)
        through = sorted(s.throughput_min for s in done)
        redirected = [s for s in students if s.advised is not None and s.advised != s.habit]
        moved = [s for s in done if s.hall != s.habit]
        halls = self.halls
        bins = max(1, math.ceil(self.slot.duration_min / 10))
        util, peak = {}, {}
        for m in self.cfg.messes:
            h = halls[m.id]
            util[m.id] = sum(h.busy_s.get(b, 0.0) for b in range(bins)) / (m.counters * 600 * bins)
            loads = [sum(h.joins.get(b + i, 0) for i in range(3)) / (m.capacity_per_min * 30) for b in range(bins - 2)]
            peak[m.id] = max(loads) if loads else 0.0
        return SimResult(
            policy=self.policy.value,
            compliance=self.compliance if self.policy is not Policy.NONE else 0.0,
            seed=self.seed,
            students=len(students),
            mean_wait_min=mean(waits) if waits else 0.0,
            p90_wait_min=waits[int(0.9 * (len(waits) - 1))] if waits else 0.0,
            mean_trip_min=mean((s.food_at - s.decided_at) / 60 for s in done) if done else 0.0,
            mean_throughput_min=mean(through) if through else 0.0,
            p90_throughput_min=through[int(0.9 * (len(through) - 1))] if through else 0.0,
            mean_total_min=mean((s.left_at - s.decided_at) / 60 for s in done) if done else 0.0,
            quiet_throughput_min=_mean_or_0(s.throughput_min for s in done if s.queue_wait_min < 1.0),
            peak_throughput_min=_mean_or_0(s.throughput_min for s in done
                                           if abs(s.arrived_at / 60 - self._peak) <= 15),
            redirected=len(moved),
            unsuccessful_rate=_unsuccessful(moved, done, self.cfg.layout.switch_walk_s / 60),
            util=util,
            peak_load=peak,
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


def _mean_or_0(xs) -> float:
    xs = list(xs)
    return mean(xs) if xs else 0.0


def _unsuccessful(moved: list[Student], done: list[Student], walk_min: float) -> float:
    """Share of redirected students who did worse than staying: their queue wait plus
    the walk exceeded the average wait of students who stayed at the mess they left
    and arrived within 2 minutes of them."""
    if not moved:
        return math.nan
    stayers: dict[str, list[tuple[float, float]]] = {}
    for s in done:
        if s.hall == s.habit:
            stayers.setdefault(s.hall, []).append((s.arrived_at, s.queue_wait_min))
    for v in stayers.values():
        v.sort()
    worse = counted = 0
    for s in moved:
        near = [w for t, w in stayers.get(s.habit, []) if abs(t - s.arrived_at) <= 120]
        if near:
            counted += 1
            worse += s.queue_wait_min + walk_min > mean(near)
    return worse / counted if counted else math.nan


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
    use_food: bool = True,
) -> SimResult:
    sim = Simulation(cfg, slot, policy, compliance, seed, arrivals, use_food=use_food)
    if natural:
        sim.engine.natural = natural
    snapshots: list[Snapshot] = []
    while not sim.finished:
        sim.step()
        if snapshot_every_s and int(sim.t) % int(snapshot_every_s) == 0 and sim.t <= sim.end:
            snapshots.append(sim.engine.snapshot())
    return sim.result(snapshots, keep_students)
