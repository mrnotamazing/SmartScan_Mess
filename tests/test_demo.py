import json

import pytest
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from messq.config import load_config
from messq.demo.server import Demo, make_handler


def _call(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data else "GET")
    with urllib.request.urlopen(req) as r:
        return r.read()


def test_demo_server_end_to_end():
    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(demo))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        demo.tick(40)  # 40 s real at 60x = 40 simulated minutes
        state = json.loads(_call(port, "/api/state"))
        assert state["t_min"] >= 39
        a, n = state["worlds"]["advised"], state["worlds"]["none"]
        assert a["students"] == n["students"] > 0  # same students in both worlds
        assert len(a["history"]) == len(n["history"]) > 0
        _call(port, "/api/runout", {"mess": "A"})
        _call(port, "/api/kitchen", {"mess": "B", "state": "low"})
        state = json.loads(_call(port, "/api/state"))
        foods = {h["id"]: h["food"] for h in state["advice"]["halls"]}
        assert foods == {"A": "out", "B": "low"}
        for page in ("/", "/screen", "/kitchen"):
            assert b"<html" in _call(port, page)
        _call(port, "/api/control", {"action": "reset"})
        assert json.loads(_call(port, "/api/state"))["t_min"] == 0
    finally:
        server.shutdown()


def test_demo_seek_back_replays_actions_and_upload():
    from pathlib import Path

    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    demo.seek(30 * 60)
    demo.run_out("A")
    demo.seek(50 * 60)
    before = demo.state()["worlds"]["advised"]
    demo.seek(10 * 60)
    assert demo.state()["t_min"] == pytest.approx(10, abs=0.1)
    demo.seek(50 * 60)  # rebuilt from scratch, run-out at 12:00+30 replayed
    after = demo.state()["worlds"]["advised"]
    assert after["avg_wait"] == before["avg_wait"] and after["outages"] == before["outages"]

    sample = Path(__file__).resolve().parent.parent / "samples" / "sample_day_log.csv"
    info = demo.upload(sample.read_text())
    assert len(info["sessions"]) == 3
    st = demo.state()
    assert st["source"]["type"] == "replay" and st["slot"] == "lunch"
    demo.kitchen("B", "Rice", __import__("messq.events", fromlist=["FoodState"]).FoodState.LOW)
    trays = {t["item"]: t["state"] for t in demo.state()["kitchen"]["B"]}
    assert trays["Rice"] == "low"
