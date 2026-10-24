# Smart Mess Queue Balancer

*MDS project, Group WGB3: **Beyond the Bottleneck: Enabling Smarter Lunch Flow by Optimising Queue
Management and Capacity Utilisation Across Chefs Touch Centres** (Phase 1 was "The Two-Hour Bottleneck").*

Uses live entry scans from the mess face-recognition terminals (Matrix COSEC
ARGO FACE) to estimate how busy each mess is, and tells students which mess
to go to so the queues balance out.

**Status: the simulator and core logic are done, and the demo runs on simulated data or on a
scanner log you upload. Nothing connects to a live scanner yet.**

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
| `localhost:8000/sheet` | **Live spreadsheet**: a scan log per mess (time, name, ID, wait) and counts per 30 min with charts and the departments on their lunch break in each slot. Download as Excel or CSV |

**Dashboard controls**

* **Timeline**: play/pause, −5/+5 min, and a slider to jump to any time, forwards or backwards.
  Jumping back re-runs the meal and replays anything you clicked (run-outs, food-status updates) at the same moments.
* **Speed**: from 1× (real time) up to 600× (a 2-hour lunch in 12 seconds).
* **Students who follow the screen**: change it mid-meal; the meal is re-run with the new share up to the current time.
* **Meal**: simulated breakfast/lunch/dinner, or any meal from an uploaded log.
* **Upload a day's log (CSV)**: see below.
* **Make food run out**: simulates a real shortage at a mess. Food status is different: it's what the manager *reports*.
* **When students arrive** (panel): the simulated lunch's arrival curve built from the department lunch breaks
  (`[[simulation.slot.group]]` in `config/default.toml`), the arrivals so far, the serving capacity (40/min both
  messes, 20/min Central), and a bar per department lit while its break is on. Hover a point to see who is on break.

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

### Hosting it online (Render, free)

The demo is a small Python server that keeps the simulated lunch running, so it needs a host that
runs a program all the time. Static or serverless hosts (GitHub Pages, Vercel) can't keep the
clock running or remember the manager's taps. `render.yaml` sets up Render's free tier:

1. render.com → sign up with GitHub → **New → Blueprint** → pick `SmartScan_Mess`.
2. Type a manager password when asked for `MESSQ_MANAGER_PASSWORD` → **Apply**.
3. Open the `https://….onrender.com` address: `/` and `/screen?at=A` for students, `/manager` to log in.

The free tier sleeps after ~15 min without visitors; the next visit wakes it in about a minute and
the simulated lunch starts again. Use simulated or sample data only until the college approves real logs.

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
python -m pytest                   # 45 tests

python -m messq.simulate --trace   # one simulated lunch, as the screen would show it, in the terminal
python -m messq.simulate           # Monte Carlo: no advice vs greedy vs equilibrium routing
python -m messq.scenarios          # the four scenarios + stress tests -> results/scenarios.json
python -m messq.scenarios --payoff # alternatives x kinds of day      -> results/payoff.json
python -m messq.scenarios --reconcile  # spreadsheet-like -> full model -> results/reconcile.json
pip install openpyxl scipy && python tools/build_workbook.py   # rebuild docs/MDS_Decision_Workbook.xlsx from those results
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

* A **star dish OUT** (any star dish, whatever it is that day) is an outage: that mess serves nobody
  until the refill, so the screens send students to the other mess for as long as that is faster.
* Any **other tray OUT**, or any tray **running low**, costs a student time only if they would reach the
  counter after it empties and before its refill: they wait *weight × (refill time − their arrival)*.
  "Running low" is tapped when the mess calls the kitchen, with about 20 minutes of food left (protocol,
  `engine.low_food_left_min`), so a student who will be served within 20 minutes loses nothing.
* **The refill clock runs from the kitchen call**, and the expected time still to wait is updated as
  time passes: after 15 minutes with no refill, the 10–14 minute "already made" case is ruled out, so
  about 15 more minutes remain. A forgotten "refilled" tap can't freeze the advice: the engine assumes
  serving resumes once the refill must have arrived.
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

**Food trays.** Each mess has trays (`items` in the config). A star dish running out stops service;
other trays add a weighted delay (above). "All refilled" resets every tray and lights up
"✨ Fresh batch just out" on the door screens for 10 minutes.

**Partial compliance.** If you know (from a no-screen baseline) where
students go by habit and roughly what fraction follow advice, set
`engine.assumed_compliance` and `engine.natural_share`. The engine then
over-corrects so that the *realised* split is balanced.

## Where this sits in Operations Management

Mainly **capacity management / load balancing** and **queuing theory**; also **behavioural operations**
(habit, herding, partial compliance) and **demand shaping** (influencing where and when students eat
with information rather than new capacity). With the simulated peak, total capacity is enough
(~37 arrivals/min in the busiest 10 minutes against 40/min of serving) but the load is uneven: Central
gets ~30/min against 20/min while Munch gets ~8/min. See section 1.1 of `docs/MDS_Queuing_Theory_and_Simulation.docx`.
(Not *yield* management: that means pricing perishable capacity, and a prepaid mess has no price lever.)

## Results (default config)

**Measured:** lunch 11:30–14:30; 2,960 students (= plates served); seats 900 / 500; 2 serving stations and 1
face scanner per mess; ~2,360 eat at Central and ~600 at Munch without screens (80/20); ~18 min scan to leaving on a normal day; refill 30 min after the "running low" call
if it must be made, 10–14 min if already made.
**Group estimates:** throughput 17–25 min depending on the surge; eating 12–15 min; disposal ≤ 2 min;
scanning + plate ≤ ~45 s; the next batch is already made ~70% of the time.
**Assumed:** ~10 students/min per serving station (it must be about this fast for
2 stations to serve ~2,360 Central students, mostly in the two hours of lunch breaks); 2 s per face scan; 15–35 s to collect a plate;
40–80 s along the food line; department sizes (rough) and MIT's lab-day share; food batch sizes and call levels.
**Arrival curve:** built from the department lunch breaks (MIT 12:00–13:00, or 13:00–14:00 on lab days; TAPMI 13:05–14:00;
DLHS/MILHS 12:40–13:40; SMI 12:00–13:00; DOC/MICFE 12:30–13:30; MLS 12:50–13:50; MIRM timing assumed 12:30–13:30). Rough sizes
(MIT 1,100, TAPMI 850, DOC 550, SMI 450, MLS + MIRM 100, DLHS/MILHS assumed 100) are scaled to the 2,960 plates. Each
department starts arriving when its break starts, with a lag of Normal(20, 20) min cut off at the end of the break: this lag is
**calibrated** (not measured) so the no-screen simulation fits the group's 17–25 min. The curve has two surges, ~12:10
(MIT + SMI) and a larger one at ~13:10–13:30 (MIT lab days + TAPMI + DOC + DLHS + MLS), which matches the full load seen at ~13:18
in the field visit. `[[simulation.slot.group]]` in `config/default.toml`; workbook tab *Arrival Curve*.

**A visit has four stages** (simulator): scan + collect a plate → queue for a serving station, served,
walk the food line → eat at a table (wait for a seat if full) → dispose of the plate. **Queue wait** =
time queueing for the scanner, a station and a seat. **Throughput** = door to leaving. Simulated
throughput: ~16.7 min for students who meet no queue, ~22.7 min around today's 13:17 peak (group: 17–25).

### Four scenarios, busy day, 60% follow the screens, 20 simulated lunches each (same students)

`python -m messq.scenarios` reproduces this (→ `results/scenarios.json`).

| Scenario | Queue wait (min) ± 95% CI | p90 wait | Throughput | p90 throughput | Stations busy Central / Munch | Run-outs | Redirected | Unsuccessful redirects |
|---|---|---|---|---|---|---|---|---|
| 1 Current system | 4.38 ± 0.53 | 13.5 | 20.9 | 29.8 | 65% / 17% | 0.5 | 0 | – |
| 2 Screens, queue information only | 1.30 ± 0.33 | 3.4 | 17.9 | 20.4 | 59% / 23% | 0.6 | 240 | 1% |
| **3 Screens + food status (proposal)** | 0.81 ± 0.09 | 2.2 | 17.4 | 19.2 | 58% / 24% | 0.7 | 286 | 3% |
| Naive: go to the shorter queue | 0.74 ± 0.07 | 2.0 | 17.3 | 19.0 | 58% / 24% | 0.5 | 277 | 4% |

An *unsuccessful redirect* is a redirected student whose wait plus walk was longer than the average wait of
students who stayed at the mess they left and arrived within 2 minutes.

### Stress tests (average queue wait, minutes)

| Changed input | 1 Current | 2 Queue only | 3 Proposal |
|---|---|---|---|
| Demand +20% (3,552 students) | 11.41 | 2.81 | 2.04 |
| Students rush at the bell (lag 15 +/- 10 min, not 20 +/- 20) | 8.86 | 1.93 | 1.78 |
| Heavy lab day: 70% of MIT eat 13:00-14:00 | 6.00 | 1.40 | 1.13 |
| No MIT labs: all MIT eat 12:00-13:00 | 8.86 | 1.27 | 1.29 |
| Stagger: SMI lunch 15 min earlier (11:45-12:45) | 3.16 | 0.65 | 0.62 |
| Stagger: TAPMI lunch 15 min later (13:20-14:15) | 1.90 | 0.90 | 0.56 |
| One bell curve (old assumption: peak 13:05, spread 35) | 5.19 | 1.03 | 0.86 |
| Only 30% follow the screens | 4.38 | 1.49 | 1.00 |
| Everyone follows the screens | 4.38 | 1.12 | 0.70 |
| Slower serving: 8 students/min per station | 12.88 | 1.96 | 1.78 |
| Faster serving: 12 students/min per station | 2.11 | 1.18 | 0.69 |
| More stock-outs: next batch never ready | 6.40 | 2.51 | 0.90 |
| No stock-outs: next batch always ready | 3.51 | 0.72 | 0.73 |
| Slower eating: 15-18 min | 4.38 | 1.30 | 0.81 |

The proposal cuts the wait in every stress test (by about 65–90%) and beats or ties "queue information
only" in every one. **Staggering one department's lunch by 15 minutes** cuts today's wait on its own: TAPMI
15 min later more than halves it, SMI 15 min earlier cuts it by about a quarter. That is evidence for
alternative A7 (needs academic administration).

### What the analysis found (under the ASSUMED parameters)

1. **Capacity is enough in total but used unevenly, and the 13:10 overlap is tight.** In the busiest 10 minutes
   (13:10) ~37 students/min arrive against 40/min of serving in both messes, but with the measured 80/20 habit
   split Central gets ~30/min against 20/min while Munch gets ~8/min.
2. **The LP optimum redirects about 9% of students** (261 of 2,960), close to the simulator's ~286. The LP
   is a fluid lower bound (0.04 min average) because it has no randomness and perfect foresight.
3. **Food is the binding constraint below ~860 star-dish portions at Munch.** Under that, each extra
   portion saves 20–40 student-minutes (the LP's shadow price): routing and food allocation must be
   planned together.
4. **Using food status the right way matters.** An earlier rule that penalised "running low" for everyone
   sent students away for nothing; charging the delay only to students who would reach an empty tray, and
   running the refill clock from the call, cut unsuccessful redirects and made food status help.
5. **The spreadsheet and the simulator agree when they make the same assumptions** (3.52 vs 3.80 min
   without screens, within 15%; the spreadsheet's steady-state formula is approximate in short slots near 100% busy).
   With screens the spreadsheet (0.47) is optimistic because it routes with perfect knowledge (workbook: Reconciliation).
6. **A 3rd serving station alone does best on normal days**; on busy and surge days the proposal beats a 3rd
   station alone (busy: 0.8 vs 1.1 min); proposal + a 3rd station is best on every kind of day but costs a
   station's staff every day (workbook: S7 Payoff Matrix).
7. **Earlier results understated run-outs.** A simulator bug let a queue be served "in the past" after a
   refill; fixed, run-outs now cost the time they should (this, and the department arrival curve, explain why the deck's earlier figures changed).

Older tables (hallway layout, earlier placeholder inputs) are in the git history.

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
