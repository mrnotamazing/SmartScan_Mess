"""The scenario comparison used in the report and the workbook.

    python -m messq.scenarios                 # 20 runs per scenario -> results/scenarios.json
    python -m messq.scenarios --runs 40
    python -m messq.scenarios --payoff         # alternatives x kinds of day -> results/payoff.json
    python -m messq.scenarios --reconcile      # spreadsheet-like -> full simulator -> results/reconcile.json

Every scenario sees the same students (same seeds). Scenarios:
  1  Current system           students go where habit takes them
  2  Queue information only   door screens use queues, but never hear about food
  3  Queue + food             door screens use queues and the manager's food status (the proposal)
  N  Naive "go to the shorter queue"  shown to make the herding point
Stress tests re-run 1, 2 and 3 with one input changed at a time.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean, stdev

from .config import AppConfig, load_config
from .engine import Policy
from .simulation import simulate

BASE = [
    ("1 Current system", Policy.NONE, True),
    ("2 Queue information only", Policy.EQUILIBRIUM, False),
    ("3 Queue + food (proposal)", Policy.EQUILIBRIUM, True),
    ("N Naive: go to the shorter queue", Policy.GREEDY, True),
]


def _with_messes(cfg: AppConfig, **changes) -> AppConfig:
    return dataclasses.replace(cfg, messes=tuple(dataclasses.replace(m, **changes) for m in cfg.messes))


def _with_slot(cfg: AppConfig, **changes) -> AppConfig:
    sim = cfg.simulation
    slots = tuple(dataclasses.replace(s, **changes) if s.name == "lunch" else s for s in sim.slots)
    return dataclasses.replace(cfg, simulation=dataclasses.replace(sim, slots=slots))


def _with_sim(cfg: AppConfig, **changes) -> AppConfig:
    return dataclasses.replace(cfg, simulation=dataclasses.replace(cfg.simulation, **changes))


def stress_tests(cfg: AppConfig) -> list[tuple[str, AppConfig, float]]:
    lunch = cfg.simulation.slot("lunch")
    comp = cfg.simulation.compliance
    return [
        ("Demand +20% (3,552 students)", _with_slot(cfg, expected_students=round(lunch.expected_students * 1.2)), comp),
        ("Sharper peak (spread 25 min, not 35)", _with_slot(cfg, spread_min=25), comp),
        ("Only 30% follow the screens", cfg, 0.3),
        ("Everyone follows the screens", cfg, 1.0),
        ("Slower serving: 8 students/min per station", _with_messes(cfg, service_rate_per_counter_per_min=8.0), comp),
        ("Faster serving: 12 students/min per station", _with_messes(cfg, service_rate_per_counter_per_min=12.0), comp),
        ("More stock-outs: next batch never ready", _with_messes(cfg, food_ready_prob=0.0), comp),
        ("No stock-outs: next batch always ready", _with_messes(cfg, food_ready_prob=1.0), comp),
        ("Slower eating: 15-18 min", _with_sim(cfg, eat_min=(15.0, 18.0)), comp),
    ]


METRICS = ["mean_wait_min", "p90_wait_min", "mean_throughput_min", "p90_throughput_min", "mean_total_min",
           "quiet_throughput_min", "peak_throughput_min",
           "outages", "outage_minutes", "redirected", "unsuccessful_rate", "compliance_rate", "peak_queue", "peak_scan_queue"]


def _one(job):
    cfg, policy, comp, use_food, seed = job
    r = simulate(cfg, cfg.simulation.slot("lunch"), policy, comp, seed=seed, use_food=use_food)
    out = {k: getattr(r, k) for k in METRICS}
    out.update({f"util_{k}": v for k, v in r.util.items()})
    out.update({f"peak_load_{k}": v for k, v in r.peak_load.items()})
    out["students"] = r.students
    return out


def _summary(runs: list[dict]) -> dict:
    out = {}
    for k in runs[0]:
        xs = [r[k] for r in runs if not (isinstance(r[k], float) and math.isnan(r[k]))]
        if not xs:
            out[k] = {"mean": None, "ci95": None}
            continue
        m = mean(xs)
        h = 1.96 * stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
        out[k] = {"mean": round(m, 3), "ci95": round(h, 3)}
    return out


def run(cfg: AppConfig, runs: int = 20, workers: int | None = None) -> dict:
    comp = cfg.simulation.compliance
    plan: list[tuple[str, str, AppConfig, Policy, float, bool]] = []
    for name, pol, food in BASE:
        plan.append(("base", name, cfg, pol, 0.0 if pol is Policy.NONE else comp, food))
    for test, tcfg, tcomp in stress_tests(cfg):
        for name, pol, food in BASE[:3]:
            plan.append((test, name, tcfg, pol, 0.0 if pol is Policy.NONE else tcomp, food))
    jobs = [(c, pol, cp, food, seed) for (_, _, c, pol, cp, food) in plan for seed in range(runs)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        flat = list(ex.map(_one, jobs, chunksize=4))
    results = []
    for i, (group, name, _, pol, cp, food) in enumerate(plan):
        results.append({"group": group, "scenario": name, "compliance": cp, "uses_food": food,
                        "runs": runs, **_summary(flat[i * runs:(i + 1) * runs])})
    return {"runs_per_scenario": runs, "students_expected": cfg.simulation.slot("lunch").expected_students,
            "results": results}


def _table(plan: list[tuple[str, str, AppConfig, Policy, float, bool]], runs: int, workers: int | None) -> list[dict]:
    jobs = [(c, pol, cp, food, seed) for (_, _, c, pol, cp, food) in plan for seed in range(runs)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        flat = list(ex.map(_one, jobs, chunksize=4))
    return [{"row": a, "col": b, "runs": runs, **_summary(flat[i * runs:(i + 1) * runs])}
            for i, (a, b, *_rest) in enumerate(plan)]


def payoff(cfg: AppConfig, runs: int = 20, workers: int | None = None) -> dict:
    """Average queue wait for each alternative on each kind of day (the S7 payoff matrix)."""
    lunch = cfg.simulation.slot("lunch")
    comp = cfg.simulation.compliance
    n = lunch.expected_students
    states = [
        ("S1 Normal day (-20% students)", _with_slot(cfg, expected_students=round(n * 0.8))),
        ("S2 Busy day (2,960 students)", cfg),
        ("S3 Surge + late refills (+20%, batch never ready)",
         _with_messes(_with_slot(cfg, expected_students=round(n * 1.2)), food_ready_prob=0.0)),
    ]
    third = lambda c: dataclasses.replace(  # noqa: E731
        c, messes=tuple(dataclasses.replace(m, counters=m.counters + 1) if m.id == "A" else m for m in c.messes))
    alts = [
        ("A1 No system (today)", lambda c: c, Policy.NONE, True),
        ("A2 Door screens, queue information only", lambda c: c, Policy.EQUILIBRIUM, False),
        ("A3 Door screens + food status (proposal)", lambda c: c, Policy.EQUILIBRIUM, True),
        ("A4 3rd serving station at Central (no screens)", third, Policy.NONE, True),
        ("A5 Proposal + 3rd serving station", third, Policy.EQUILIBRIUM, True),
    ]
    plan = [(a, st, f(sc), pol, 0.0 if pol is Policy.NONE else comp, food)
            for a, f, pol, food in alts for st, sc in states]
    return {"runs": runs, "alternatives": [a[0] for a in alts], "states": [s[0] for s in states],
            "cells": _table(plan, runs, workers)}


def reconcile(cfg: AppConfig, runs: int = 20, workers: int | None = None) -> dict:
    """Why the spreadsheet (S15) and the simulator differ: start the simulator with the
    spreadsheet's simplifications, then add one real-world feature at a time."""
    comp = cfg.simulation.compliance
    big = dict(food_batch=10**6, food_refill_trigger=0, seats=10**6, scan_time_s=0.01)
    steps = [
        ("1 Spreadsheet-like: exponential serving, no run-outs, no scanner or seat limits",
         _with_sim(_with_messes(cfg, **big), service_cv=1.0)),
        ("2 + realistic serving variability (cv 0.6)", _with_messes(cfg, **big)),
        ("3 + one face scanner per mess (2 s each)",
         _with_messes(cfg, food_batch=10**6, food_refill_trigger=0, seats=10**6)),
        ("4 + seat limits", _with_messes(cfg, food_batch=10**6, food_refill_trigger=0)),
        ("5 + food run-outs and refills (full model)", cfg),
    ]
    plan = []
    for name, c in steps:
        plan.append((name, "Without screens", c, Policy.NONE, 0.0, True))
        plan.append((name, "With screens", c, Policy.EQUILIBRIUM, comp, True))
    return {"runs": runs, "steps": [s[0] for s in steps], "cells": _table(plan, runs, workers)}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--out", default="results/scenarios.json")
    p.add_argument("--payoff", action="store_true")
    p.add_argument("--reconcile", action="store_true")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    if a.payoff or a.reconcile:
        data = payoff(cfg, a.runs) if a.payoff else reconcile(cfg, a.runs)
        out = Path("results/payoff.json" if a.payoff else "results/reconcile.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1))
        for c in data["cells"]:
            w, t = c["mean_wait_min"], c["mean_throughput_min"]
            print(f"{c['row'][:60]:60s} {c['col'][:48]:48s} wait {w['mean']:6.2f}±{w['ci95']:.2f}  p90 {c['p90_wait_min']['mean']:5.1f}  thru {t['mean']:5.1f}")
        print(f"\nWritten to {out}")
        return
    data = run(cfg, a.runs)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    print(f"{'group':42s} {'scenario':34s} {'wait':>11s} {'p90':>6s} {'thru':>6s} {'p90thru':>7s} {'utilA':>6s} {'utilB':>6s} {'out':>5s} {'redir':>6s} {'unsucc':>7s}")
    for r in data["results"]:
        g = lambda k: r[k]["mean"]  # noqa: E731
        u = g("unsuccessful_rate")
        print(f"{r['group'][:42]:42s} {r['scenario'][:34]:34s} {g('mean_wait_min'):5.2f}±{r['mean_wait_min']['ci95']:4.2f} "
              f"{g('p90_wait_min'):6.1f} {g('mean_throughput_min'):6.1f} {g('p90_throughput_min'):7.1f} "
              f"{g('util_A'):6.0%} {g('util_B'):6.0%} {g('outages'):5.1f} {g('redirected'):6.0f} "
              f"{'' if u is None else format(u, '.0%'):>7s}")
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
