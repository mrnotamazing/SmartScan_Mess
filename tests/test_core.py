import dataclasses
import math
import random
from statistics import mean

import pytest

from messq.config import load_config
from messq.engine import Engine, Policy, Status
from messq.estimator import Deduplicator, MessEstimator
from messq.events import FoodSignal, FoodState, ScanEvent
from messq.privacy import pseudonymise
from messq.queueing import erlang_c, mmc_wait
from messq.routing import apply_floor, compensate_for_noncompliance, equilibrium_split, greedy_split
from messq.simulation import simulate
from messq.waits import HallState, predict_wait


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ---- queueing --------------------------------------------------------------
def test_mm1_matches_closed_form():
    lam, mu = 3.0, 4.0
    rho = lam / mu
    assert erlang_c(1, rho) == pytest.approx(rho)
    assert mmc_wait(lam, mu, 1) == pytest.approx(rho / (mu - lam))


def test_mm2_textbook_value():
    # c=2, lambda=1, mu=1: C = 1/3, Wq = C / (c*mu - lambda) = 1/3
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)
    assert mmc_wait(1.0, 1.0, 2) == pytest.approx(1 / 3)


def test_unstable_queue_is_infinite():
    assert math.isinf(mmc_wait(12.0, 4.0, 3))
    assert mmc_wait(0.0, 4.0, 3) == 0.0


# ---- estimator -------------------------------------------------------------
def test_occupancy_window_and_rate():
    est = MessEstimator(occupancy_window_s=20 * 60, rate_window_s=5 * 60)
    for i in range(30):  # one scan per minute for 30 minutes
        est.add_scan(i * 60.0)
    now = 29 * 60.0 + 1
    assert est.occupancy(now) == 20
    assert est.arrival_rate_per_min(now) == pytest.approx(1.0)
    assert est.count_last(now, 60) == 1


def test_out_of_order_scans_are_counted():
    est = MessEstimator(600, 300)
    for ts in [10.0, 30.0, 20.0, 5.0]:
        est.add_scan(ts)
    assert est.occupancy(31.0) == 4


def test_fluid_backlog_grows_and_drains():
    est = MessEstimator(30 * 60, 300)
    est.advance(0.0, capacity_per_min=10)
    for i in range(40):
        est.add_scan(i)
    est.advance(60.0, capacity_per_min=10)  # 40 arrivals, 10 served in a minute
    assert est.backlog == pytest.approx(30)
    est.advance(180.0, capacity_per_min=10)  # 2 more minutes, 20 served
    assert est.backlog == pytest.approx(10)
    est.advance(600.0, capacity_per_min=10)
    assert est.backlog == 0


def test_dedup():
    d = Deduplicator(max_size=2)
    assert d.is_new("a") and not d.is_new("a")
    assert d.is_new(None) and d.is_new(None)


# ---- waits -----------------------------------------------------------------
def test_wait_increases_with_arrivals_and_backlog(cfg):
    m, e = cfg.messes[0], cfg.engine
    idle = HallState(backlog=0, occupancy=0, food=FoodState.OK)
    busy = HallState(backlog=60, occupancy=100, food=FoodState.OK)
    w = [predict_wait(m, e, idle, lam).total for lam in (0, 6, 11, 15, 25)]
    assert w == sorted(w)
    assert predict_wait(m, e, busy, 5).queue > predict_wait(m, e, idle, 5).queue
    # 60 people ahead at 12/min ~ 5 min
    assert predict_wait(m, e, busy, 0).queue == pytest.approx(60 / m.capacity_per_min - 0.5, abs=0.3)


def test_food_out_adds_refill_delay(cfg):
    m, e = cfg.messes[0], cfg.engine
    ok = predict_wait(m, e, HallState(0, 0, FoodState.OK), 5)
    out = predict_wait(m, e, HallState(0, 0, FoodState.OUT, food_out_for_min=2), 5)
    low = predict_wait(m, e, HallState(0, 0, FoodState.LOW), 5)
    assert out.total > low.total > ok.total
    assert out.food == pytest.approx(m.food_refill_time_min - 2 - m.walk_time_s / 60)


def test_seat_wait_when_full(cfg):
    m, e = cfg.messes[0], cfg.engine
    full = HallState(backlog=0, occupancy=m.seats + 50, food=FoodState.OK)
    assert predict_wait(m, e, full, 5).seat > 0
    assert predict_wait(m, e, HallState(0, 10, FoodState.OK), 5).seat == 0


# ---- routing ---------------------------------------------------------------
def test_symmetric_halls_split_evenly():
    fn = lambda lam: 1 + lam / 10 + max(0, lam - 10)  # noqa: E731
    s = equilibrium_split({"A": fn, "B": fn}, total_rate=24)
    assert s["A"] == pytest.approx(0.5, abs=0.01)


def test_equilibrium_equalises_waits():
    fa = lambda lam: 6 + lam / 12  # noqa: E731  (A already has a queue)
    fb = lambda lam: 1 + lam / 12  # noqa: E731
    s = equilibrium_split({"A": fa, "B": fb}, total_rate=120)
    assert fa(120 * s["A"]) == pytest.approx(fb(120 * s["B"]), abs=0.05)
    assert s["B"] > s["A"] > 0  # not all-or-nothing: no herding


def test_hopeless_hall_gets_nothing():
    s = equilibrium_split({"A": lambda lam: 100 + lam, "B": lambda lam: 1 + lam / 12}, total_rate=10)
    assert s["A"] == 0


def test_greedy_is_all_or_nothing():
    assert greedy_split({"A": 5, "B": 3}) == {"A": 0.0, "B": 1.0}


def test_noncompliance_compensation():
    target = {"A": 0.5, "B": 0.5}
    natural = {"A": 0.7, "B": 0.3}
    advice = compensate_for_noncompliance(target, natural, 0.5)
    realised = {i: 0.5 * natural[i] + 0.5 * advice[i] for i in target}
    assert realised["A"] == pytest.approx(0.5)
    assert compensate_for_noncompliance(target, natural, 1.0) == target


def test_floor_keeps_out_hall_share_and_raises_others():
    assert apply_floor({"A": 0.0, "B": 1.0}, 0.05, {"A", "B"}) == pytest.approx({"A": 0.05, "B": 0.95})
    # A is out of food: not raised, but its modelled share is not zeroed either
    assert apply_floor({"A": 0.3, "B": 0.7}, 0.05, {"B"}) == {"A": 0.3, "B": 0.7}


# ---- engine ----------------------------------------------------------------
def _feed(engine, mess_id, n, t0, t1, prefix):
    step = (t1 - t0) / n
    engine.ingest([ScanEvent(t0 + i * step, mess_id, f"k{i}", f"{prefix}{i}") for i in range(n)])


def test_engine_steers_away_from_busy_hall(cfg):
    eng = Engine(cfg)
    eng.update(0)
    _feed(eng, "A", 150, 0, 300, "a")  # 30/min into A, far above its 12/min capacity
    _feed(eng, "B", 20, 0, 300, "b")
    eng.update(300)
    snap = eng.snapshot()
    assert snap.hall("B").share > snap.hall("A").share
    assert snap.hall("A").status in (Status.AMBER, Status.RED)
    assert snap.advice == "Go to Mess B"
    assert snap.hall("A").wait.wait > snap.hall("B").wait.wait


def test_engine_drops_duplicate_events(cfg):
    eng = Engine(cfg)
    ev = [ScanEvent(1.0, "A", "k", "same-id")] * 5
    assert eng.ingest(ev) == 1


def test_stale_out_signal_expires(cfg):
    eng = Engine(cfg)
    eng.food_signal(FoodSignal(0.0, "A", FoodState.OUT))
    assert eng.food_state("A", 60.0)[0] is FoodState.OUT
    expiry = (cfg.mess("A").food_refill_time_min + cfg.engine.food_out_grace_min) * 60
    assert eng.food_state("A", expiry + 1)[0] is FoodState.OK


def test_recommend_draws_follow_shares(cfg):
    eng = Engine(cfg)
    eng._shares = {"A": 0.3, "B": 0.7}
    rng = random.Random(0)
    draws = [eng.recommend(rng) for _ in range(5000)]
    assert draws.count("B") / len(draws) == pytest.approx(0.7, abs=0.03)


# ---- privacy ---------------------------------------------------------------
def test_pseudonymise_is_stable_and_salted():
    a = pseudonymise("2023MDS042", b"salt1")
    assert a == pseudonymise(" 2023MDS042 ", b"salt1")
    assert a != pseudonymise("2023MDS042", b"salt2")
    assert "2023" not in a and len(a) == 16


# ---- simulation ------------------------------------------------------------
def test_simulation_is_deterministic(cfg):
    slot = dataclasses.replace(cfg.simulation.slot("lunch"), expected_students=300)
    a = simulate(cfg, slot, Policy.EQUILIBRIUM, seed=3)
    b = simulate(cfg, slot, Policy.EQUILIBRIUM, seed=3)
    assert a.mean_wait_min == b.mean_wait_min and a.hall_counts == b.hall_counts
    assert a.unfinished == 0


def test_advice_beats_no_advice_on_default_config(cfg):
    slot = cfg.simulation.slot("lunch")
    none = mean(simulate(cfg, slot, Policy.NONE, seed=s).mean_wait_min for s in range(3))
    eq = mean(simulate(cfg, slot, Policy.EQUILIBRIUM, seed=s).mean_wait_min for s in range(3))
    assert eq < none
