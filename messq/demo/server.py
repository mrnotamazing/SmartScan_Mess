"""Live demo: one meal, run twice side by side (no advice vs advice).

    python -m messq.demo                 # then open http://localhost:8000
    python -m messq.demo --lan           # also reachable from phones on the same Wi-Fi

Who sees what (see auth.py):
  anyone           /                 student page for phones: which mess is faster right now
                   /screen?at=A      the display outside a mess (A = Central, B = Munch)
  kitchen login    /kitchen?mess=A   tray low / out / refilled, per tray
  manager login    /manager          pitch dashboard (both worlds, chart, timeline, upload)
                   /sheet            live spreadsheet: scan log per mess + counts per 30 min
                   /kitchen          (managers can use the kitchen page too)

The meal is either simulated or replayed from an uploaded scanner log (CSV).
Uploaded files are parsed in memory and never written to disk; raw IDs are
hashed as rows are read. Standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from urllib.parse import parse_qs, urlparse

from ..config import AppConfig, load_config
from ..engine import Policy
from ..events import FoodSignal, FoodState
from ..menu import DayMenu, load_menu
from ..logs import LogError, ParsedLog, parse_log, replay_slot
from ..sheets import LOG_HEADER, compare_wait_rows, log_rows, summary_rows, to_csv, workbook
from ..simulation import Simulation
from .auth import ENV as AUTH_ENV
from .auth import Auth

STATIC = Path(__file__).resolve().parent / "static"
PUBLIC, KITCHEN, MANAGER = frozenset(), frozenset({"kitchen", "manager"}), frozenset({"manager"})
PAGES = {  # path -> (file, roles allowed; empty = anyone)
    "/": ("student.html", PUBLIC),
    "/screen": ("screen.html", PUBLIC),
    "/login": ("login.html", PUBLIC),
    "/kitchen": ("kitchen.html", KITCHEN),
    "/manager": ("index.html", MANAGER),
    "/sheet": ("sheet.html", MANAGER),
}
GET_APIS = {"/api/public": PUBLIC, "/api/me": PUBLIC, "/api/kitchen-state": KITCHEN, "/api/state": MANAGER,
            "/api/sheet": MANAGER, "/api/export.xlsx": MANAGER, "/api/export.csv": MANAGER}
POST_APIS = {"/api/login": PUBLIC, "/api/logout": PUBLIC, "/api/kitchen": KITCHEN, "/api/kitchen-review": MANAGER, "/api/upload": MANAGER,
             "/api/control": MANAGER, "/api/source": MANAGER, "/api/runout": MANAGER}
HOME = {"manager": "/manager", "kitchen": "/kitchen"}
INTERVALS = (5, 10, 15, 30, 60)
HISTORY_EVERY_S = 30  # simulated seconds between chart points
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TAIL_MIN = 0  # the timeline ends when the mess closes (lunch 11:30-14:30)


@dataclass
class Action:
    t: float  # simulated seconds
    kind: str  # "runout" | "kitchen"
    mess: str
    item: str | None = None
    state: str | None = None


class Demo:
    """Holds both worlds. Every user action is recorded with its simulated time,
    so jumping backwards rebuilds the meal and replays the actions exactly."""

    def __init__(self, cfg: AppConfig, slot: str, compliance: float, seed: int, speed: float, menu: DayMenu | None = None):
        self.cfg, self.compliance, self.seed, self.speed = cfg, compliance, seed, speed
        self.menu = menu or DayMenu()
        # Tray reports from the kitchen page wait here until a manager approves them.
        self.pending: list[dict] = []
        self._next_request = 1
        self.lock = threading.RLock()
        self.source: dict = {"type": "sim", "slot": slot}
        self.log: ParsedLog | None = None
        self.actions: list[Action] = []
        self.paused = False
        # Uploaded logs live only in memory, so a per-run salt is enough for the demo.
        self._salt = os.environ.get(cfg.privacy.salt_env, "").encode() or secrets.token_bytes(32)
        self._build()

    # ---- building ---------------------------------------------------------
    def _build(self) -> None:
        arrivals = natural = None
        if self.source["type"] == "replay" and self.log:
            sess = self.log.sessions[self.source["session"]]
            self.slot, start = replay_slot(sess)
            arrivals = self.log.arrivals(sess, start)
            natural = {k: v / sess.total for k, v in sess.counts.items()}
            self.source_label = f"Replay: {sess.label()}"
        else:
            self.slot = self.cfg.simulation.slot(self.source["slot"])
            self.source_label = f"Simulated {self.slot.name} (day {self.seed})"
        self.worlds = {
            "none": Simulation(self.cfg, self.slot, Policy.NONE, self.compliance, self.seed, arrivals),
            "advised": Simulation(self.cfg, self.slot, Policy.EQUILIBRIUM, self.compliance, self.seed, arrivals),
        }
        if natural:
            for w in self.worlds.values():
                w.engine.natural = natural
        self.history: dict[str, list[list[float]]] = {k: [] for k in self.worlds}
        self._next_action = 0
        self._owed = 0.0

    @property
    def t(self) -> float:
        return self.worlds["advised"].t

    @property
    def max_t(self) -> float:
        return (self.slot.duration_min + TAIL_MIN) * 60

    @property
    def finished(self) -> bool:
        return self.t >= self.max_t or all(w.finished for w in self.worlds.values())

    def _apply(self, a: Action) -> None:
        if a.kind == "runout":
            for w in self.worlds.values():
                w.force_run_out(a.mess)
        elif a.kind == "kitchen":
            w = self.worlds["advised"]  # only the world with the system has a kitchen page
            w.engine.food_signal(FoodSignal(w.t, a.mess, FoodState(a.state), a.item))

    def _step(self) -> None:
        while self._next_action < len(self.actions) and self.actions[self._next_action].t <= self.t:
            self._apply(self.actions[self._next_action])
            self._next_action += 1
        for w in self.worlds.values():
            if not w.finished:
                w.step()
            else:
                w.t += self.cfg.simulation.step_s  # keep both clocks together
        if int(self.t) % HISTORY_EVERY_S == 0:
            for k, w in self.worlds.items():
                self.history[k].append([round(self.t / 60, 2), _waiting(w), _recent_wait(w)])

    def _record(self, action: Action) -> None:
        """Store a live action at the current time (dropping any 'future' ones
        left over from before a jump back) and apply it now."""
        self.actions = [a for a in self.actions if a.t <= self.t]
        self.actions.append(action)
        self._next_action = len(self.actions)
        self._apply(action)

    # ---- clock ------------------------------------------------------------
    def tick(self, real_dt: float) -> None:
        with self.lock:
            if self.paused or self.finished:
                return
            self._owed += real_dt * self.speed
            step = self.cfg.simulation.step_s
            while self._owed >= step and not self.finished:
                self._step()
                self._owed -= step

    def seek(self, target_s: float) -> None:
        with self.lock:
            target_s = max(0.0, min(self.max_t, target_s))
            if target_s < self.t:
                self._build()
            while self.t + 1e-9 < target_s and not self.finished:
                self._step()
            self._owed = 0.0

    # ---- actions ----------------------------------------------------------
    def run_out(self, mess_id: str) -> None:
        with self.lock:
            self._record(Action(self.t, "runout", mess_id))

    def kitchen(self, mess_id: str, item: str | None, state: FoodState) -> None:
        with self.lock:
            self._record(Action(self.t, "kitchen", mess_id, item, state.value))

    def request(self, mess_id: str, item: str | None, state: FoodState) -> dict:
        """A kitchen-page report: held until a manager approves it. A newer report
        for the same tray replaces the older one."""
        with self.lock:
            self.pending = [p for p in self.pending if (p["mess"], p["item"]) != (mess_id, item)]
            req = {"id": self._next_request, "t": self.t, "mess": mess_id, "item": item, "state": state.value}
            self._next_request += 1
            self.pending.append(req)
            return req

    def review(self, request_id: int, approve: bool) -> bool:
        with self.lock:
            req = next((p for p in self.pending if p["id"] == request_id), None)
            if req is None:
                return False
            self.pending.remove(req)
            if approve:
                self.kitchen(req["mess"], req["item"], FoodState(req["state"]))
            return True

    def set_compliance(self, value: float) -> None:
        with self.lock:
            self.compliance = value
            t = self.t
            self._build()
            self.seek(t)

    def new_day(self) -> None:
        with self.lock:
            self.seed += 1
            self.actions = []
            self.pending = []
            self._build()

    def set_source(self, source: dict) -> None:
        with self.lock:
            if source.get("type") == "replay":
                if not self.log or not 0 <= int(source.get("session", -1)) < len(self.log.sessions):
                    raise ValueError("no such meal in the uploaded log")
                self.source = {"type": "replay", "session": int(source["session"])}
            else:
                self.cfg.simulation.slot(source.get("slot", ""))  # raises KeyError if unknown
                self.source = {"type": "sim", "slot": source["slot"]}
            self.actions = []
            self._build()

    def upload(self, text: str) -> dict:
        log = parse_log(text, self.cfg.messes, self._salt, keep_names=self.cfg.privacy.show_names)
        with self.lock:
            self.log = log
            busiest = max(log.sessions, key=lambda s: s.total)
            self.source = {"type": "replay", "session": busiest.index}
            self.actions = []
            self._build()
        return self._log_info()

    def _log_info(self) -> dict | None:
        if not self.log:
            return None
        names = {m.id: m.name for m in self.cfg.messes}
        return {
            "sessions": [{"index": s.index, "label": s.label()} for s in self.log.sessions],
            "mapping": {raw: names[mid] for raw, mid in self.log.mapping.items()},
            "columns": self.log.columns,
            "warnings": self.log.warnings,
            "scans": len(self.log.scans),
        }

    # ---- spreadsheet --------------------------------------------------------
    def default_world(self) -> str:
        return "none" if self.source["type"] == "replay" else "advised"

    def _world_for(self, world: str | None) -> Simulation:
        return self.worlds[world if world in self.worlds else self.default_world()]

    def sheet(self, world: str | None, interval: int) -> dict:
        with self.lock:
            sim = self._world_for(world)
            header, rows = summary_rows(sim, interval)
            return {
                "clock": self.clock(self.t),
                "source": self.source_label,
                "world": world if world in self.worlds else self.default_world(),
                "titles": {"none": "As it happened" if self.source["type"] == "replay" else "Without screens",
                           "advised": "With screens"},
                "messes": [{"id": m.id, "name": m.name} for m in self.cfg.messes],
                "log_header": LOG_HEADER,
                "logs": {m.id: log_rows(sim, m.id) for m in self.cfg.messes},
                "summary_header": header,
                "summary": rows,
                "interval": interval,
                **dict(zip(("compare_header", "compare"), self._compare(interval))),
            }

    def _compare(self, interval: int) -> tuple[list[str], list[list]]:
        title = "As it happened" if self.source["type"] == "replay" else "Without the system"
        return compare_wait_rows(self.worlds["none"], self.worlds["advised"], interval, title)

    def export_xlsx(self, world: str | None, interval: int) -> bytes:
        with self.lock:
            return workbook(self._world_for(world), interval, self._compare(interval))

    def export_csv(self, world: str | None, interval: int, which: str) -> tuple[str, str]:
        with self.lock:
            sim = self._world_for(world)
            if which in {m.id for m in self.cfg.messes}:
                name = self.cfg.mess(which).name
                return f"{name} log", to_csv(LOG_HEADER, log_rows(sim, which))
            if which == "compare":
                return "Wait with vs without", to_csv(*self._compare(interval))
            header, rows = summary_rows(sim, interval)
            return f"Every {interval} min", to_csv(header, rows)

    def write_files(self, folder: Path, interval: int) -> None:
        """Keep spreadsheet files on disk up to date (for people who'd rather open Excel)."""
        folder.mkdir(parents=True, exist_ok=True)
        files = {f"{m.name.lower().replace(' ', '_')}_log.csv": self.export_csv(None, interval, m.id)[1] for m in self.cfg.messes}
        files[f"every_{interval}_min.csv"] = self.export_csv(None, interval, "summary")[1]
        files["wait_with_vs_without.csv"] = self.export_csv(None, interval, "compare")[1]
        files_b = {k: v.encode("utf-8-sig") for k, v in files.items()}
        files_b["mess_logs.xlsx"] = self.export_xlsx(None, interval)
        for fname, data in files_b.items():
            try:
                _write_atomic(folder / fname, data)
            except PermissionError:
                pass  # open in Excel on Windows (locked); the next minute's write catches up

    # ---- view -------------------------------------------------------------
    def public_state(self) -> dict:
        """What anyone may see: aggregate busyness per mess and the screen advice.
        No names, no logs, no controls."""
        s = self.state()
        return {
            "clock": s["clock"],
            "mode": s["mode"],
            "switch_walk_s": s["switch_walk_s"],
            "min_saving_min": self.cfg.layout.min_saving_min,
            "doors": s["doors"],
            "advice": s["advice"],
        }

    def kitchen_state(self) -> dict:
        s = self.state()
        return {
            "clock": s["clock"],
            "advice": {"halls": [{"id": h["id"], "name": h["name"], "food": h["food"]} for h in s["advice"]["halls"]]},
            "kitchen": s["kitchen"],
            "kitchen_feed": s["kitchen_feed"],
            "menu": s["menu"],
            "pending": s["pending"],
        }

    def _tray_label(self, item: str) -> str:
        dish = self.menu.dish(item)
        return f"{item} ({dish})" if dish else item

    def clock(self, t_s: float) -> str:
        hh, mm = map(int, self.slot.start.split(":"))
        minutes = hh * 60 + mm + int(t_s // 60)
        return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"

    def state(self) -> dict:
        with self.lock:
            adv = self.worlds["advised"]
            eng = adv.engine
            snap = eng.snapshot()
            names = {m.id: m.name for m in self.cfg.messes}
            halls = []
            for h in snap.halls:
                halls.append(
                    {
                        "id": h.mess_id,
                        "name": h.name,
                        "wait_min": round(h.wait.wait, 1),
                        "to_food_min": round(h.wait.wait + h.wait.service, 1),
                        "visit_min": round(h.visit_min, 1),
                        "scanner_load": round(h.scanner_load, 3),
                        "status": h.status.value,
                        "share": round(h.share, 3),
                        "occupancy": h.occupancy,
                        "seats": h.seats,
                        "space": h.space,
                        "seats_free_per_min": round(h.seats / self.cfg.engine.stay_mean_min),
                        "load": round(h.load, 3),
                        "rate": round(h.arrival_rate, 1),
                        "food": h.food.value,
                        "fresh": h.fresh,
                    }
                )
            doors = {
                d.at: {
                    "at": d.at,
                    "go_to": d.go_to,
                    "go_to_name": names.get(d.go_to) if d.go_to else None,
                    "level": d.level,
                    "p_switch": round(d.p_switch, 3),
                    "saving_min": round(d.saving_min, 1),
                }
                for d in snap.doors.values()
            }
            waiting = {(p["mess"], p["item"]): p for p in self.pending}
            kitchen = {
                m.id: [
                    {"item": item, "dish": self.menu.dish(item), "main": item == m.items[0],
                     "pending": waiting[(m.id, item)]["state"] if (m.id, item) in waiting else None,
                     "state": st.value, "since": self.clock(ts) if ts > -1e8 else None,
                     "mins_ago": round((self.t - ts) / 60) if ts > -1e8 else None}
                    for item, st, ts in eng.trays(m.id, self.t)
                    if self.menu.served(item)
                ]
                for m in self.cfg.messes
            }
            feed = [
                {"clock": self.clock(sig.ts), "mess": names[sig.mess_id],
                 "item": self._tray_label(sig.item or ("all trays" if sig.state is FoodState.OK else self.cfg.mess(sig.mess_id).items[0])),
                 "state": sig.state.value}
                for sig in list(eng.kitchen_log)[-8:][::-1]
            ]
            replay = self.source["type"] == "replay"
            return {
                "mode": self.cfg.layout.mode,
                "switch_walk_s": self.cfg.layout.switch_walk_s,
                "normal_visit_min": self.cfg.engine.normal_visit_min,
                "slot": self.slot.name,
                "source": {**self.source, "label": self.source_label},
                "slots": [s.name for s in self.cfg.simulation.slots],
                "log": self._log_info(),
                "clock": self.clock(self.t),
                "start_clock": self.slot.start,
                "t_min": round(self.t / 60, 2),
                "duration_min": self.slot.duration_min,
                "max_t_min": self.max_t / 60,
                "speed": self.speed,
                "paused": self.paused,
                "finished": self.finished,
                "compliance": self.compliance,
                "seed": self.seed,
                "titles": {
                    "none": "As it happened (arrivals from your log)" if replay else "Without the system (today)",
                    "advised": "Same students, with the screens",
                },
                "worlds": {k: _world(w, self.history[k]) for k, w in self.worlds.items()},
                "advice": {"text": snap.advice, "headline": snap.headline.mess_id, "halls": halls},
                "doors": doors,
                "kitchen": kitchen,
                "kitchen_feed": feed,
                "menu": {"day": self.menu.day.title(), "theme": self.menu.theme},
                "pending": [
                    {"id": p["id"], "clock": self.clock(p["t"]), "mins_ago": round((self.t - p["t"]) / 60),
                     "mess": p["mess"], "mess_name": names[p["mess"]], "state": p["state"],
                     "item": self._tray_label(p["item"] or ("all trays" if p["state"] == "ok" else self.cfg.mess(p["mess"]).items[0]))}
                    for p in self.pending
                ],
                "actions": [{"clock": self.clock(a.t), "kind": a.kind, "mess": names[a.mess]} for a in self.actions[-6:]],
            }


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, path)
    except PermissionError:  # target open in another program (Windows)
        tmp.unlink(missing_ok=True)
        raise


WAIT_WINDOW_S = 300  # the wait chart averages over students who got food in the last 5 min


def _recent_wait(w: Simulation) -> float:
    """Average wait (door to food) of students who got food in the last 5 minutes."""
    lo = w.t - WAIT_WINDOW_S
    waits = [(s.seated_at - s.arrived_at) / 60 for s in reversed(w.students)
             if s.seated_at is not None and lo < s.seated_at <= w.t]
    return round(mean(waits), 1) if waits else 0.0


def _waiting(w: Simulation) -> int:
    """Everyone waiting: outside for the scanner, for food, or for a seat."""
    return sum(h.outside_queue() + len(h.queue) + len(h.seat_queue) for h in w.halls.values())


def _counts(students, t: float) -> dict:
    """Where everyone is right now: arrived at a door -> scanned -> got food -> left."""
    arrived = scanned = served = left = 0
    for s in students:
        if s.arrived_at > t:
            continue  # still walking
        arrived += 1
        if s.scanned_at is not None:
            scanned += 1
        if s.seated_at is not None:
            served += 1
            if s.left_at is not None and s.left_at <= t:
                left += 1
    return {"arrived": arrived, "scanned": scanned, "served": served, "eating": served - left, "left": left}


def _world(w: Simulation, history: list) -> dict:
    waits = [(s.seated_at - s.arrived_at) / 60 for s in w.students if s.seated_at is not None]
    return {
        "expected": w.slot.expected_students,
        **_counts(w.students, w.t),
        "students": len(w.students),
        "seated": len(waits),
        "avg_wait": round(mean(waits), 1) if waits else 0.0,
        "long_waits": sum(x > 10 for x in waits),
        "switched": sum(s.hall != s.habit for s in w.students),
        "waiting_now": _waiting(w),
        "outages": sum(h.outages for h in w.halls.values()),
        "halls": [
            {
                "id": h.cfg.id,
                "name": h.cfg.name,
                "queue": h.outside_queue() + len(h.queue) + len(h.seat_queue),
                "outside": h.outside_queue(),
                "inside": h.true_in_hall(),
                "seats": h.cfg.seats,
                "food": "out" if h.stock <= 0 else ("low" if h.stock <= h.cfg.food_refill_trigger else "ok"),
                "students": sum(s.hall == h.cfg.id for s in w.students),
                **_counts([s for s in w.students if s.hall == h.cfg.id], w.t),
                "outside_q": h.outside_queue(),
                "food_q": len(h.queue),
                "seat_q": len(h.seat_queue),
            }
            for h in w.halls.values()
        ],
        "history": history,
    }


def make_handler(demo: Demo, auth: Auth):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet during a pitch
            pass

        def _headers(self, code: int, ctype: str, length: int, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(length))
            self.end_headers()

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self._headers(code, ctype, len(body), extra)
            self.wfile.write(body)

        def _download(self, body: bytes, filename: str, ctype: str) -> None:
            self._send(200, body, ctype, {"Content-Disposition": f'attachment; filename="{filename}"'})

        def _json(self, obj, code: int = 200, extra: dict | None = None) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json", extra)

        def _redirect(self, to: str, extra: dict | None = None) -> None:
            self._send(303, b"", "text/plain", {"Location": to, **(extra or {})})

        @property
        def role(self) -> str | None:
            return auth.role_from(self.headers.get("Cookie"))

        def _allowed(self, roles: frozenset) -> bool:
            return not roles or self.role in roles

        def do_GET(self):
            url = urlparse(self.path)
            path, q = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
            if path == "/logout":
                return self._redirect("/login", {"Set-Cookie": auth.clear_cookie()})
            if path in PAGES:
                fname, roles = PAGES[path]
                if not self._allowed(roles):
                    if self.role is None:
                        return self._redirect(f"/login?next={path}")
                    return self._send(403, _forbidden_page(self.role), "text/html; charset=utf-8")
                return self._send(200, (STATIC / fname).read_bytes(), "text/html; charset=utf-8")
            if path not in GET_APIS:
                return self._send(404, b"not found", "text/plain")
            if not self._allowed(GET_APIS[path]):
                return self._json({"error": "login required"}, 401)
            interval = int(q.get("interval", 30)) if q.get("interval", "30").isdigit() else 30
            interval = interval if interval in INTERVALS else 30
            world = q.get("world")
            if path == "/api/public":
                self._json(demo.public_state())
            elif path == "/api/me":
                self._json({"role": self.role})
            elif path == "/api/kitchen-state":
                self._json(demo.kitchen_state())
            elif path == "/api/state":
                self._json(demo.state())
            elif path == "/api/sheet":
                self._json(demo.sheet(world, interval))
            elif path == "/api/export.xlsx":
                self._download(demo.export_xlsx(world, interval), "mess_logs.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            elif path == "/api/export.csv":
                title, text = demo.export_csv(world, interval, q.get("sheet", "summary"))
                self._download(text.encode("utf-8-sig"), title.lower().replace(" ", "_") + ".csv", "text/csv; charset=utf-8")

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in POST_APIS:
                return self._json({"error": "not found"}, 404)
            # Our pages send this header; another website can't make a browser add it
            # without permission we never give, which blocks cross-site requests.
            if self.headers.get("X-Messq") != "1":
                return self._json({"error": "missing X-Messq header"}, 403)
            if not self._allowed(POST_APIS[path]):
                return self._json({"error": "login required"}, 401)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                return self._json({"error": "File is larger than 20 MB. Export a single day."}, 413)
            raw = self.rfile.read(length)
            if path == "/api/upload":
                try:
                    return self._json({"ok": True, "log": demo.upload(raw.decode("utf-8-sig", errors="replace"))})
                except LogError as e:
                    return self._json({"error": str(e)}, 400)
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            if path == "/api/login":
                addr = self.client_address[0]
                if auth.blocked(addr):
                    return self._json({"error": "Too many attempts. Wait 5 minutes."}, 429)
                role = auth.login(addr, str(body.get("password", "")))
                if role is None:
                    return self._json({"error": "Wrong password."}, 401)
                nxt = str(body.get("next") or "")
                if nxt not in PAGES or role not in PAGES[nxt][1]:
                    nxt = HOME[role]
                return self._json({"ok": True, "role": role, "next": nxt}, extra={"Set-Cookie": auth.make_cookie(role)})
            if path == "/api/logout":
                return self._json({"ok": True}, extra={"Set-Cookie": auth.clear_cookie()})
            ids = {m.id for m in demo.cfg.messes}
            try:
                if path == "/api/control":
                    action, value = body.get("action"), body.get("value")
                    if action == "pause":
                        demo.paused = True
                    elif action == "resume":
                        demo.paused = False
                    elif action == "speed":
                        demo.speed = max(1.0, min(600.0, float(value)))
                    elif action == "seek":
                        demo.seek(float(value) * 60)
                    elif action == "jump":
                        demo.seek(demo.t + float(value) * 60)
                    elif action == "compliance":
                        demo.set_compliance(max(0.0, min(1.0, float(value))))
                    elif action == "reset":
                        demo.new_day()
                    else:
                        raise ValueError("unknown action")
                elif path == "/api/source":
                    demo.set_source(body)
                elif path == "/api/runout" and body.get("mess") in ids:
                    demo.run_out(body["mess"])
                elif path == "/api/kitchen" and body.get("mess") in ids and body.get("state") in ("ok", "low", "out"):
                    item = body.get("item")
                    if item is not None and item not in demo.cfg.mess(body["mess"]).items:
                        raise ValueError("unknown tray")
                    # Kitchen staff (and anyone using the kitchen page) send a request that a
                    # manager approves on the dashboard; a manager's own tap applies at once.
                    if self.role != "manager" or body.get("request"):
                        req = demo.request(body["mess"], item, FoodState(body["state"]))
                        return self._json({"ok": True, "pending": True, "id": req["id"]})
                    demo.kitchen(body["mess"], item, FoodState(body["state"]))
                elif path == "/api/kitchen-review":
                    if not demo.review(int(body["id"]), bool(body.get("approve"))):
                        return self._json({"error": "That request was already handled."}, 409)
                else:
                    raise ValueError("bad request")
            except (ValueError, KeyError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            self._json({"ok": True})

    return Handler


def _forbidden_page(role: str) -> bytes:
    home = HOME.get(role, "/")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Not Allowed</title>'
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:520px;margin:12vh auto;padding:0 16px;"
        "background:#f4f3f0;color:#0b0b0b}@media(prefers-color-scheme:dark){body{background:#111110;color:#f0efec}}"
        "a{color:#2a78d6}</style></head><body>"
        f"<h1>This page is for managers</h1><p>You're logged in as <b>{role}</b> staff, which can only open "
        f'the kitchen page.</p><p><a href="{home}">Back to the {role} page</a> · <a href="/logout">Log in as someone else</a></p>'
        "</body></html>"
    ).encode()


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--slot", default="lunch")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--lan", action="store_true", help="listen on all interfaces so phones on the same Wi-Fi can connect")
    p.add_argument("--speed", type=float, default=60, help="simulated seconds per real second (60 = 1 min per s)")
    p.add_argument("--compliance", type=float, help="share of students who follow advice (default from config)")
    p.add_argument("--seed", type=int, default=2)
    p.add_argument("--menu-day", help="which day's lunch menu the kitchen page shows (default: today), e.g. wednesday")
    p.add_argument("--log", help="start by replaying this scanner log (CSV)")
    p.add_argument("--show-names", action="store_true",
                   help="show names from uploaded logs in the live sheet (same as privacy.show_names = true)")
    p.add_argument("--save-sheets", metavar="FOLDER", nargs="?", const="live_sheets",
                   help="keep Excel/CSV copies of the live sheets in FOLDER, rewritten every minute (default folder: live_sheets)")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    if args.show_names:
        cfg = dataclasses.replace(cfg, privacy=dataclasses.replace(cfg.privacy, show_names=True))
    demo = Demo(cfg, args.slot, args.compliance if args.compliance is not None else cfg.simulation.compliance, args.seed, args.speed,
                load_menu(args.menu_day))
    if demo.menu.dishes:
        print(f"Kitchen trays use the {demo.menu.day.title()} lunch menu ({demo.menu.theme}) from config/menu.toml")
    if args.log:
        info = demo.upload(Path(args.log).read_text(encoding="utf-8-sig", errors="replace"))
        print(f"Loaded {info['scans']} scans; meals found: " + "; ".join(s["label"] for s in info["sessions"]))

    def clock():
        last = time.monotonic()
        while True:
            time.sleep(0.1)
            now = time.monotonic()
            demo.tick(now - last)
            last = now

    auth = Auth()
    threading.Thread(target=clock, daemon=True).start()
    if args.save_sheets:
        folder = Path(args.save_sheets)

        def saver():
            while True:
                try:
                    demo.write_files(folder, 30)
                except OSError as e:
                    print(f"Couldn't update the sheet files: {e}")
                time.sleep(60)

        threading.Thread(target=saver, daemon=True).start()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(demo, auth))
    base = f"http://localhost:{args.port}"
    print(f"Mess queue demo running ({cfg.layout.mode} layout, {args.speed:g}x speed).\n")
    print("For students (no login):")
    print(f"  Phone page                    {base}/")
    for m in cfg.messes:
        print(f"  {'Screen outside ' + m.name:30s}{base}/screen?at={m.id}")
    print("\nFor staff (login):")
    print(f"  Manager dashboard             {base}/manager")
    print(f"  Live spreadsheet              {base}/sheet")
    print(f"  Kitchen trays                 {base}/kitchen")
    print("\nPasswords:")
    for role in ("manager", "kitchen"):
        if role in auth.generated:
            print(f"  {role:8s} {auth.generated[role]}   (made up for this run; set {AUTH_ENV[role]} to choose your own)")
        else:
            print(f"  {role:8s} from {AUTH_ENV[role]}")
    if auth.shared:
        print("  (same password for both: everyone who logs in gets the full manager view)")
    if args.lan and (ip := _lan_ip()):
        print(f"\nFrom phones on the same Wi-Fi: http://{ip}:{args.port}/")
    if args.save_sheets:
        print(f"\nSheet files (every minute): {Path(args.save_sheets).resolve()}")
    print("\nCtrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
