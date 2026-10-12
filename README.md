# Smart Mess Queue Balancer

Uses live entry scans from the mess face-recognition terminals (Matrix COSEC
ARGO FACE) to estimate how busy each mess is, and tells students which mess
to go to so the queues balance out.

**Status: Phase 1 (simulator + core logic) is done, and the demo (Phase 2 preview) runs on
simulated data or on a scanner log you upload. Nothing connects to a live scanner yet.**

**Deployment assumed:** a screen **outside each mess entrance**. A student walks to the mess they
usually go to, sees the screen, and either goes in or walks ~30 s to the other mess. The system
only counts people who have **scanned in**; it never tries to count people still outside.

| Phase | What | State |
|---|---|---|
| 1 | Scanner adapter interface, fake-event simulator, occupancy/wait estimation, probabilistic routing, food-stock input, tests | ✅ done |
| 2 | Door screens, kitchen tray page, manager dashboard, log upload + replay | demo versions working (`python -m messq.demo`); production hardening next |
| 3 | Surge alerts (1-/5-min counts, learned baselines, cooldown, Telegram/WhatsApp) | |
| 4 | Real COSEC adapter (pycosec / official API) + CSV-export fallback | needs credentials + permission |
| 5 | A/B logging, metrics, report notebook | |
| 6 | Peak prediction, food forecasting, rewards | |

## Run the live demo on your laptop (for a pitch)

Needs **Python 3.11 or newer** and nothing else: no `pip install`, no internet during the demo.

1. **Get Python.** On Windows, install it from [python.org](https://www.python.org/downloads/) and tick
   *"Add python.exe to PATH"* in the installer. On a Mac, use python.org or `brew install python`.
   Check with `python --version` (or `python3 --version` on Mac). It must print 3.11 or higher.
2. **Get the code.** On GitHub, switch to this branch, then *Code → Download ZIP* and unzip it.
   Or: `git clone -b claude/laughing-bell-r2ub69 https://github.com/mrnotamazing/SmartScan_Mess`
3. **Start it.** Open a terminal (Windows: *Command Prompt* or *PowerShell*) in the unzipped folder:

   ```bash
   python -m messq.demo          # Windows   (use: py -m messq.demo  if "python" isn't found)
   python3 -m messq.demo         # Mac / Linux
   ```

4. **Open** <http://localhost:8000/manager> in a browser and log in with the **manager password
   printed in the terminal**. Ctrl+C in the terminal stops the demo.

### Who can open what

| | Pages | Login |
|---|---|---|
| **Students / anyone** | `/` (phone page: which mess is quicker right now), `/screen?at=A` (outside Central Mess), `/screen?at=B` (outside Munch Mess) | none |
| **Kitchen staff** | `/kitchen` (tray Low / Out / Refilled) | kitchen password |
| **Managers** | `/manager` (dashboard), `/sheet` (live spreadsheet), `/kitchen`, uploads, downloads | manager password |

Students can't reach the dashboard, the spreadsheet (names, logs) or the kitchen buttons: those
pages redirect to a login, and their data feeds refuse requests without a staff session. A kitchen
login can only open the kitchen page.

**Passwords** are never stored in the code. Each run, the terminal prints a made-up password for any
role you haven't set. To choose your own (so it doesn't change every run), set them before starting:

```bash
export MESSQ_MANAGER_PASSWORD='pick-something-long'      # Mac / Linux
export MESSQ_KITCHEN_PASSWORD='another-different-one'
python3 -m messq.demo

set MESSQ_MANAGER_PASSWORD=pick-something-long           # Windows (Command Prompt)
set MESSQ_KITCHEN_PASSWORD=another-different-one
py -m messq.demo
```

If you set both to the same password, there's one shared staff login and everyone who uses it
gets the full manager view (dashboard, spreadsheet with names, kitchen page).

Logins last 12 hours and end when the demo restarts. After 8 wrong passwords from one device,
that device has to wait 5 minutes.

| Page | Use it for |
|---|---|
| `localhost:8000/manager` | **Pitch dashboard** (manager login): the same meal run twice with identical students, *without* vs *with* the screens. Live chart, timeline, log upload, kitchen overview |
| `localhost:8000/` | **Student phone page** (no login): which mess is quicker now. When both are close, each phone gets a suggestion drawn from the system's split, so phones don't all pile into one mess |
| `localhost:8000/screen?at=A` | The screen **outside Central Mess** (use `?at=B` for Munch Mess). Full-screen it (F11) on a projector. Add `&dir=left` if the other mess is to the left |
| `localhost:8000/kitchen?mess=A` | Central Mess kitchen managers' page (`?mess=B` for Munch Mess): tap *Low / Out / Refilled* per tray (Main course, Rice, Roti, Dal) |
| `localhost:8000/sheet` | **Live spreadsheet**: a scan log per mess (time, name, ID, wait) and counts per 30 min with charts. Download as Excel or CSV |

**Dashboard controls**

* **Timeline**: play/pause, −5/+5 min, and a slider to jump to any time, forwards or backwards.
  Jumping back re-runs the meal and replays anything you clicked (run-outs, kitchen taps) at the same moments.
* **Speed**: from 1× (real time) up to 600× (a 2-hour lunch in 12 seconds).
* **Students who follow the screen**: change it mid-meal; the meal is re-run with the new share up to the current time.
* **Meal**: simulated breakfast/lunch/dinner, or any meal from an uploaded log.
* **Upload a day's log (CSV)**: see below.
* **Make food run out**: simulates a real shortage at a mess. The kitchen page is different: it's what managers *report*.

### Live spreadsheet

`localhost:8000/sheet` (manager login) records the meal as it happens:

| Tab | Columns |
|---|---|
| **Central Mess log**, **Munch Mess log** | one row per scan: Time, Name, ID (pseudonymised), Wait (min), Note (e.g. "walked over from Munch Mess (screen)") |
| **Every 30 min** | per time slot: students at each mess, total, Central's share, average wait per mess, students who walked over. Totals, the busiest slot, and two charts (students per slot, average wait) |

* **Updates:** *Live* (every 3 s) or *Every 1 minute* (with a countdown). Group by 5/10/15/30/60 minutes.
* **Showing:** *With screens* or *Without screens*. For an uploaded log, choose *As it happened* (the real scans).
* **Download Excel (.xlsx):** three sheets with every row, plus native Excel charts. **Download this tab (CSV)** for one tab.
* **Files that keep themselves up to date:** start the demo with `--save-sheets` and it rewrites
  `live_sheets/central_mess_log.csv`, `munch_mess_log.csv`, `every_30_min.csv` and `mess_logs.xlsx`
  every minute. Re-open the file to see new rows (Excel doesn't reload files on its own; on
  Windows, a file that's open in Excel is skipped until you close it).
* **Names:** simulated students get made-up names. For an uploaded real log, names are hidden
  (only a pseudonymised ID is shown) unless you set `privacy.show_names = true` in the config or start
  with `--show-names`. Turn that on only with the college's approval: names plus meal times are personal data
  under the DPDP Act.

### Replaying a real day from a log file

Click **Upload a day's log (CSV)** and pick an export from the scanner software. The app:

1. finds the columns by name: a time (`Timestamp`, `Punch Time`, or separate `Date` + `Time`), a
   device or mess (`Device Name`, `Terminal`, `Door`, `Mess`…), and optionally a person ID and an
   IN/OUT column (exit rows are ignored),
2. matches device names to messes (`CENTRAL-MESS-ENTRY` → Central Mess; unknown names are assigned in order),
3. splits the day into meals wherever there's a 45-minute gap, and shows the busiest one.

The left side then shows **what happened** (real arrival times and messes). The right side shows
**the same students with screens**. Queues, serving and seating on both sides are simulated from
the assumed speeds, so treat the minutes as estimates.

* Try it with `samples/sample_day_log.csv`, a fake day in the shape a COSEC export might have.
  Make another with `python -m messq.make_sample_log`.
* The file is read in memory and never saved; raw IDs are hashed as each row is read.
* Excel files: *File → Save As → CSV* first. Limit 20 MB (export one day).
* Start straight into a replay: `python -m messq.demo --log path/to/log.csv` (add `--show-names` to see the sample's made-up names).

**Phones in the room.** Run `python -m messq.demo --lan` and the terminal prints an address like
`http://192.168.1.23:8000/`. Anyone on the **same Wi-Fi** can open the student page and the door
screens on their phone. Hand someone `/kitchen` with the kitchen password and let them tap "Out" during the pitch. (Windows may ask to allow Python
through the firewall: allow it on *private* networks. College Wi-Fi often blocks
device-to-device traffic; a phone hotspot works.)

Options: `--speed 120` (a 2-hour lunch in 1 minute; default 60 = 2 minutes), `--slot dinner`,
`--compliance 0.4` (share of students who follow advice), `--seed 5` (a different "day"), `--port 8080`.

### A 3-minute pitch script

0. Before you start: open `/manager` and log in. Have the student page (`/`) open on your phone.
1. *"Same students, same lunch, two worlds. On the left is today. On the right, there's a screen outside each mess."*
2. Drag the timeline to about **13:00**. The orange line climbs while Munch Mess sits half-empty on the left.
3. Point at **"waited >10 min"** and at the line under the blue card: *"only about 1 in 10 students
   had to walk 30 seconds to the other mess."*
4. Open `/screen?at=A`: *"This is what you'd see outside Central Mess: how full each mess is and when you'd get food."*
5. Hand someone the kitchen page and have them tap **Out** on Central Mess's main course. Its
   screen starts pointing to Munch Mess within seconds.
6. Open `/sheet` → *Every 30 min*: *"And the mess manager gets this, live: who came when, per mess, every half hour."*
7. If you have a real log, upload it: *"This is last Tuesday's lunch, replayed."*
8. Close with what you need: permission to read scan counts (not faces), and one pilot meal slot.

Be upfront that it is a simulation with assumed numbers. The pilot exists to measure the real ones.

## Developer quick start

```bash
pip install pytest                 # only needed for the tests
python -m pytest                   # 37 tests

python -m messq.simulate --trace   # one simulated lunch, as the screen would show it, in the terminal
python -m messq.simulate           # Monte Carlo: no advice vs greedy vs equilibrium routing
python -m messq.simulate --slot dinner --runs 50 --compliance 0.2 0.4 0.6 0.8 1.0
python -m messq.simulate --replay samples/sample_day_log.csv              # list meals in a log
python -m messq.simulate --replay samples/sample_day_log.csv --session 1  # replay one under each policy
```

Per-run results are written to `results/simulation_runs.csv`, ready for the analysis in your MDS report.

## How it works

```
 scanner adapter ──► engine ───────────────────────────────► recommendation
 (simulator now,     ├ dedupe events                          "Go to Munch Mess"
  COSEC API later)   ├ occupancy  = entries in last N min      + per-hall wait,
                     ├ arrival rate = entries in last 5 min      status, split %
 kitchen taps ──────►├ backlog    = fluid queue estimate
 (low/out/refilled)  ├ wait       = backlog + M/M/c + seats + food
                     └ split      = equal-wait (Wardrop) split
```

| Quantity | Measured or estimated? | How |
|---|---|---|
| Scans per minute per hall | **measured** | count of entry scans |
| People inside a hall | *estimated* | entries in the last N minutes (N = 22 by default). There are no exit scans |
| People waiting to be served | *estimated* | fluid queue: grows with scans, shrinks at the hall's configured serving rate |
| Wait time | *estimated* | backlog ÷ capacity + M/M/c (Erlang C) wait + seat wait + food delay, projected forward by the walk time |
| Food state | reported by staff | kitchen taps; taps expire if staff forget to tap "refilled" |

**Anti-herding.** The engine does not tell everyone to go to the emptier
hall. It finds the split of incoming students that would make the predicted
waits equal (a Wardrop equilibrium).

**Door screens** (`layout.mode = "doors"`, the default). Students arrive at their usual mess, so the
engine works out what share of the people at the busier door should walk over to reach that
split. The screen turns that share into a message: a *strong* "Munch Mess is faster right now →",
a *soft* "In a hurry? Munch Mess is ~4 min faster", or "come on in". It never suggests switching
unless it saves at least `layout.min_saving_min` (2 min) after the walk. The older single
shared screen is still available as `layout.mode = "hallway"`.

**Kitchen trays.** Each mess has trays (`items` in the config). Only the main tray running out
stops service; another tray out counts as "busy". "All refilled" resets every tray and lights up
"✨ Fresh batch just out" on the door screens for 10 minutes.

**Partial compliance.** If you know (from a no-screen baseline) where
students go by habit and roughly what fraction follow advice, set
`engine.assumed_compliance` and `engine.natural_share`. The engine then
over-corrects so that the *realised* split is balanced.

## Results (default config, ASSUMED numbers)

Every policy sees the same students (paired comparison), ±95% CI.
Wait = minutes from scanning in at the hall to sitting down with food.

### Door screens (the default layout), simulated lunch, 30 runs per row

| Policy | Students who follow | Avg wait | p90 wait | Peak queue | Students who walked to the other mess |
|---|---|---|---|---|---|
| No screens (habit 65/35) | – | 5.4 ± 0.4 | 14.8 ± 1.2 | 192 ± 14 | 0% |
| "Switch if it saves ≥2 min" (greedy) | 60% | 2.1 ± 0.3 | 5.3 ± 0.8 | 76 ± 10 | 11% |
| Equilibrium split | 30% | 2.4 ± 0.2 | 6.3 ± 0.7 | 88 ± 7 | 9% |
| Equilibrium split | 60% | 2.2 ± 0.3 | 5.5 ± 0.8 | 79 ± 9 | 10% |
| Equilibrium split | 100% | 2.2 ± 0.3 | 5.5 ± 0.8 | 79 ± 10 | 11% |

**Replaying the sample log's lunch** (1,604 real-shaped arrivals, 20 runs): no screens 6.0 ± 0.3 min
average (p90 16.0); equilibrium split at 60% follow 1.9 ± 0.2 min (p90 4.5), with 11% of students switching.

### One shared hallway screen (`layout.mode = "hallway"`), simulated lunch

| Policy | Compliance | Avg wait | p90 wait | Peak queue | Food run-outs | Occupancy est. error |
|---|---|---|---|---|---|---|
| No advice (habit 65/35) | – | 5.6 ± 0.4 | 15.3 ± 1.0 | 198 ± 13 | 1.3 | 36 people |
| Greedy ("go to emptier") | 60% | 2.0 ± 0.2 | 4.4 ± 0.5 | 67 ± 6 | 1.4 | 12 |
| Equilibrium split | 30% | 2.3 ± 0.2 | 6.3 ± 0.7 | 89 ± 9 | 1.5 | 14 |
| Equilibrium split | 60% | 2.0 ± 0.2 | 4.8 ± 0.6 | 71 ± 8 | 1.6 | 12 |
| Equilibrium split | 100% | 1.9 ± 0.2 | 4.4 ± 0.5 | 64 ± 6 | 1.4 | 12 |

Same thing, but with students reading the advice **5 minutes before they
arrive** (e.g. on their phone in the hostel), so feedback lags:

| Policy | Compliance | Avg wait | p90 wait | Peak queue |
|---|---|---|---|---|
| No advice | – | 5.6 ± 0.5 | 15.5 ± 1.3 | 200 ± 17 |
| Greedy | 60% | 3.0 ± 0.3 | 6.9 ± 0.5 | 111 ± 10 |
| Greedy | 100% | **4.3 ± 0.3** | 8.8 ± 0.5 | 141 ± 8 |
| Equilibrium split | 60% | 2.0 ± 0.2 | 5.4 ± 0.5 | 79 ± 7 |
| Equilibrium split | 100% | **1.9 ± 0.3** | 4.5 ± 0.9 | 67 ± 12 |

What this says (under the ASSUMED parameters):

1. With these parameters, balancing cuts the average wait from about 5.5 to about 2 minutes and the p90 wait from about 15 to about 5 minutes.
2. **Door screens need far fewer people to move.** About 1 in 10 students walks to the other mess,
   against 30–50% with one shared screen, for the same benefit. That's the pitch line.
3. At the doors, a simple "switch if it saves ≥2 min" rule does as well as the equilibrium split.
   Feedback is fast (30 s walk) and the threshold stops herding. The equilibrium split matters
   when advice is read early, e.g. on phones (next table).
4. Greedy advice herds when the advice lags. In the 5-minute table it gets *worse* as more students obey it (3.0 → 4.3 min). The equilibrium split doesn't have this problem.
5. Balancing alone did **not** reduce food run-outs in this model. Total consumption is unchanged, and refills are triggered by stock level. Fewer run-outs need kitchen-side changes (earlier refill triggers, forecasting: Phase 6). Don't promise the vendor fewer run-outs from routing alone.
6. A missed "refilled" tap is dangerous. Before tap expiry was added, one missed tap kept a hall marked empty, sent every student to the other hall, and pushed one run to a 9-minute average wait. Taps now expire, and that case is a regression test.

## Configuration

All numbers live in `config/default.toml` (or the file named by
`MESSQ_CONFIG`). Values tagged **ASSUMED** are placeholders. The most
important one to measure is `service_rate_per_counter_per_min`: time a
counter with a stopwatch at peak. The backlog and wait estimates depend
directly on it.

Secrets are never put in the config file. They come from environment variables:

| Variable | Purpose |
|---|---|
| `MESSQ_ID_SALT` | secret used to pseudonymise student IDs (HMAC-SHA256) |
| `MESSQ_COSEC_URL`, `MESSQ_COSEC_USER`, `MESSQ_COSEC_PASSWORD` | Phase 4, real scanner/server access |

## Plugging in the real scanner (Phase 4, not built yet)

Every event source implements `messq.adapters.ScannerAdapter.poll() -> list[ScanEvent]`.
Swapping the simulator for a real source does not touch the engine. The plan:

* **COSEC API adapter**: polls every 3–5 s for new punch events using
  [pycosec](https://pypi.org/project/pycosec/) (third-party, HTTP Basic auth)
  or the official Matrix API once we have its docs. It maps device → mess,
  de-duplicates by event id (already handled by the engine), and handles
  network failures and device clock drift.
* **CSV-export adapter** (fallback): watches the COSEC server's attendance
  export every 30–60 s.
* **Push** from the device or server is unconfirmed, so polling is the design. Push is an optional upgrade.

**Unconfirmed about the Matrix API (nothing in this repo assumes it):**
the endpoint names, event fields, whether events can be filtered "since
event id X", whether the device or only the COSEC server exposes the API,
and whether push/webhooks exist.

### What to get from the college / vendor

- [ ] Written permission from the college admin **and** the mess vendor to read scan events
- [ ] Confirm one scanner per mess entrance, and where each screen can be mounted (power + network)
- [ ] One day's attendance export (CSV) to replay in the demo
- [ ] Exact device model (ARGO FACE210?) and firmware version
- [ ] Whether events are read from the device or from the COSEC server (VYOM/CENTRA), plus its IP
- [ ] API username/password with **read-only** access to events
- [ ] Official Matrix COSEC API documentation (usually given to customers/integrators)
- [ ] Failing that, how to get a periodic attendance CSV/database export
- [ ] Device-to-mess mapping (device IDs)

## Privacy

* Only `pseudonymised student key + mess id + timestamp` is handled. No face
  images or templates exist anywhere in this code, and none are requested.
* IDs are HMAC-SHA256 hashed with a secret salt before storage. Under the
  DPDP Act 2023 pseudonymised logs are still personal data, so a retention
  limit applies (`privacy.retention_days`, default 30).
* The balancing itself needs **counts only**. Per-student keys are needed
  only for compliance measurement or rewards. If you don't build those,
  drop the key at ingestion and store nothing per-person.

## Assumptions in the brief I'd question

1. **"Occupancy = entries in last N min" breaks down in long queues.**
   Someone stuck in a 25-minute queue drops out of a 22-minute window. That
   is why the no-advice case shows a 36-person estimation error. The
   backlog estimate partly fixes this, but only if the serving rate is
   measured.
2. **Seats are probably not the bottleneck; serving counters are.**
   `load = occupancy / seats` is shown, but the wait estimate is driven by
   counter throughput.
3. **Herding matters less than expected for screens 30 s apart.** Feedback is fast,
   so even simple advice works there. Probabilistic routing matters once advice is
   read earlier (on phones).
4. **Compliance can't be measured per student from a shared screen**,
   because the screen doesn't know who read it. For the screen, measure it in
   aggregate (advised split vs observed split, screen-on vs screen-off
   days). Per-student compliance needs the phone page.
5. **Food run-outs**: see result 5 above.

## Student screen psychology

How the door screen tries to make students actually care about the wait (colour, framing,
food cues, social proof, rewards), what's built, and what to A/B test in the pilot:
[docs/student-screen-psychology.md](docs/student-screen-psychology.md).
