"""Live demo: one simulated meal, run twice side by side (no advice vs advice).

    python -m messq.demo                 # then open http://localhost:8000
    python -m messq.demo --lan           # also reachable from phones on the same Wi-Fi

Pages:  /         pitch dashboard (both worlds, chart, controls)
        /screen   what students would see on the hallway screen / phone
        /kitchen  kitchen staff buttons (tray low / out / refilled)

Standard library only. Everything shown is simulated.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean

from ..config import AppConfig, load_config
from ..engine import Policy
from ..events import FoodSignal, FoodState
from ..simulation import Simulation

STATIC = Path(__file__).resolve().parent / "static"
PAGES = {"/": "index.html", "/screen": "screen.html", "/kitchen": "kitchen.html"}
HISTORY_EVERY_S = 30  # simulated seconds between chart points


class Demo:
    def __init__(self, cfg: AppConfig, slot: str, compliance: float, seed: int, speed: float):
        self.cfg, self.slot_name, self.compliance = cfg, slot, compliance
        self.seed, self.speed = seed, speed
        self.lock = threading.Lock()
        self.reset()

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = seed
        slot = self.cfg.simulation.slot(self.slot_name)
        self.slot = slot
        self.worlds = {
            "none": Simulation(self.cfg, slot, Policy.NONE, self.compliance, self.seed),
            "advised": Simulation(self.cfg, slot, Policy.EQUILIBRIUM, self.compliance, self.seed),
        }
        self.history: dict[str, list[list[float]]] = {k: [] for k in self.worlds}
        self.paused = False
        self._owed = 0.0

    # ---- clock ------------------------------------------------------------
    def tick(self, real_dt: float) -> None:
        with self.lock:
            if self.paused or self.finished:
                return
            self._owed += real_dt * self.speed
            step = self.cfg.simulation.step_s
            while self._owed >= step and not self.finished:
                for w in self.worlds.values():
                    if not w.finished:
                        w.step()
                self._owed -= step
                t = self.worlds["advised"].t
                if int(t) % HISTORY_EVERY_S == 0:
                    for k, w in self.worlds.items():
                        self.history[k].append([round(t / 60, 2), _waiting(w)])

    @property
    def finished(self) -> bool:
        return all(w.finished for w in self.worlds.values())

    # ---- actions ----------------------------------------------------------
    def run_out(self, mess_id: str) -> None:
        with self.lock:
            for w in self.worlds.values():
                w.force_run_out(mess_id)

    def kitchen(self, mess_id: str, state: FoodState) -> None:
        with self.lock:
            w = self.worlds["advised"]  # only the world with the system has a kitchen page
            w.engine.food_signal(FoodSignal(w.t, mess_id, state))

    # ---- view -------------------------------------------------------------
    def state(self) -> dict:
        with self.lock:
            adv = self.worlds["advised"]
            snap = adv.engine.snapshot()
            hh, mm = map(int, self.slot.start.split(":"))
            minutes = hh * 60 + mm + int(adv.t // 60)
            return {
                "slot": self.slot.name,
                "clock": f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}",
                "t_min": round(adv.t / 60, 1),
                "duration_min": self.slot.duration_min,
                "speed": self.speed,
                "paused": self.paused,
                "finished": self.finished,
                "compliance": self.compliance,
                "seed": self.seed,
                "worlds": {k: _world(w, self.history[k]) for k, w in self.worlds.items()},
                "advice": {
                    "text": snap.advice,
                    "headline": snap.headline.mess_id,
                    "halls": [
                        {
                            "id": h.mess_id,
                            "name": h.name,
                            "wait_min": round(h.wait.wait, 1),
                            "status": h.status.value,
                            "share": round(h.share, 3),
                            "occupancy": h.occupancy,
                            "seats": h.seats,
                            "rate": round(h.arrival_rate, 1),
                            "food": h.food.value,
                        }
                        for h in snap.halls
                    ],
                },
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
            path = self.path.split("?")[0]
            if path in PAGES:
                self._send(200, (STATIC / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(demo.state())
            elif path == "/api/config":
                self._json({"messes": [{"id": m.id, "name": m.name} for m in demo.cfg.messes]})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            path = self.path.split("?")[0]
            ids = {m.id for m in demo.cfg.messes}
            if path == "/api/control":
                action = body.get("action")
                with demo.lock:
                    if action == "pause":
                        demo.paused = True
                    elif action == "resume":
                        demo.paused = False
                    elif action == "speed":
                        demo.speed = max(1.0, min(600.0, float(body.get("value", 60))))
                    elif action == "compliance":
                        demo.compliance = max(0.0, min(1.0, float(body.get("value", 0.6))))
                if action == "reset":
                    with demo.lock:
                        demo.reset(seed=int(body["seed"]) if "seed" in body else demo.seed + 1)
            elif path == "/api/runout" and body.get("mess") in ids:
                demo.run_out(body["mess"])
            elif path == "/api/kitchen" and body.get("mess") in ids and body.get("state") in ("ok", "low", "out"):
                demo.kitchen(body["mess"], FoodState(body["state"]))
            else:
                return self._json({"error": "bad request"}, 400)
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
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    demo = Demo(cfg, args.slot, args.compliance if args.compliance is not None else cfg.simulation.compliance, args.seed, args.speed)

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
    print(f"Mess queue demo running ({args.slot}, {args.speed:g}x speed). Open:")
    print(f"  Pitch dashboard   http://localhost:{args.port}/")
    print(f"  Student screen    http://localhost:{args.port}/screen")
    print(f"  Kitchen buttons   http://localhost:{args.port}/kitchen")
    if args.lan and (ip := _lan_ip()):
        print(f"  From a phone on the same Wi-Fi: http://{ip}:{args.port}/screen")
    print("Ctrl+C to stop. Everything shown is simulated data.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
