import json

import pytest
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from messq.config import load_config
from messq.demo.auth import Auth
from messq.demo.server import Demo, make_handler


PW = {"manager": "manager-pass-1"}


class Client:
    """Talks to the demo server like a browser: keeps cookies, sends the X-Messq header."""

    def __init__(self, port):
        import http.cookiejar

        self.port = port
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, body=None, header=True, expect=200):
        import urllib.error

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST" if data else "GET")
        if header and data:
            req.add_header("X-Messq", "1")
        try:
            with self.opener.open(req) as r:
                code, out, url = r.status, r.read(), r.url
        except urllib.error.HTTPError as e:
            code, out, url = e.code, e.read(), e.url
        assert code == expect, (path, code, out[:200])
        return out, url

    def login(self, role):
        out, _ = self.call("/api/login", {"password": PW[role]})
        return json.loads(out)


def _serve(demo):
    auth = Auth(PW)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(demo, auth))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_demo_server_end_to_end():
    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    server, port = _serve(demo)
    try:
        c = Client(port)
        assert c.login("manager")["next"] == "/manager"
        demo.tick(40)  # 40 s real at 60x = 40 simulated minutes
        state = json.loads(c.call("/api/state")[0])
        assert state["t_min"] >= 39
        a, n = state["worlds"]["advised"], state["worlds"]["none"]
        assert a["students"] == n["students"] > 0  # same students in both worlds
        assert len(a["history"]) == len(n["history"]) > 0
        c.call("/api/runout", {"mess": "A"})
        c.call("/api/food", {"mess": "B", "state": "low"})
        state = json.loads(c.call("/api/state")[0])
        foods = {h["id"]: h["food"] for h in state["advice"]["halls"]}
        assert foods == {"A": "out", "B": "low"}
        for page in ("/", "/screen", "/food", "/manager", "/sheet"):
            assert b"<html" in c.call(page)[0]
        c.call("/api/control", {"action": "reset"})
        assert json.loads(c.call("/api/state")[0])["t_min"] == 0
    finally:
        server.shutdown()


def test_access_control():
    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    demo.seek(40 * 60)
    server, port = _serve(demo)
    try:
        anon = Client(port)
        # Students: door screens, phone page and the public feed only.
        for page in ("/", "/screen?at=A", "/screen?at=B", "/login"):
            anon.call(page)
        pub = json.loads(anon.call("/api/public")[0])
        assert set(pub) == {"clock", "mode", "switch_walk_s", "min_saving_min", "doors", "advice"}
        assert "Name" not in json.dumps(pub) and "worlds" not in pub
        for page in ("/manager", "/sheet", "/food"):
            _, url = anon.call(page)
            assert "/login?next=" in url  # redirected to the login page
        for api in ("/api/state", "/api/sheet", "/api/export.xlsx", "/api/food-state"):
            anon.call(api, expect=401)
        anon.call("/api/food", {"mess": "A", "state": "out"}, expect=401)
        anon.call("/api/control", {"action": "reset"}, expect=401)
        anon.call("/api/login", {"password": "wrong"}, expect=401)

        # Cross-site requests can't add the header, so even a logged-in browser is protected.
        m = Client(port)
        m.login("manager")
        m.call("/api/control", {"action": "pause"}, header=False, expect=403)
        m.call("/api/control", {"action": "pause"})
        # Only the manager marks trays; the change applies at once.
        m.call("/food")
        m.call("/api/food", {"mess": "B", "item": "Roti", "state": "low"})
        st = json.loads(m.call("/api/food-state")[0])
        trays = {t["item"]: t for t in st["trays"]["B"]}
        assert trays["Roti"]["state"] == "low" and trays["Gravy sabji"]["star"] and trays["Dal"]["weight"] == 0.1
        m.call("/logout")
        m.call("/api/state", expect=401)
    finally:
        server.shutdown()


def test_login_rate_limit_and_tampered_cookie():
    auth = Auth(PW)
    for _ in range(8):
        assert auth.login("1.2.3.4", "nope") is None
    assert auth.login("1.2.3.4", PW["manager"]) is None  # blocked even with the right password
    assert auth.login("5.6.7.8", PW["manager"]) == "manager"
    cookie = auth.make_cookie("manager").split(";")[0]
    assert auth.role_from(cookie) == "manager"
    forged = cookie.replace("manager.", "admin.", 1)
    assert auth.role_from(forged) is None
    assert Auth(PW).role_from(cookie) is None  # another server run doesn't accept it


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
    demo.food("B", "Rice", __import__("messq.events", fromlist=["FoodState"]).FoodState.LOW)
    trays = {t["item"]: t["state"] for t in demo.state()["trays"]["B"]}
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
    assert "xl/charts/chart3.xml" in z.namelist()  # wait without vs with the system
    cmp_header, cmp = sheet["compare_header"], sheet["compare"]
    assert cmp_header[1].startswith("Without the system") and len(cmp) == len(sheet["summary"])
    assert all(r[0] == s_[0] for r, s_ in zip(cmp, sheet["summary"]))  # same time slots
    title, text = demo.export_csv(None, 30, "B")
    assert title == "Munch Mess log" and text.splitlines()[0] == "Time,Name,ID,Wait (min),Time inside (min),Note"
    demo.write_files(tmp_path, 30)
    assert {p.name for p in tmp_path.iterdir()} == {
        "central_mess_log.csv", "munch_mess_log.csv", "every_30_min.csv", "wait_with_vs_without.csv", "mess_logs.xlsx"}


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


def test_single_manager_login():
    auth = Auth({"manager": "appleisyum"})
    assert auth.login("9.9.9.9", "appleisyum") == "manager"
    assert auth.login("9.9.9.9", "kitchen") is None  # there is no kitchen login


def test_login_lockout_uses_proxy_address(monkeypatch):
    """Behind a proxy, one visitor's wrong passwords must not lock everyone out."""
    import urllib.error
    import urllib.request

    monkeypatch.setenv("MESSQ_TRUST_PROXY", "1")
    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    server, port = _serve(demo)

    def login(pw, fwd):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/login", data=json.dumps({"password": pw}).encode(),
                                     method="POST", headers={"X-Messq": "1", "X-Forwarded-For": fwd})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        for _ in range(8):
            login("wrong", "1.1.1.1")
        assert login("wrong", "1.1.1.1") == 429  # that visitor is locked out...
        assert login(PW["manager"], "2.2.2.2") == 200  # ...another visitor is not
        assert login(PW["manager"], "9.9.9.9, 1.1.1.1") == 429  # a faked left-most entry doesn't help
    finally:
        server.shutdown()


def test_dashboard_shows_department_breaks_and_arrivals():
    demo = Demo(load_config(), "lunch", 0.6, seed=1, speed=60)
    demo.seek(105 * 60)  # 13:15, the overlap
    a = demo.state()["arrivals"]
    on = {d["name"] for d in a["depts"] if d["on"]}
    assert {"TAPMI", "MIT (lab day)"} <= on and "SMI" not in on
    assert a["capacity"] == 40 and a["expected"] and a["actual"]
    assert sum(r for _m, r in a["expected"]) * 5 == pytest.approx(2960, rel=0.03)
    header, rows = demo.sheet("advised", 30)["summary_header"], demo.sheet("advised", 30)["summary"]
    assert header[-1] == "On lunch break" and "TAPMI" in rows[-1][-1] and rows[0][-1] == ""
