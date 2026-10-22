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
| 2 | Door screens, manager dashboard with food status, log upload + replay | demo versions working (`python -m messq.demo`); production hardening next |
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
| **Mess manager** | `/manager` (dashboard, including food status: mark trays running low / out / refilled), `/food?mess=A` (the same food status as a phone page), `/sheet` (live spreadsheet), uploads, downloads | manager password |

There is one staff login: the mess manager's. Students can't reach the dashboard, the spreadsheet
(names, logs) or the food-status buttons: those pages redirect to a login, and their data feeds
refuse requests without a manager session.

**The password** is never stored in the code. If you haven't set it, the terminal prints a made-up
one each run. To choose your own (so it doesn't change every run), set it before starting:

```bash
export MESSQ_MANAGER_PASSWORD='pick-something-long'      # Mac / Linux
python3 -m messq.demo

set MESSQ_MANAGER_PASSWORD=pick-something-long           # Windows (Command Prompt)
py -m messq.demo
```

Logins last 12 hours and end when the demo restarts. After 8 wrong passwords from one device,
that device has to wait 5 minutes.

| Page | Use it for |
|---|---|
| `localhost:8000/manager` | **Pitch dashboard** (manager login): the same meal run twice with identical students, *without* vs *with* the screens. Live charts, timeline, log upload, food status |
| `localhost:8000/` | **Student phone page** (no login): which mess is quicker now. When both are close, each phone gets a suggestion drawn from the system's split, so phones don't all pile into one mess |
| `localhost:8000/screen?at=A` | The screen **outside Central Mess** (use `?at=B` for Munch Mess). Full-screen it (F11) on a projector. Add `&dir=left` if the other mess is to the left |
| `localhost:8000/food?mess=A` | **Food status** for the mess manager's phone (`?mess=B` for Munch Mess; also on the dashboard): tap *Running low / Out / Refilled* per tray (gravy sabji, dry sabji, dal, rice, special rice, roti, sambar/rasam, curd/raita, dessert), each showing today's dish from `config/menu.toml`. Update that file each week; `--menu-day wednesday` shows another day's menu. How much each tray matters comes from the priority matrix (see *Food status and the priority matrix*) |
| `localhost:8000/sheet` | **Live spreadsheet**: a scan log per mess (time, name, ID, wait) and counts per 30 min with charts. Download as Excel or CSV |

**Dashboard controls**

* **Timeline**: play/pause, −5/+5 min, and a slider to jump to any time, forwards or backwards.
  Jumping back re-runs the meal and replays anything you clicked (run-outs, food-status updates) at the same moments.
* **Speed**: from 1× (real time) up to 600× (a 2-hour lunch in 12 seconds).
* **Students who follow the screen**: change it mid-meal; the meal is re-run with the new share up to the current time.
* **Meal**: simulated breakfast/lunch/dinner, or any meal from an uploaded log.
* **Upload a day's log (CSV)**: see below.
* **Make food run out**: simulates a real shortage at a mess. Food status is different: it's what the manager *reports*.

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
screens on their phone. Open `/food?mess=A` on your phone and tap "Out" during the pitch. (Windows may ask to allow Python
through the firewall: allow it on *private* networks. College Wi-Fi often blocks
device-to-device traffic; a phone hotspot works.)

Options: `--speed 120` (a 2-hour lunch in 1 minute; default 60 = 2 minutes), `--slot dinner`,
`--compliance 0.4` (share of students who follow advice), `--seed 5` (a different "day"), `--port 8080`.

### A 3-minute pitch script

0. Before you start: open `/manager` and log in. Have the student page (`/`) open on your phone.
1. *"Same students, same lunch, two worlds. On the left is today. On the right, there's a screen outside each mess."*
2. Drag the timeline to about **13:00**. The orange line climbs while Munch Mess sits half-empty on the left.
3. Point at **"waited >10 min"** and at the line under the blue card: *"only about 1 in 5 students
   had to walk 30 seconds to the other mess."*
4. Open `/screen?at=A`: *"This is what you'd see outside Central Mess: how full each mess is and when you'd get food."*
5. On the food-status page, tap **Out** on Central Mess's star dish (gravy sabji). Its
   screen starts pointing to Munch Mess within seconds.
6. Open `/sheet` → *Every 30 min*: *"And the mess manager gets this, live: who came when, per mess, every half hour."*
7. If you have a real log, upload it: *"This is last Tuesday's lunch, replayed."*
8. Close with what you need: permission to read scan counts (not faces), and one pilot meal slot.

Be upfront that it is a simulation with assumed numbers. The pilot exists to measure the real ones.

## Developer quick start

```bash
pip install pytest                 # only needed for the tests
python -m pytest                   # 40 tests

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
 manager taps ──────►├ backlog    = fluid queue estimate
 (low/out/refilled)  ├ wait       = backlog + M/M/c + seats + food
                     └ split      = equal-wait (Wardrop) split
```

| Quantity | Measured or estimated? | How |
|---|---|---|
| Scans per minute per hall | **measured** | count of entry scans |
| People inside a hall | *estimated* | people still queueing + people served in the last ~17 min (eating). There are no exit scans |
| Time inside (scan to leaving) | *estimated* | queue time now + serving + ~17 min eating. About 18 min on a normal day (measured); longer in a surge |
| People waiting to be served | *estimated* | fluid queue: grows with scans, shrinks at the hall's configured serving rate |
| Wait time | *estimated* | backlog ÷ capacity + M/M/c (Erlang C) wait + seat wait + food delay, projected forward by the walk time |
| Food state | reported by the mess manager | food-status taps, weighted by the priority matrix; taps expire if "refilled" is forgotten |

**Food status and the priority matrix.** The manager marks trays *running low*, *out* or
*refilled*. Each tray has a weight from the ABC/XYZ priority matrix (`MDS_dataset.xlsx`), set in
`[[tray]]` in `config/default.toml`:

| Tray | Item type (matrix) | Class | Weight |
|---|---|---|---|
| Gravy sabji, Special rice | Star dish | AZ Tight Control | ★ 1.0 |
| Roti | Made fresh in batches | AZ | 0.5 |
| Dessert | One per plate | AX Calculated Issue | 0.3 |
| Curd / raita | Fresh side | AZ | 0.3 |
| Dry sabji, Dal, Rice, Sambar / rasam | Base food | CZ Buffered Issue | 0.1 |

* A **star dish OUT** (any star dish, whatever it is that day) closes that mess for routing: the
  screens send students to the other mess until it is refilled.
* Any **other tray OUT** adds *weight × expected refill time* (≈17 min) to that mess's predicted wait.
* Any tray **running low** adds *weight × 0.25 × expected refill time*. The 0.25 (assumed) is the
  chance it empties before a student arriving now is served. A star dish running low adds ≈4 min.
* Table items (salt, pickle, fryums: class CX, "free issue") aren't tracked.

The weights are the group's reading of the matrix and should be confirmed with the CT manager.

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

## Results (default config)

**Measured inputs:** lunch 11:30–14:30; 2,960 students (= plates served) across Central CT and Munch Mess;
seats 900 / 500; 2 serving stations and 1 face scanner per mess; ~18 min scan-to-leaving on a normal day;
restocking after the mess calls the kitchen ("running low"): 30 min in total if the kitchen has to make it
and send it, 10–14 min if it is already made and only has to be sent.
**Assumed:** 85% go to Central by habit; ~10 students/min per serving station (~6 s each; it must be about
this fast for 2 stations to serve ~2,500 Central students in 3 hours); 2 s per face scan; the arrival curve's
shape; food batch sizes and call levels.
**Group estimate:** the next batch is already made about 70% of the time when the mess calls.

Every policy sees the same students (paired comparison), ±95% CI.
Wait = minutes from reaching the mess door (including any queue at the scanner) to sitting down with food.

### Door screens (the default layout), simulated lunch, 20 runs per row

| Policy | Students who follow | Avg wait | p90 wait | Peak queue | Food run-outs | Walked to the other mess |
|---|---|---|---|---|---|---|
| No screens (habit 85/15) | – | 7.2 ± 0.4 | 17.6 ± 0.9 | 405 ± 16 | 0.8 | 0% |
| "Switch if it saves ≥2 min" (greedy) | 60% | 1.0 ± 0.2 | 2.8 ± 0.5 | 83 ± 13 | 0.3 | 16% |
| Equilibrium split | 30% | 1.6 ± 0.3 | 4.8 ± 0.9 | 122 ± 15 | 0.8 | 13% |
| Equilibrium split | 60% | 1.1 ± 0.3 | 3.1 ± 0.9 | 94 ± 19 | 0.5 | 15% |
| Equilibrium split | 100% | 1.0 ± 0.1 | 2.6 ± 0.4 | 82 ± 11 | 0.5 | 17% |

How much the restock matters (`food_ready_prob`, the chance the next batch is already made
when the mess calls; group estimate 70%), equilibrium split at 60%:

| Next batch already made? | Restock time | Run-outs, no screens | Run-outs, screens | Avg wait, no screens → screens |
|---|---|---|---|---|
| Never | 30 min | 2.0 | 3.0 | 7.0 → 0.9 |
| Half the time | 30 or 10–14 min | 1.3 | 1.6 | 7.1 → 0.8 |
| 70% of the time (default) | 30 or 10–14 min | 0.8 | 0.9 | 7.2 → 0.8 |
| Always | 10–14 min | 0 | 0 | 7.2 → 0.9 |

Without screens the simulated p90 wait (~17 min) is close to the ~15 min delay observed in Phase 1,
which suggests the assumed numbers are in the right range.

### One shared hallway screen (`layout.mode = "hallway"`): earlier inputs

These two tables were run with the earlier placeholder inputs (1,600 students, 3 lines at 4/min, habit
65/35, 12:30–14:30). They are kept because the herding comparison still holds.

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

1. With the corrected inputs, door screens cut the average wait from about 7 to about 1–1.5 minutes,
   and the p90 wait from about 17 to about 4 minutes.
2. **About 1 in 7 students walks to the other mess** (13–17%). Because 85% start at Central, rebalancing
   needs more movement than the earlier 65/35 guess did.
3. At the doors, a simple "switch if it saves ≥2 min" rule does as well as the equilibrium split.
   Feedback is fast (30 s walk) and the threshold stops herding. The equilibrium split matters
   when advice is read early, e.g. on phones.
4. Greedy advice herds when the advice lags (hallway tables): it gets *worse* as more students obey it.
5. **Moving students moves the run-outs.** Food run-outs rise slightly with screens because Munch now
   feeds more students and a 30-minute call-back restock cannot keep up. Student routing and food
   allocation have to be planned together (see the LP allocation in `docs/MDS_Decision_Workbook.xlsx`).
6. **Run-outs are a kitchen-timing problem, not a queue problem.** If the next batch is always made
   before the mess calls (10–14 min to send instead of 30), run-outs disappear in the model. Average
   waits barely change, because the serving stations, not the food, set the queue.
7. **The single face scanner is close to its limit at peak.** At an assumed 2 s per scan it handles about
   30 students/min; peak arrivals at Central are close to that, so a queue of 20–25 people can form
   *outside* the scanner, which the system cannot see. The dashboard shows each scanner's load. Time the
   scan with a stopwatch.
8. A missed "refilled" tap is dangerous. Before tap expiry was added, one missed tap kept a hall marked
   empty and sent every student to the other hall. Taps now expire, and that case is a regression test.

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

**The device: COSEC ARGO FACE210M.** From Matrix's product page: a face-based time-attendance
terminal (face + Mifare/DESFire card; "M" = Mifare), 3.5" touchscreen, **Ethernet 10/100 and PoE
only (no Wi-Fi)**, USB-C, 50,000 users, 200,000 face templates, **500,000 stored events**. The
time-attendance variant lists **no Wiegand, relay, door-lock or external-reader interface**, which
rules out tapping it with extra hardware. The integration has to be over the network. The product
page doesn't mention an API or event push for this model, so the API details must come from Matrix or IT.

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
- [x] Device model: **COSEC ARGO FACE210M** (confirmed). Still needed: firmware version
- [ ] Is each FACE210M registered to a COSEC server (CENTRA / VYOM)? If yes, read events from the server, not the devices
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
   The ~18 min visit is for a normal day; in a surge, queueing adds to it, and
   someone stuck in the queue drops out of an 18-minute window. The estimator now
   counts people inside as *still queueing + served in the last ~17 min*, which
   cut the "people inside" error from ~34 to ~11 people without screens (~14 to
   ~8 with them). It still relies on the serving rate, so measure that next.
2. **Seats are not the bottleneck; serving counters are.** With the measured
   1,400 seats (900 + 500), the simulated waits barely changed from the earlier
   guesses of 550 seats, and the deck's field notes point the same way.
   `load = occupancy / seats` is shown, but the wait estimate is driven by
   counter throughput. Measure the serving rate next.
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
