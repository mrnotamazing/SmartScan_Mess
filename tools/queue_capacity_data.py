"""Simulated data for the queue / capacity / load-balancing workbook.

    python tools/queue_capacity_data.py            # -> results/queue_capacity.json (20 lunches per scenario)

Everything here is SIMULATED (messq/simulation.py with config/default.toml), not measured.
Per 10-minute slot, mess and stage it records arrivals, mean waits and service times, and the
time-average number of people in the queue / in service (for Little's Law checks). It also runs
static assignments ("department X eats at mess Y") against the dynamic Smart Scan routing.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from messq.config import AppConfig, load_config  # noqa: E402
from messq.engine import Policy  # noqa: E402
from messq.simulation import Simulation  # noqa: E402

SEEDS = range(20)
SLOT_S = 600
N_SLOTS = 18
# stage: (entered, started service, finished) per student; "queue" = entered -> started, "service" = started -> finished
STAGES = {
    "scanner": ("arrived_at", "scan_start", "scanned_at"),
    "station": ("queue_join", "service_start", "service_end"),
    "seat": ("food_at", "seated_at", "table_left"),
    "disposal": ("table_left", "table_left", "left_at"),
    "visit": ("arrived_at", "arrived_at", "left_at"),
}


def _overlap(a: float, b: float, lo: float, hi: float) -> float:
    return max(0.0, min(b, hi) - max(a, lo))


def _run(cfg: AppConfig, policy: Policy, comp: float, seed: int, assign=None) -> Simulation:
    sim = Simulation(cfg, cfg.simulation.slot("lunch"), policy, comp, seed, assign=assign)
    while not sim.finished:
        sim.step()
    return sim


def _stage_stats(sim: Simulation) -> dict:
    """{mess: {stage: [per slot: n, wait_sum, service_sum, L_queue_integral, L_service_integral]}}"""
    out = {}
    for m in sim.cfg.messes:
        studs = [s for s in sim.students if s.hall == m.id and s.left_at is not None]
        out[m.id] = {}
        for stage, (enter, start, end) in STAGES.items():
            rows = []
            for b in range(N_SLOTS):
                lo, hi = b * SLOT_S, (b + 1) * SLOT_S
                n = ws = ss = lq = ls = 0.0
                for s in studs:
                    e, st, f = getattr(s, enter), getattr(s, start), getattr(s, end)
                    lq += _overlap(e, st, lo, hi)
                    ls += _overlap(st, f, lo, hi)
                    if lo <= e < hi:
                        n += 1
                        ws += st - e
                        ss += f - st
                rows.append([n, ws, ss, lq, ls])
            out[m.id][stage] = rows
        # peak seats in use, minute by minute
        occ = [sum(1 for s in studs if s.seated_at <= t < s.table_left) for t in range(0, (N_SLOTS + 3) * SLOT_S, 60)]
        out[m.id]["peak_seated"] = max(occ)
        out[m.id]["students"] = len(studs)
        out[m.id]["outage_min"] = sim.halls[m.id].outage_minutes
    return out


def _base_job(args):
    world, seed = args
    cfg = load_config()
    sim = _run(cfg, Policy.NONE if world == "today" else Policy.EQUILIBRIUM, 0.0 if world == "today" else cfg.simulation.compliance, seed)
    stats = _stage_stats(sim)
    # routing: per slot, students at each door asked to switch, and how many did
    adv = [[0, 0, 0] for _ in range(N_SLOTS)]
    for s in sim.students:
        b = min(N_SLOTS - 1, int(s.decided_at // SLOT_S))
        adv[b][0] += 1
        if s.advised is not None and s.advised != s.habit:
            adv[b][1] += 1
            adv[b][2] += s.hall != s.habit
    stats["advice"] = adv
    return world, seed, stats


def _snapshots(seed: int = 0) -> list[dict]:
    """What the door screens decided at a few moments of one simulated lunch (with screens)."""
    cfg = load_config()
    sim = Simulation(cfg, cfg.simulation.slot("lunch"), Policy.EQUILIBRIUM, cfg.simulation.compliance, seed)
    want = [40, 70, 100, 105, 110, 125]
    out = []
    while not sim.finished and want:
        sim.step()
        if sim.t >= want[0] * 60:
            want.pop(0)
            snap = sim.engine.snapshot()
            row = {"t_min": round(sim.t / 60)}
            for h in snap.halls:
                row[h.mess_id] = {"rate": round(h.arrival_rate, 1), "wait": round(h.wait.wait, 1),
                                  "to_food": round(h.wait.wait + h.wait.service, 1), "food": h.food.value,
                                  "share": round(h.share, 3), "load": round(h.load, 2)}
            row["doors"] = {d.at: {"go_to": d.go_to, "p_switch": round(d.p_switch, 3), "saving": round(d.saving_min, 1),
                                   "level": d.level} for d in snap.doors.values()}
            out.append(row)
    return out


def _variant(cfg: AppConfig, v: str) -> AppConfig:
    sim = cfg.simulation
    lunch = sim.slot("lunch")

    def slot(**ch):
        return dataclasses.replace(cfg, simulation=dataclasses.replace(
            sim, slots=tuple(dataclasses.replace(s, **ch) if s.name == "lunch" else s for s in sim.slots)))

    def mit(share):
        return slot(groups=tuple(dataclasses.replace(g, alt_share=share) if g.name == "MIT" else g for g in lunch.groups))
    return {
        "Average day": cfg,
        "Normal day (-20% students)": slot(expected_students=round(lunch.expected_students * 0.8)),
        "Busy day (+20% students)": slot(expected_students=round(lunch.expected_students * 1.2)),
        "No MIT labs (MIT + SMI at 12:00)": mit(0.0),
        "Heavy lab day (70% of MIT at 13:00)": mit(0.7),
        "Late refills (next batch never ready)": dataclasses.replace(
            cfg, messes=tuple(dataclasses.replace(m, food_ready_prob=0.0) for m in cfg.messes)),
    }[v]


VARIANTS = ["Average day", "Normal day (-20% students)", "Busy day (+20% students)", "No MIT labs (MIT + SMI at 12:00)",
            "Heavy lab day (70% of MIT at 13:00)", "Late refills (next batch never ready)"]
ROBUST = ["Today: habit 80/20, no screens", "Static: freshers to Munch (25% of every department)", "Static: fixed 40% to Munch",
          "Static: fixed 50/50 split (equal stations)", "Static: 40% assigned to Munch, 60% obey", "Static: TAPMI + DOC/MICFE to Munch, rest to Central",
          "Dynamic: Smart Scan screens (60% follow)", "Dynamic: Smart Scan screens (everyone follows)"]


def _robust_job(args):
    name, v, seed = args
    cfg = _variant(load_config(), v)
    spec = POLICIES[name]
    c = cfg
    if "habit" in spec:
        c = dataclasses.replace(cfg, simulation=dataclasses.replace(cfg.simulation, habit_share=spec["habit"]))
    sim = _run(c, spec["policy"], spec.get("comp", 0.0), seed, spec.get("assign"))
    done = [s for s in sim.students if s.seated_at is not None]
    return name, v, mean(s.queue_wait_min for s in done), sum(s.queue_wait_min > 10 for s in done), \
        sum(s.hall != s.habit for s in sim.students) if spec["policy"] is Policy.EQUILIBRIUM else None


def _policy_job(args):
    name, seed = args
    cfg = load_config()
    spec = POLICIES[name]
    c = cfg
    if "habit" in spec:
        c = dataclasses.replace(cfg, simulation=dataclasses.replace(cfg.simulation, habit_share=spec["habit"]))
    sim = _run(c, spec["policy"], spec.get("comp", 0.0), seed, spec.get("assign"))
    done = [s for s in sim.students if s.seated_at is not None]
    waits = sorted(s.queue_wait_min for s in done)
    per = {m.id: [[0, 0.0] for _ in range(N_SLOTS)] for m in cfg.messes}
    for s in done:
        b = min(N_SLOTS - 1, int(s.arrived_at // SLOT_S))
        per[s.hall][b][0] += 1
        per[s.hall][b][1] += s.queue_wait_min
    halls = sim.halls
    return name, seed, {
        "wait": mean(waits), "p90": waits[int(0.9 * (len(waits) - 1))],
        "long": sum(w > 10 for w in waits),
        "munch_share": sum(s.hall == "B" for s in done) / len(done),
        "outages_B": halls["B"].outages, "outages": sum(h.outages for h in halls.values()),
        "peak_q": {k: h.peak_queue for k, h in halls.items()},
        "per_slot": per,
    }


DEPTS = ["MIT", "TAPMI", "DOC/MICFE", "SMI", "DLHS/MILHS", "MLS", "MIRM"]
POLICIES = {
    "Today: habit 80/20, no screens": {"policy": Policy.NONE},
    "Static: freshers to Munch (25% of every department)": {"policy": Policy.NONE, "habit": {"A": 0.75, "B": 0.25}},
    "Static: fixed 40% to Munch": {"policy": Policy.NONE, "habit": {"A": 0.6, "B": 0.4}},
    "Static: fixed 50/50 split (equal stations)": {"policy": Policy.NONE, "habit": {"A": 0.5, "B": 0.5}},
    # Same 60% compliance as the screens: of the extra 20% assigned to Munch, 60% go -> 20% + 0.6 x 20% = 32%
    "Static: 40% assigned to Munch, 60% obey": {"policy": Policy.NONE, "habit": {"A": 0.68, "B": 0.32}},
    "Static: TAPMI + DOC/MICFE to Munch, rest to Central": {
        "policy": Policy.NONE, "assign": {d: ("B" if d in ("TAPMI", "DOC/MICFE") else "A") for d in DEPTS}},
    "Static: MIT to Munch, rest to Central": {"policy": Policy.NONE, "assign": {d: ("B" if d == "MIT" else "A") for d in DEPTS}},
    "Dynamic: Smart Scan screens (60% follow)": {"policy": Policy.EQUILIBRIUM, "comp": 0.6},
    "Dynamic: Smart Scan screens (everyone follows)": {"policy": Policy.EQUILIBRIUM, "comp": 1.0},
}


def main() -> None:
    cfg = load_config()
    with ProcessPoolExecutor() as ex:
        base = list(ex.map(_base_job, [(w, s) for w in ("today", "screens") for s in SEEDS], chunksize=2))
        pol = list(ex.map(_policy_job, [(p, s) for p in POLICIES for s in SEEDS], chunksize=2))
        rob = list(ex.map(_robust_job, [(p, v, s) for p in ROBUST for v in VARIANTS for s in SEEDS], chunksize=4))
    n = len(SEEDS)
    worlds = {}
    for world in ("today", "screens"):
        runs = [st for w, _s, st in base if w == world]
        wd = {}
        for m in cfg.messes:
            md = {}
            for stage in STAGES:
                slots = []
                for b in range(N_SLOTS):
                    tot = [sum(r[m.id][stage][b][k] for r in runs) for k in range(5)]
                    cnt = tot[0]
                    slots.append({
                        "lam": tot[0] / n / 10,  # per minute
                        "wq_min": tot[1] / cnt / 60 if cnt else 0.0,
                        "ws_min": tot[2] / cnt / 60 if cnt else 0.0,
                        "lq": tot[3] / n / SLOT_S,
                        "ls": tot[4] / n / SLOT_S,
                    })
                md[stage] = slots
            md["peak_seated"] = mean(r[m.id]["peak_seated"] for r in runs)
            md["students"] = mean(r[m.id]["students"] for r in runs)
            md["outage_min"] = mean(r[m.id]["outage_min"] for r in runs)
            wd[m.id] = md
        wd["advice"] = [[sum(r["advice"][b][k] for r in runs) / n for k in range(3)] for b in range(N_SLOTS)]
        worlds[world] = wd
    policies = {}
    for p in POLICIES:
        rs = [st for name, _s, st in pol if name == p]
        policies[p] = {
            "wait": mean(r["wait"] for r in rs), "p90": mean(r["p90"] for r in rs), "long": mean(r["long"] for r in rs),
            "munch_share": mean(r["munch_share"] for r in rs), "outages_B": mean(r["outages_B"] for r in rs),
            "outages": mean(r["outages"] for r in rs),
            "peak_q": {k: mean(r["peak_q"][k] for r in rs) for k in ("A", "B")},
            "per_slot": {k: [(sum(r["per_slot"][k][b][1] for r in rs) / max(1, sum(r["per_slot"][k][b][0] for r in rs)),
                              sum(r["per_slot"][k][b][0] for r in rs) / n) for b in range(N_SLOTS)] for k in ("A", "B")},
        }
    robust = {p: {v: {"wait": mean(r[2] for r in rob if r[0] == p and r[1] == v),
                      "long": mean(r[3] for r in rob if r[0] == p and r[1] == v)} for v in VARIANTS} for p in ROBUST}
    out = {"seeds": n, "worlds": worlds, "policies": policies, "robust": robust, "variants": VARIANTS,
           "snapshots": _snapshots(0)}
    path = ROOT / "results" / "queue_capacity.json"
    path.write_text(json.dumps(out, indent=1))
    for p, v in policies.items():
        print(f"{p:55s} wait {v['wait']:5.2f}  p90 {v['p90']:5.1f}  >10min {v['long']:6.0f}  Munch {v['munch_share']:.0%}  "
              f"outB {v['outages_B']:.1f}  peakQ C {v['peak_q']['A']:.0f} M {v['peak_q']['B']:.0f}")
    for p in ROBUST:
        print(f"{p[:45]:45s} " + "  ".join(f"{robust[p][v]['wait']:5.2f}" for v in VARIANTS))
    print("written", path)


if __name__ == "__main__":
    main()
