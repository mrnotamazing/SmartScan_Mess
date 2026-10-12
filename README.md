# Smart Mess Queue Balancer

Uses live entry scans from the mess face-recognition terminals (Matrix COSEC
ARGO FACE) to estimate how busy each mess is, and tells students which mess
to go to so the queues balance out.

**Status: Phase 1 (simulator + core logic) is done. Everything runs on
simulated data. Nothing connects to a real scanner yet.**

| Phase | What | State |
|---|---|---|
| 1 | Scanner adapter interface, fake-event simulator, occupancy/wait estimation, probabilistic routing, food-stock input, tests | ✅ done |
| 2 | Student display (kiosk + phone), kitchen "tray low / refilled" page, manager dashboard | next |
| 3 | Surge alerts (1-/5-min counts, learned baselines, cooldown, Telegram/WhatsApp) | |
| 4 | Real COSEC adapter (pycosec / official API) + CSV-export fallback | needs credentials + permission |
| 5 | A/B logging, metrics, report notebook | |
| 6 | Peak prediction, food forecasting, rewards | |

## Quick start

Requires Python 3.11+. The core has no third-party dependencies.

```bash
pip install pytest                 # only needed for the tests
python -m pytest                   # 23 tests

python -m messq.simulate --trace   # one simulated lunch, as the screen would show it
python -m messq.simulate           # Monte Carlo: no advice vs greedy vs equilibrium routing
python -m messq.simulate --slot dinner --runs 50 --compliance 0.2 0.4 0.6 0.8 1.0
```

Per-run results are written to `results/simulation_runs.csv`, ready for the analysis in your MDS report.

## How it works

```
 scanner adapter ──► engine ───────────────────────────────► recommendation
 (simulator now,     ├ dedupe events                          "Go to Mess B"
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
waits equal (a Wardrop equilibrium). Each phone user gets a random draw from
that split. The shared screen (Phase 2) will show the split ("Go to Mess B, 7 in 10
are being sent there"). When the split is close to even, the screen says
"Both halls OK".

**Partial compliance.** If you know (from a no-screen baseline) where
students go by habit and roughly what fraction follow advice, set
`engine.assumed_compliance` and `engine.natural_share`. The engine then
over-corrects so that the *realised* split is balanced.

## Phase 1 results (simulated lunch, 1,600 students, default config)

30 runs per row, ±95% CI. Wait = minutes from scanning in at the hall to sitting down with food.

| Policy | Compliance | Avg wait | p90 wait | Peak queue | Food run-outs | Occupancy est. error |
|---|---|---|---|---|---|---|
| No advice (habit 65/35) | – | 5.4 ± 0.3 | 14.8 ± 0.9 | 192 ± 11 | 1.1 | 35 people |
| Greedy ("go to emptier") | 60% | 2.0 ± 0.2 | 4.7 ± 0.5 | 72 ± 8 | 1.3 | 12 |
| Equilibrium split | 30% | 2.3 ± 0.2 | 6.2 ± 0.7 | 88 ± 9 | 1.3 | 14 |
| Equilibrium split | 60% | 1.9 ± 0.2 | 4.6 ± 0.6 | 70 ± 8 | 1.4 | 12 |
| Equilibrium split | 100% | 1.9 ± 0.2 | 4.6 ± 0.5 | 65 ± 7 | 1.2 | 12 |

Same thing, but with students reading the advice **5 minutes before they
arrive** (e.g. on their phone in the hostel), so feedback lags:

| Policy | Compliance | Avg wait | p90 wait | Peak queue |
|---|---|---|---|---|
| No advice | – | 5.5 ± 0.4 | 15.1 ± 1.1 | 194 ± 13 |
| Greedy | 60% | 3.3 ± 0.3 | 7.2 ± 0.6 | 116 ± 9 |
| Greedy | 100% | **4.4 ± 0.3** | 8.9 ± 0.5 | 144 ± 9 |
| Equilibrium split | 60% | 2.0 ± 0.3 | 5.3 ± 0.7 | 78 ± 10 |
| Equilibrium split | 100% | **1.9 ± 0.2** | 4.5 ± 0.6 | 69 ± 8 |

What this says (under the ASSUMED parameters):

1. With these parameters, balancing cuts the average wait from about 5.4 to about 2 minutes and the p90 wait from about 15 to about 5 minutes. Much of that comes from students who switch away from their habitual hall.
2. Greedy advice herds when the advice lags. In the 5-minute table it gets *worse* as more students obey it (3.3 → 4.4 min). The equilibrium split doesn't have this problem.
3. Balancing alone did **not** reduce food run-outs in this model. Total consumption is unchanged, and refills are triggered by stock level. Fewer run-outs need kitchen-side changes (earlier refill triggers, forecasting: Phase 6). Don't promise the vendor fewer run-outs from routing alone.
4. A missed "refilled" tap is dangerous. Before tap expiry was added, one missed tap kept a hall marked empty, sent every student to the other hall, and pushed one run to a 9-minute average wait. Taps now expire, and that case is a regression test.

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
- [ ] Where the scanners are: one per mess entrance, or a shared point?
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
   is why the no-advice case shows a 35-person estimation error. The
   backlog estimate partly fixes this, but only if the serving rate is
   measured.
2. **Seats are probably not the bottleneck; serving counters are.**
   `load = occupancy / seats` is shown, but the wait estimate is driven by
   counter throughput.
3. **Herding matters less than expected for a hallway screen 30 s from
   both halls.** Feedback is fast, so even greedy advice works there.
   Probabilistic routing matters once advice is read earlier (on phones).
   It is never worse, so it is the default.
4. **Compliance can't be measured per student from a shared screen**,
   because the screen doesn't know who read it. For the screen, measure it in
   aggregate (advised split vs observed split, screen-on vs screen-off
   days). Per-student compliance needs the phone page.
5. **Food run-outs**: see result 3 above.
