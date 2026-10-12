"""Monte Carlo comparison of routing policies on simulated data.

    python -m messq.simulate                          # lunch, all policies, 20 runs
    python -m messq.simulate --slot dinner --runs 50
    python -m messq.simulate --compliance 0.2 0.4 0.6 0.8 1.0
    python -m messq.simulate --trace                  # what the screen would show, every 5 min
    python -m messq.simulate --replay logs.csv        # list the meals found in a scanner log
    python -m messq.simulate --replay logs.csv --session 1   # replay that meal under each policy
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import asdict
from pathlib import Path
from statistics import mean, stdev

from .config import load_config
from .engine import Policy, Snapshot
from .simulation import SimResult, simulate

METRICS = [
    ("mean_wait_min", "avg wait", "{:.1f}"),
    ("p90_wait_min", "p90 wait", "{:.1f}"),
    ("peak_queue", "peak queue", "{:.0f}"),
    ("outages", "run-outs", "{:.1f}"),
    ("outage_minutes", "run-out min", "{:.1f}"),
    ("compliance_rate", "followed", "{:.0%}"),
    ("switch_rate", "switched", "{:.0%}"),
    ("occupancy_mae", "occ. err", "{:.0f}"),
]


def ci95(xs: list[float]) -> float:
    return 1.96 * stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def summarise(results: list[SimResult]) -> dict[str, tuple[float, float]]:
    out = {}
    for key, _, _ in METRICS:
        xs = [getattr(r, key) for r in results if not math.isnan(getattr(r, key))]
        out[key] = (mean(xs), ci95(xs)) if xs else (math.nan, 0.0)
    return out


def format_snapshot(s: Snapshot) -> str:
    others = "  ".join(
        f"{h.name}: ~{h.wait.wait:.0f} min wait, {h.status.value.upper():5s} "
        f"(occ~{h.occupancy}/{h.seats}, {h.arrival_rate:.0f}/min, food {h.food.value}, advise {h.share:.0%})"
        for h in s.halls
    )
    return f"t={s.ts / 60:5.0f} min | {s.advice:28s} | {others}"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--slot", default="lunch")
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--policies", nargs="+", default=[p.value for p in Policy], choices=[p.value for p in Policy])
    p.add_argument("--compliance", type=float, nargs="+", help="override simulation.compliance (one or more)")
    p.add_argument("--csv", default="results/simulation_runs.csv")
    p.add_argument("--trace", action="store_true", help="print one equilibrium run as the screen would show it")
    p.add_argument("--replay", help="CSV scanner log to replay instead of simulated arrivals")
    p.add_argument("--session", type=int, help="which meal in the log to replay (see --replay alone)")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    slot = cfg.simulation.slot(args.slot)
    arrivals = natural = None
    if args.replay:
        from .logs import parse_log, replay_slot
        from .privacy import load_salt

        log = parse_log(Path(args.replay).read_text(encoding="utf-8-sig", errors="replace"), cfg.messes, load_salt(cfg.privacy.salt_env))
        print(f"Columns used: {log.columns}; devices -> messes: {log.mapping}")
        for w in log.warnings:
            print("Note:", w)
        for sess in log.sessions:
            print(f"  [{sess.index}] {sess.label()}  {sess.counts}")
        if args.session is None:
            print("\nPick one with --session N")
            return
        sess = log.sessions[args.session]
        slot, start = replay_slot(sess)
        arrivals = log.arrivals(sess, start)
        natural = {k: v / sess.total for k, v in sess.counts.items()}
        print(f"\nReplaying {sess.label()}. Arrivals are real; queues, serving and seating are simulated.")

    if args.trace:
        comp = (args.compliance or [cfg.simulation.compliance])[0]
        r = simulate(cfg, slot, Policy.EQUILIBRIUM, comp, seed=1, snapshot_every_s=300)
        for s in r.snapshots:
            print(format_snapshot(s))
        return

    compliances = args.compliance or [cfg.simulation.compliance]
    rows: list[SimResult] = []
    if not args.replay:
        print(f"Slot '{slot.name}': {slot.expected_students} students expected, {args.runs} runs per setting\n")
    header = f"{'policy':12s} {'comply':>6s} " + " ".join(f"{label:>14s}" for _, label, _ in METRICS)
    print(header)
    print("-" * len(header))
    for policy in [Policy(x) for x in args.policies]:
        for comp in [0.0] if policy is Policy.NONE else compliances:
            results = [
                simulate(cfg, slot, policy, comp, seed=i, arrivals=arrivals, natural=natural) for i in range(args.runs)
            ]
            rows.extend(results)
            summ = summarise(results)
            cells = []
            for key, _, fmt in METRICS:
                m, h = summ[key]
                cell = "n/a" if math.isnan(m) else fmt.format(m) + (f"±{fmt.format(h)}" if h and "%" not in fmt else "")
                cells.append(f"{cell:>14s}")
            print(f"{policy.value:12s} {comp:6.0%} " + " ".join(cells))

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            fields = [k for k in asdict(rows[0]) if k not in ("snapshots", "hall_counts")]
            fields += [f"students_{m.id}" for m in cfg.messes]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                d = {k: v for k, v in asdict(r).items() if k in fields}
                d.update({f"students_{k}": v for k, v in r.hall_counts.items()})
                w.writerow(d)
        print(f"\nPer-run results written to {path}")
    print("\nWaits are minutes from scanning in at the hall to sitting down with food (±95% CI).")
    print("All inputs are simulated; numbers marked ASSUMED in the config drive these results.")


if __name__ == "__main__":
    main()
