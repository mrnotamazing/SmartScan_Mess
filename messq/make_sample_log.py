"""Write a fake one-day scanner log, in the shape a COSEC export might have,
so the upload/replay feature can be tried before real logs exist.

    python -m messq.make_sample_log                 # -> samples/sample_day_log.csv
    python -m messq.make_sample_log --date 2026-10-12 --out my_log.csv

The data is simulated (no-advice behaviour from the default config); IDs and names are made up.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_config
from .engine import Policy
from .simulation import simulate


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--date", default="2026-10-12")
    p.add_argument("--out", default="samples/sample_day_log.csv")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    day = datetime.strptime(args.date, "%Y-%m-%d")
    rng = random.Random(args.seed)
    roll_numbers = [f"STU{n:05d}" for n in rng.sample(range(10000, 99999), 2500)]
    rows = []
    for i, slot in enumerate(cfg.simulation.slots):
        hh, mm = map(int, slot.start.split(":"))
        start = day.replace(hour=hh, minute=mm)
        result = simulate(cfg, slot, Policy.NONE, seed=args.seed + i, keep_students=True)
        eaters = rng.sample(roll_numbers, min(len(roll_numbers), len(result.students_list)))
        devices = {m.id: m.name.upper().replace(" ", "-") + "-ENTRY" for m in cfg.messes}
        for s, roll in zip(result.students_list, eaters):
            ts = start + timedelta(seconds=s.arrived_at)
            rows.append((ts, roll, s.name, devices[s.hall]))
    rows.sort()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Time", "User ID", "User Name", "Device Name", "Direction"])
        for ts, roll, name, device in rows:
            w.writerow([ts.strftime("%d/%m/%Y"), ts.strftime("%H:%M:%S"), roll, name, device, "IN"])
    print(f"Wrote {len(rows)} fake scans to {out}")


if __name__ == "__main__":
    main()
