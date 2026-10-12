"""Live demo: one meal, run twice side by side (no advice vs advice).

    python -m messq.demo                 # then open http://localhost:8000
    python -m messq.demo --lan           # also reachable from phones on the same Wi-Fi

Pages:  /                  pitch dashboard (both worlds, chart, timeline, upload)
        /screen?at=A       the screen outside Mess A (what students see)
        /kitchen?mess=A    kitchen staff: tray low / out / refilled, per tray

The meal is either simulated or replayed from an uploaded scanner log (CSV).
Uploaded files are parsed in memory and never written to disk; raw IDs are
hashed as rows are read. Standard library only.
"""

from __future__ import annotations

import argparse
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
from ..logs import LogError, ParsedLog, parse_log, replay_slot
from ..simulation import Simulation

STATIC = Path(__file__).resolve().parent / "static"
PAGES = {"/": "index.html", "/screen": "screen.html", "/kitchen": "kitchen.html"}
HISTORY_EVERY_S = 30  # simulated seconds between chart points
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TAIL_MIN = 30  # the timeline runs this long past the meal so queues can drain


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

    def __init__(self, cfg: AppConfig, slot: str, compliance: float, seed: int, speed: float):
        self.cfg, self.compliance, self.seed, self.speed = cfg, compliance, seed, speed
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
                self.history[k].append([round(self.t / 60, 2), _waiting(w)])

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
        log = parse_log(text, self.cfg.messes, self._salt)
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

    # ---- view -------------------------------------------------------------
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
            kitchen = {
                m.id: [
                    {"item": item, "state": st.value, "since": self.clock(ts) if ts > -1e8 else None,
                     "mins_ago": round((self.t - ts) / 60) if ts > -1e8 else None}
                    for item, st, ts in eng.trays(m.id, self.t)
                ]
                for m in self.cfg.messes
            }
            feed = [
                {"clock": self.clock(sig.ts), "mess": names[sig.mess_id],
                 "item": sig.item or ("all trays" if sig.state is FoodState.OK else self.cfg.mess(sig.mess_id).items[0]),
                 "state": sig.state.value}
                for sig in list(eng.kitchen_log)[-8:][::-1]
            ]
            replay = self.source["type"] == "replay"
            return {
                "mode": self.cfg.layout.mode,
                "switch_walk_s": self.cfg.layout.switch_walk_s,
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
                "actions": [{"clock": self.clock(a.t), "kind": a.kind, "mess": names[a.mess]} for a in self.actions[-6:]],
            }


def _waiting(w: Simulation) -> int:
    return sum(len(h.queue) + len(h.seat_queue) for h in w.halls.values())


def _world(w: Simulation, history: list) -> dict:
    waits = [(s.seated_at - s.arrived_at) / 60 for s in w.students if s.seated_at is not None]
    return {
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
                "queue": len(h.queue) + len(h.seat_queue),
                "inside": h.true_in_hall(),
                "seats": h.cfg.seats,
                "food": "out" if h.stock <= 0 else ("low" if h.stock <= h.cfg.food_refill_trigger else "ok"),
                "students": sum(s.hall == h.cfg.id for s in w.students),
            }
            for h in w.halls.values()
        ],
        "history": history,
    }


def make_handler(demo: Demo):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet during a pitch
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in PAGES:
                self._send(200, (STATIC / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(demo.state())
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
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
                    demo.kitchen(body["mess"], item, FoodState(body["state"]))
                else:
                    raise ValueError("bad request")
            except (ValueError, KeyError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            self._json({"ok": True})

    return Handler


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
    p.add_argument("--log", help="start by replaying this scanner log (CSV)")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    demo = Demo(cfg, args.slot, args.compliance if args.compliance is not None else cfg.simulation.compliance, args.seed, args.speed)
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

    threading.Thread(target=clock, daemon=True).start()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(demo))
    first = cfg.messes[0].id
    print(f"Mess queue demo running ({cfg.layout.mode} layout, {args.speed:g}x speed). Open:")
    print(f"  Pitch dashboard          http://localhost:{args.port}/")
    print(f"  Screen outside {cfg.messes[0].name:9s} http://localhost:{args.port}/screen?at={first}")
    print(f"  Kitchen buttons          http://localhost:{args.port}/kitchen")
    if args.lan and (ip := _lan_ip()):
        print(f"  From a phone on the same Wi-Fi: http://{ip}:{args.port}/screen?at={first}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
