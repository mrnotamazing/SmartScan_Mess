"""Read a scanner log export (CSV) and split it into meals for replay.

We don't know the exact column names of a Matrix COSEC export yet, so the
parser looks for columns by common names:

    time:   "timestamp", "datetime", "punch time", ... or a "date" + "time" pair
    mess:   "mess", "device", "door", "terminal", "reader", "location", "hall", ...
    person: "user id", "employee id", "roll", "student", "card", ... (optional)
    in/out: "direction", "event", "type", "in/out"  (optional; exit rows are dropped)

Raw IDs are hashed the moment a row is read and never stored. Only
(time, mess, hashed key) leaves this module.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .config import MealSlot, MessConfig
from .privacy import pseudonymise

DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p", "%d-%m-%Y %I:%M:%S %p", "%d-%m-%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%d-%b-%Y %H:%M:%S", "%d %b %Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%H:%M:%S.%f"]

TIME_KEYS = ("timestamp", "datetime", "date time", "date_time", "punch time", "event time", "log time", "scan time")
MESS_KEYS = ("mess", "device", "door", "terminal", "reader", "location", "hall", "gate", "site", "controller", "zone")
ID_KEYS = ("user", "employee", "emp", "student", "roll", "card", "person", "member", "id")
NAME_KEYS = ("name", "student name", "full name", "user name", "employee name", "person name")
DIR_KEYS = ("direction", "in/out", "inout", "entry/exit", "event", "type", "status")
EXIT_WORDS = ("out", "exit", "check-out", "checkout")

MAX_GAP_MIN = 45  # a gap longer than this between scans starts a new meal
MIN_SESSION_SCANS = 10


class LogError(ValueError):
    pass


@dataclass
class Session:
    index: int
    name: str
    start: datetime
    end: datetime
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def label(self) -> str:
        return f"{self.name} {self.start:%d %b, %H:%M}–{self.end:%H:%M} · {self.total:,} scans"


@dataclass
class ParsedLog:
    scans: list[tuple[datetime, str, str]]  # (time, mess id, hashed key), sorted
    names: dict[str, str] = field(default_factory=dict)  # hashed key -> name, only if show_names
    mapping: dict[str, str] = field(default_factory=dict)  # value in the file -> mess id
    columns: dict[str, str] = field(default_factory=dict)  # role -> column name used
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)

    def arrivals(self, session: Session, slot_start: datetime) -> list[tuple[float, str, str | None]]:
        return [
            ((ts - slot_start).total_seconds(), mess, self.names.get(key))
            for ts, mess, key in self.scans
            if session.start <= ts <= session.end
        ]


def _find(headers: list[str], keys: tuple[str, ...], exclude: set[str] = frozenset()) -> str | None:
    norm = {h: h.strip().lower().replace("_", " ") for h in headers if h not in exclude}
    for key in keys:  # exact match first, then "contains", in priority order
        for h, n in norm.items():
            if n == key:
                return h
    for key in keys:
        for h, n in norm.items():
            if key in n:
                return h
    return None


def _parse_dt(value: str) -> datetime | None:
    value = value.strip()
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _parse_time(value: str) -> time | None:
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except ValueError:
            pass
    return None


def _map_messes(values: set[str], messes: tuple[MessConfig, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for v in values:
        low = " ".join(v.strip().lower().replace("-", " ").replace("_", " ").split())
        for m in messes:
            if low in (m.id.lower(), m.name.lower()) or m.name.lower() in low:
                mapping[v] = m.id
                break
        else:  # e.g. "MESS-A-ENTRY" -> A, "Hall 2" -> second mess
            tokens = low.replace("-", " ").replace("_", " ").split()
            for m in messes:
                if m.id.lower() in tokens:
                    mapping[v] = m.id
                    break
    unmatched = sorted(values - set(mapping))
    free = [m.id for m in messes if m.id not in mapping.values()]
    if len(unmatched) > len(free):
        raise LogError(
            f"The file has {len(values)} different mess/device values ({', '.join(sorted(values)[:8])}) "
            f"but the config only has {len(messes)} messes. Add the missing messes to config/default.toml."
        )
    mapping.update(zip(unmatched, free))
    return mapping


def _meal_name(start: datetime) -> str:
    h = start.hour + start.minute / 60
    if h < 11:
        return "Breakfast"
    if h < 16:
        return "Lunch"
    if h < 18.5:
        return "Snacks"
    return "Dinner"


def replay_slot(session: Session) -> tuple[MealSlot, datetime]:
    """A simulation slot covering one meal from a log, starting a few minutes early."""
    start = session.start.replace(second=0, microsecond=0)
    start = start - timedelta(minutes=start.minute % 5 + 5)
    duration = int((session.end - start).total_seconds() // 60) + 5
    slot = MealSlot(
        name=session.name.lower(),
        start=f"{start:%H:%M}",
        duration_min=duration,
        expected_students=session.total,
        peak_offset_min=duration / 2,
        spread_min=duration / 4,
    )
    return slot, start


def find_sessions(scans: list[tuple[datetime, str, str]], mess_ids: list[str]) -> list[Session]:
    sessions: list[Session] = []
    group: list[tuple[datetime, str, str]] = []

    def close():
        if len(group) >= MIN_SESSION_SCANS:
            counts = {m: 0 for m in mess_ids}
            for _, mess, _ in group:
                counts[mess] += 1
            sessions.append(Session(len(sessions), _meal_name(group[0][0]), group[0][0], group[-1][0], counts))

    for row in scans:
        if group and (row[0] - group[-1][0]).total_seconds() > MAX_GAP_MIN * 60:
            close()
            group = []
        group.append(row)
    if group:
        close()
    return sessions


def parse_log(text: str, messes: tuple[MessConfig, ...], salt: bytes, keep_names: bool = False) -> ParsedLog:
    """keep_names: also keep a name column (privacy.show_names). Off by default."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise LogError("The file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    if not headers:
        raise LogError("Couldn't find a header row. The first line should name the columns.")

    t_col = _find(headers, TIME_KEYS)
    d_col = tm_col = None
    if t_col is None:
        d_col = _find(headers, ("date", "day"))
        tm_col = _find(headers, ("time", "punch", "clock"), exclude={d_col} if d_col else set())
        if tm_col is None:
            raise LogError(f"Couldn't find a time column. Columns found: {', '.join(headers)}")
    used = {c for c in (t_col, d_col, tm_col) if c}
    m_col = _find(headers, MESS_KEYS, exclude=used)
    if m_col is None:
        if len(messes) == 1:
            m_col = None
        else:
            raise LogError(f"Couldn't find a mess/device column. Columns found: {', '.join(headers)}")
    used |= {m_col} if m_col else set()
    name_col = _find(headers, NAME_KEYS, exclude=used)
    used |= {name_col} if name_col else set()
    id_col = _find(headers, ID_KEYS, exclude=used)
    used |= {id_col} if id_col else set()
    dir_col = _find(headers, DIR_KEYS, exclude=used)

    rows: list[tuple[datetime, str, str]] = []
    names: dict[str, str] = {}
    raw_mess: set[str] = set()
    skipped = exits = 0
    today = date.today()
    for n, row in enumerate(reader):
        if dir_col and (row.get(dir_col) or "").strip().lower() in EXIT_WORDS:
            exits += 1
            continue
        if t_col:
            ts = _parse_dt(row.get(t_col) or "")
        else:
            tm = _parse_time(row.get(tm_col) or "")
            d = _parse_date(row.get(d_col) or "") if d_col else today
            ts = datetime.combine(d, tm) if tm and d else None
        mess_raw = (row.get(m_col) or "").strip() if m_col else messes[0].id
        if ts is None or not mess_raw:
            skipped += 1
            continue
        raw_id = (row.get(id_col) or "").strip() if id_col else ""
        key = pseudonymise(raw_id or f"row{n}", salt)  # the raw ID is dropped here
        if keep_names and name_col and (nm := (row.get(name_col) or "").strip()):
            names[key] = nm
        rows.append((ts, mess_raw, key))
        raw_mess.add(mess_raw)
    if not rows:
        raise LogError("No rows with a readable time were found. Check the date/time format.")

    mapping = _map_messes(raw_mess, messes)
    scans = sorted({(ts, mapping[m], k) for ts, m, k in rows})  # also drops exact duplicate rows
    warnings = []
    if skipped:
        warnings.append(f"{skipped} rows skipped (unreadable time or missing mess).")
    if exits:
        warnings.append(f"{exits} exit rows ignored (only entries are used).")
    if len(rows) - len(scans):
        warnings.append(f"{len(rows) - len(scans)} duplicate rows removed.")
    columns = {"time": t_col or (f"{d_col} + {tm_col}" if d_col else tm_col), "mess": m_col or "-"}
    if id_col:
        columns["person"] = id_col
    if dir_col:
        columns["in/out"] = dir_col
    if name_col:
        columns["name"] = name_col + ("" if keep_names else " (hidden: privacy.show_names is off)")
    parsed = ParsedLog(scans=scans, names=names, mapping=mapping, columns=columns, skipped=skipped, warnings=warnings)
    parsed.sessions = find_sessions(scans, [m.id for m in messes])
    if not parsed.sessions:
        raise LogError(f"Found {len(scans)} scans but no meal with at least {MIN_SESSION_SCANS} scans.")
    return parsed
