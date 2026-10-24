"""Spreadsheet views of a meal: one scan log per mess, and counts per time slot.

Used by the live sheet page, the Excel/CSV downloads, and the files the demo
can keep updated on disk. Only scans up to the current (simulated) time are
included, so the sheets grow as the meal goes on.
"""

from __future__ import annotations

import csv
import io
from statistics import mean

from .config import AppConfig
from .simulation import Simulation
from .xlsx import Chart, Sheet, build_xlsx

LOG_HEADER = ["Time", "Name", "ID", "Wait (min)", "Time inside (min)", "Note"]
# Categorical slots 1 and 2 of the dataviz palette; mess 3+ continue in fixed order.
MESS_COLORS = ["2A78D6", "EB6834", "1BAF7A", "EDA100", "E87BA4"]


def _clock(start_hhmm: str, t_s: float, seconds: bool = True) -> str:
    hh, mm = map(int, start_hhmm.split(":"))
    total = hh * 3600 + mm * 60 + int(t_s)
    h, m, s = (total // 3600) % 24, (total // 60) % 60, total % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if seconds else f"{h:02d}:{m:02d}"


def log_rows(sim: Simulation, mess_id: str) -> list[list]:
    """Everyone who has scanned in at `mess_id` so far, in scan order."""
    names = {m.id: m.name for m in sim.cfg.messes}
    rows = []
    scanned = (s for s in sim.students if s.hall == mess_id and s.scanned_at is not None and s.scanned_at <= sim.t)
    for s in sorted(scanned, key=lambda s: s.scanned_at):
        wait = round(s.queue_wait_min, 1) if s.seated_at is not None and s.seated_at <= sim.t else ""
        note = f"walked over from {names[s.habit]} (screen)" if s.hall != s.habit else ""
        inside = round((s.left_at - s.scanned_at) / 60, 1) if s.left_at is not None and s.left_at <= sim.t else ""
        rows.append([_clock(sim.slot.start, s.scanned_at), s.name or "(hidden)", f"ID {s.key[:6]}", wait, inside, note])
    return rows


def _slots(sim: Simulation, interval_min: int):
    """(label, students who scanned in during the slot) for each clock-aligned slot so far."""
    hh, mm = map(int, sim.slot.start.split(":"))
    start_min = hh * 60 + mm
    step = interval_min
    first = (start_min // step) * step
    now_min = start_min + sim.t / 60
    buckets: dict[int, list] = {}
    for s in sim.students:
        if s.scanned_at is None or s.scanned_at > sim.t:
            continue
        b = int((start_min + s.scanned_at / 60 - first) // step)
        buckets.setdefault(b, []).append(s)
    b = 0
    while first + b * step <= now_min:
        lo = first + b * step
        label = f"{lo // 60 % 24:02d}:{lo % 60:02d}–{(lo + step) // 60 % 24:02d}:{(lo + step) % 60:02d}"
        if lo + step > now_min:
            label += " (so far)"
        yield label, buckets.get(b, [])
        b += 1


def _avg_wait(studs, t: float) -> float | str:
    w = [s.queue_wait_min for s in studs if s.seated_at is not None and s.seated_at <= t]
    return round(mean(w), 1) if w else ""


def summary_rows(sim: Simulation, interval_min: int) -> tuple[list[str], list[list]]:
    """Students per mess per time slot (aligned to the clock, e.g. 12:30-13:00)."""
    cfg: AppConfig = sim.cfg
    ids = [m.id for m in cfg.messes]
    header = ["Time slot", *[m.name for m in cfg.messes], "Total",
              f"{cfg.messes[0].name} share (%)",
              *[f"Avg wait {m.name} (min)" for m in cfg.messes], "Walked over (screen)"]
    depts = bool(sim.slot.groups)
    if depts:
        header.append("On lunch break")
    rows = []
    hh, mm = map(int, sim.slot.start.split(":"))
    first = ((hh * 60 + mm) // interval_min) * interval_min - (hh * 60 + mm)
    for k, (label, studs) in enumerate(_slots(sim, interval_min)):
        counts = [sum(s.hall == i for s in studs) for i in ids]
        total = sum(counts)
        waits = [_avg_wait([s for s in studs if s.hall == i], sim.t) for i in ids]
        rows.append([label, *counts, total, round(100 * counts[0] / total) if total else "", *waits,
                     sum(s.hall != s.habit for s in studs)])
        if depts:
            lo = first + k * interval_min
            rows[-1].append(", ".join(sim.slot.on_break(lo, lo + interval_min)))
    return header, rows


def compare_wait_rows(without: Simulation, with_: Simulation, interval_min: int,
                      without_title: str = "Without the system") -> tuple[list[str], list[list]]:
    """Average wait per time slot, both messes together, without vs with the screens.
    The two runs share the same students and clock, so their slots line up."""
    header = ["Time slot", f"{without_title}: avg wait (min)", "With the screens: avg wait (min)", "Minutes saved"]
    rows = []
    for (label, a), (_, b) in zip(_slots(without, interval_min), _slots(with_, interval_min)):
        wa, wb = _avg_wait(a, without.t), _avg_wait(b, with_.t)
        rows.append([label, wa, wb, round(wa - wb, 1) if wa != "" and wb != "" else ""])
    return header, rows


def workbook(sim: Simulation, interval_min: int, compare: tuple[list[str], list[list]] | None = None) -> bytes:
    cfg = sim.cfg
    sheets = []
    for m in cfg.messes:
        sheets.append(Sheet(name=f"{m.name} log"[:31], header=LOG_HEADER, rows=log_rows(sim, m.id),
                            widths=[11, 22, 11, 11, 16, 34]))
    header, rows = summary_rows(sim, interval_min)
    n = len(cfg.messes)
    colors = [MESS_COLORS[i % len(MESS_COLORS)] for i in range(n)]
    height = 18
    sheets.append(Sheet(
        name=f"Every {interval_min} min"[:31], header=header, rows=rows,
        widths=[20] + [14] * n + [9, 14] + [18] * n + [16],
        charts=[
            Chart(f"Students per {interval_min} min", "bar", 0, list(range(1, n + 1)), colors,
                  (0, len(rows) + 3, 8, len(rows) + 3 + height), "Students"),
            Chart(f"Average wait per {interval_min} min", "line", 0, list(range(n + 3, 2 * n + 3)), colors,
                  (9, len(rows) + 3, 17, len(rows) + 3 + height), "Minutes"),
        ],
    ))
    if compare:
        c_header, c_rows = compare
        sheets.append(Sheet(
            name="Wait with vs without"[:31], header=c_header, rows=c_rows, widths=[20, 30, 30, 14],
            charts=[Chart(f"Average wait per {interval_min} min: without vs with the system", "line", 0, [1, 2],
                          [MESS_COLORS[1], MESS_COLORS[0]], (0, len(c_rows) + 3, 8, len(c_rows) + 3 + height), "Minutes")],
        ))
    return build_xlsx(sheets)


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()
