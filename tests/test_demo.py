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


def test_sheet_api_exports_and_saved_files(tmp_path):
    import io
    import zipfile

    demo = Demo(load_config(), "lunch", 0.6, seed=3, speed=60)
    demo.seek(70 * 60)
    sheet = demo.sheet(None, 30)
    names = [m["name"] for m in sheet["messes"]]
    assert names == ["Central Mess", "Munch Mess"]
    total_logged = sum(len(v) for v in sheet["logs"].values())
    assert total_logged == sum(r[3] for r in sheet["summary"])  # every scan is in exactly one slot
    first = sheet["logs"]["A"][0]
    assert first[0].count(":") == 2 and first[1] and first[2].startswith("ID ")
    xlsx = demo.export_xlsx(None, 15)
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    assert "xl/charts/chart1.xml" in z.namelist() and "xl/charts/chart2.xml" in z.namelist()
    title, text = demo.export_csv(None, 30, "B")
    assert title == "Munch Mess log" and text.splitlines()[0] == "Time,Name,ID,Wait (min),Note"
    demo.write_files(tmp_path, 30)
    assert {p.name for p in tmp_path.iterdir()} == {
        "central_mess_log.csv", "munch_mess_log.csv", "every_30_min.csv", "mess_logs.xlsx"}


def test_uploaded_names_hidden_unless_enabled():
    import dataclasses

    rows = "\n".join(f"2026-10-12 12:{m:02d}:00,Central Mess,R{m},Real Person {m}" for m in range(30))
    text = "timestamp,device,roll no,student name\n" + rows
    cfg = load_config()
    demo = Demo(cfg, "lunch", 0.6, seed=1, speed=60)
    demo.upload(text)
    demo.seek(60 * 60)
    assert all(r[1] == "(hidden)" for r in demo.sheet(None, 30)["logs"]["A"])
    cfg2 = dataclasses.replace(cfg, privacy=dataclasses.replace(cfg.privacy, show_names=True))
    demo2 = Demo(cfg2, "lunch", 0.6, seed=1, speed=60)
    demo2.upload(text)
    demo2.seek(60 * 60)
    assert demo2.sheet(None, 30)["logs"]["A"][0][1] == "Real Person 0"
