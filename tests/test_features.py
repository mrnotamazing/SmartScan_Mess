import dataclasses

import pytest

from messq.config import load_config
from messq.engine import Engine, Policy
from messq.events import FoodSignal, FoodState, ScanEvent
from messq.logs import LogError, parse_log, replay_slot
from messq.routing import door_switch_probs
from messq.simulation import simulate

SALT = b"test"


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ---- log parsing -------------------------------------------------------------
def _csv(rows, header):
    return "\n".join([header] + rows)


def test_parse_split_date_time_and_device_names(cfg):
    rows = [f"12/10/2026,12:{m:02d}:00,STU{m},MESS-{'A' if m % 3 else 'B'}-ENTRY,IN" for m in range(40)]
    rows.append("12/10/2026,12:41:00,STU1,MESS-A-ENTRY,OUT")  # exit rows are ignored
    log = parse_log(_csv(rows, "Date,Time,User ID,Device Name,Direction"), cfg.messes, SALT)
    assert log.mapping == {"MESS-A-ENTRY": "A", "MESS-B-ENTRY": "B"}
    assert len(log.scans) == 40
    assert any("exit" in w for w in log.warnings)
    assert len(log.sessions) == 1 and log.sessions[0].name == "Lunch"
    assert all("STU" not in key for _, _, key in log.scans)  # raw IDs never kept


def test_parse_single_timestamp_semicolons_and_unknown_device_names(cfg):
    rows = [f"2026-10-12 08:{m:02d}:10;{'North gate' if m % 2 else 'South gate'};{m}" for m in range(30)]
    rows += [f"2026-10-12 20:{m:02d}:10;North gate;{m}" for m in range(30)]
    log = parse_log(_csv(rows, "Punch Time;Terminal;Employee Code"), cfg.messes, SALT)
    assert set(log.mapping.values()) == {"A", "B"}
    assert [s.name for s in log.sessions] == ["Breakfast", "Dinner"]


def test_parse_errors_are_helpful(cfg):
    with pytest.raises(LogError, match="time column"):
        parse_log("name,device\nx,A\n", cfg.messes, SALT)
    rows = [f"2026-10-12 12:{m:02d}:00,Hall {m % 3}" for m in range(30)]
    with pytest.raises(LogError, match="3 different"):
        parse_log(_csv(rows, "timestamp,hall"), cfg.messes, SALT)


def test_replay_reproduces_log_in_no_advice_world(cfg):
    rows = [f"2026-10-12 12:{m // 4:02d}:{(m % 4) * 15:02d},{'A' if m % 3 else 'B'}" for m in range(200)]
    log = parse_log(_csv(rows, "timestamp,mess"), cfg.messes, SALT)
    sess = log.sessions[0]
    slot, start = replay_slot(sess)
    r = simulate(cfg, slot, Policy.NONE, arrivals=log.arrivals(sess, start), keep_students=True)
    assert r.hall_counts == sess.counts
    got = sorted(round(s.arrived_at) for s in r.students_list)
    want = sorted(round((ts - start).total_seconds()) for ts, _, _ in log.scans)
    assert got == want


# ---- door screens --------------------------------------------------------------
def test_door_switch_only_from_overfull_door_and_only_if_worth_it():
    target, natural = {"A": 0.5, "B": 0.5}, {"A": 0.7, "B": 0.3}
    probs = door_switch_probs(target, natural, 1.0, {"A": 10, "B": 2}, 0.5, 2)
    assert probs["A"][0] == "B" and probs["A"][1] == pytest.approx(0.2 / 0.7)
    assert probs["B"] == (None, 0.0)
    # saving after the walk is under the threshold: nobody is asked to walk
    assert door_switch_probs(target, natural, 1.0, {"A": 3, "B": 2}, 0.5, 2)["A"] == (None, 0.0)
    # lower compliance -> ask a larger share
    assert door_switch_probs(target, natural, 0.5, {"A": 10, "B": 2}, 0.5, 2)["A"][1] == pytest.approx(0.4 / 0.7)


def test_engine_door_advice_points_away_from_busy_hall(cfg):
    eng = Engine(cfg)
    eng.update(0)
    eng.ingest([ScanEvent(i * 2.0, "A", f"a{i}", f"a{i}") for i in range(150)])
    eng.ingest([ScanEvent(i * 15.0, "B", f"b{i}", f"b{i}") for i in range(20)])
    eng.update(300)
    door = eng.snapshot().doors
    assert door["A"].go_to == "B" and door["A"].level in ("soft", "strong")
    assert door["B"].go_to is None and door["B"].level == "stay"


def test_doors_layout_needs_fewer_switches_than_hallway(cfg):
    slot = cfg.simulation.slot("lunch")
    hall_cfg = dataclasses.replace(cfg, layout=dataclasses.replace(cfg.layout, mode="hallway"))
    doors = simulate(cfg, slot, Policy.EQUILIBRIUM, seed=1)
    hallway = simulate(hall_cfg, slot, Policy.EQUILIBRIUM, seed=1)
    none = simulate(cfg, slot, Policy.NONE, seed=1)
    assert doors.switch_rate < hallway.switch_rate
    assert doors.mean_wait_min < none.mean_wait_min


# ---- kitchen trays ---------------------------------------------------------------
def test_tray_aggregation_and_fresh_batch(cfg):
    eng = Engine(cfg)
    rice = cfg.mess("A").items[1]
    eng.food_signal(FoodSignal(0, "A", FoodState.OUT, rice))
    assert eng.food_state("A", 10)[0] is FoodState.LOW  # a side tray out slows service, doesn't stop it
    eng.food_signal(FoodSignal(20, "A", FoodState.OUT))  # main tray
    assert eng.food_state("A", 30)[0] is FoodState.OUT
    eng.food_signal(FoodSignal(60, "A", FoodState.OK))  # "all refilled"
    assert all(st is FoodState.OK for _, st, _ in eng.trays("A", 61))
    eng.update(61)
    assert eng.snapshot().hall("A").fresh
