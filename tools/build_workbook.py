"""Build docs/Final_MDS_Decision_Workbook.xlsx: the MDS decision workbook for Beyond the Bottleneck.

    python tools/build_workbook.py docs/Final_MDS_Decision_Workbook.xlsx

Needs openpyxl (and scipy, to solve the student-flow LP). Every spreadsheet
calculation is a live formula that reads the Inputs tab. Simulator results are
read from results/*.json, written by `python -m messq.scenarios` (and its
--payoff and --reconcile options); rerun those first if the simulator changed.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, Series
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parent.parent
OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "docs" / "Final_MDS_Decision_Workbook.xlsx")
SCEN = json.loads((ROOT / "results" / "scenarios.json").read_text())
PAYOFF = json.loads((ROOT / "results" / "payoff.json").read_text())
RECON = json.loads((ROOT / "results" / "reconcile.json").read_text())
sys.path.insert(0, str(ROOT))
from messq.config import load_config  # noqa: E402

_CFG = load_config()
LUNCH = _CFG.simulation.slot("lunch")
HABIT_A = _CFG.simulation.habit_share["A"]
base = {r["scenario"]: r for r in SCEN["results"] if r["group"] == "base"}
STRESS = {(r["group"], r["scenario"][:1]): r["mean_wait_min"]["mean"] for r in SCEN["results"]}
PAYW = {(c["row"], c["col"]): c["mean_wait_min"]["mean"] for c in PAYOFF["cells"]}
W1, W2, W3 = (base[k]["mean_wait_min"]["mean"] for k in ["1 Current system", "2 Queue information only", "3 Queue + food (proposal)"])


def stress(prefix, sc="1"):
    return next(v for (g, k), v in STRESS.items() if g.startswith(prefix) and k == sc)


SIM_SOURCE = (f"Simulated: python -m messq.scenarios, {SCEN['runs_per_scenario']} lunches per row (seeds 0–"
              f"{SCEN['runs_per_scenario'] - 1}, the same students in every scenario); ± = 95% confidence interval")


FONT = "Arial"
BLUE, GREEN, BLACK, GREY = "0000FF", "008000", "000000", "595959"
F_HEAD = PatternFill("solid", fgColor="E7E6E1")
F_TITLE = PatternFill("solid", fgColor="1F3A5F")
F_KEY = PatternFill("solid", fgColor="FFFF00")
F_NOTE = PatternFill("solid", fgColor="EEF4FB")
F_OUT = PatternFill("solid", fgColor="E8F3E8")
THIN = Side(style="thin", color="C9C8C3")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
RUPEE = '"₹"#,##0;("₹"#,##0);-'
MIN1 = '0.0;-0.0;-'

wb = Workbook()
wb.remove(wb.active)


def sheet(name, title, session, widths):
    ws = wb.create_sheet(name)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[L(i)].width = w
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color="FFFFFF")
    ws["A1"].fill = F_TITLE
    for c in range(2, len(widths) + 1):
        ws.cell(row=1, column=c).fill = F_TITLE
    ws["A2"] = session
    ws["A2"].font = Font(name=FONT, size=10, italic=True, color=GREY)
    ws.sheet_view.showGridLines = False
    return ws


def put(ws, ref, value, *, kind="text", fmt=None, bold=False, fill=None, wrap=False, size=10, align=None, comment=None):
    """kind: text | input | formula | link | head | note"""
    c = ws[ref]
    c.value = value
    color = {"input": BLUE, "link": GREEN}.get(kind, BLACK)
    c.font = Font(name=FONT, size=size, bold=bold or kind == "head", color=color)
    if kind == "head":
        c.fill = F_HEAD
        c.alignment = CENTER
        c.border = BOX
    if kind in ("input", "formula", "link"):
        c.border = BOX
    if kind == "note":
        c.font = Font(name=FONT, size=9, italic=True, color=GREY)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    if wrap:
        c.alignment = WRAP
    if align:
        c.alignment = align
    if comment:
        c.comment = Comment(comment, "WGB3")
    return c


def table(ws, top, left, headers, rows, kinds=None, fmts=None, wrap_cols=()):
    """Write a header row + rows. kinds/fmts: per-column defaults."""
    for j, h in enumerate(headers):
        put(ws, f"{L(left + j)}{top}", h, kind="head")
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row):
            k = (kinds[j] if kinds else "text")
            if isinstance(v, str) and v.startswith("="):
                k = "link" if "!" in v else "formula"
            f = fmts[j] if fmts else None
            c = put(ws, f"{L(left + j)}{top + i}", v, kind=k, fmt=f, wrap=(j in wrap_cols))
            c.border = BOX
            if j in wrap_cols:
                c.alignment = WRAP
    return top + len(rows)


def note(ws, ref, text, span_to=None, height=None):
    put(ws, ref, text, kind="note")
    if span_to:
        ws.merge_cells(f"{ref}:{span_to}")
    if height:
        ws.row_dimensions[ws[ref].row].height = height


def q(name):  # quoted sheet reference
    return "'" + name.replace("'", "''") + "'"



# =============================================================================
# Inputs: ONE assumptions table. Every other tab reads from here.
# =============================================================================
INP = "Inputs"
ws = sheet(INP, "Inputs: every assumption the workbook and the simulator use",
           "Change BLUE cells only. Yellow = not measured yet (assumed or group estimate): replace with measured data. "
           "The simulator reads the same values from config/default.toml.",
           [70, 11, 15, 15, 58, 12, 34])
table(ws, 4, 1, ["Parameter", "Value", "Unit", "Status", "Source / how to measure", "Date", "Used in"], [])
SEP = "Sep 2026"
OCT = "Oct 2026"


def _day(hhmm):  # "12:30" -> Excel time (fraction of a day)
    h, m = hhmm.split(":")
    return (int(h) * 60 + int(m)) / 1440


DEPT_NOTES = {  # status and source for each department's size and break, from the group (Oct 2026)
    "MIT": ("Group estimate", "Group: ~1,100 (rough)", "Measured", "Department timetable"),
    "TAPMI": ("Group estimate", "Group: ~850 (rough)", "Measured", "Department timetable"),
    "DOC/MICFE": ("Group estimate", "Group: ~550 (rough)", "Measured", "Department timetable"),
    "SMI": ("Group estimate", "Group: ~450 (rough)", "Measured", "Department timetable"),
    "DLHS/MILHS": ("Assumed", "Size not known yet: taken as similar to MLS + MIRM", "Measured", "Department timetable"),
    "MLS": ("Assumed", "Group: MLS + MIRM ~100 together; half each assumed", "Measured", "Department timetable"),
    "MIRM": ("Assumed", "As MLS", "Assumed", "Timing not known: placed in the middle of the other breaks"),
}
DEPT_ROWS = [("sec", "DEPARTMENT LUNCH BREAKS (sizes are rough counts, used as shares and scaled to the plates served)")]
for _i, _g in enumerate(LUNCH.groups):
    _ns, _nsrc, _ts, _tsrc = DEPT_NOTES.get(_g.name, ("Assumed", "", "Assumed", ""))
    DEPT_ROWS += [
        (f"dn{_i}", f"{_g.name}: students (rough)", _g.students, "students", _ns, _nsrc, OCT, "Arrival Curve, simulator", "#,##0"),
        (f"ds{_i}", f"{_g.name}: lunch break starts", _day(_g.start), "time", _ts, _tsrc, OCT, "Arrival Curve, simulator", "hh:mm"),
        (f"de{_i}", f"{_g.name}: lunch break ends", _day(_g.end), "time", _ts, _tsrc, OCT, "Arrival Curve, simulator", "hh:mm"),
    ]
    if _g.alt_share:
        DEPT_ROWS += [
            (f"da{_i}", f"{_g.name}: share eating in the lab-day break (average weekday)", _g.alt_share, "share", "Assumed",
             "Labs: electrical 3 days/week, other branches 2. Assumed 5-day week, ~25% electrical: 0.75×2/5 + 0.25×3/5", OCT, "Arrival Curve, simulator", "0%"),
            (f"dx{_i}", f"{_g.name}: lab-day break starts", _day(_g.alt_start), "time", "Measured", "Group: 13:00–14:00 if there is a lab", OCT, "Arrival Curve, simulator", "hh:mm"),
            (f"dy{_i}", f"{_g.name}: lab-day break ends", _day(_g.alt_end), "time", "Measured", "As above", OCT, "Arrival Curve, simulator", "hh:mm"),
        ]
ROWS = [
    # key, label, value, unit, status, source, date, used in, fmt
    ("sec", "MEASURED (Phase 1 field work, CT, the group)"),
    ("students", "Students per lunch at Central CT + Munch (= plates served)", 2960, "students", "Measured",
     "Phase 1 deck: ~2,960 plates; one plate per student. Daily counts 2,810–3,465", SEP, "S15, LP Student Flow, all scenarios", "#,##0"),
    ("start", "Lunch opens", "11:30", "time", "Measured", "Mess timings 11:30–14:30", OCT, "S15, LP Student Flow", "@"),
    ("dur", "Lunch window length", 180, "minutes", "Measured", "11:30–14:30", OCT, "S15", "0"),
    ("seats_A", "Seats: Central CT", 900, "seats", "Measured", "Group measurement", OCT, "S15, simulator", "#,##0"),
    ("seats_B", "Seats: Munch Mess", 492, "seats", "Measured", "Group measurement", OCT, "S15, simulator", "#,##0"),
    ("c_A", "Serving stations: Central CT", 2, "stations", "Measured", "Group observation", OCT, "S15, LP, Decision Rule", "0"),
    ("c_B", "Serving stations: Munch Mess", 2, "stations", "Measured", "Group observation", OCT, "S15, LP, Decision Rule", "0"),
    ("sc_A", "Face scanners at the entrance: Central CT", 1, "scanners", "Measured", "Group observation", OCT, "S15", "0"),
    ("sc_B", "Face scanners at the entrance: Munch Mess", 1, "scanners", "Measured", "Group observation", OCT, "S15", "0"),
    ("visit", "Normal visit, scan to leaving (quiet times)", 20, "minutes", "Group estimate", "Group: about 20 min on a normal day", OCT, "Checks (calibration)", "0"),
    ("thr_lo", "Throughput time range: low (quiet)", 17, "minutes", "Group estimate", "Group: door to leaving takes 17–35 min depending on the rush", OCT, "Checks (calibration)", "0"),
    ("thr_hi", "Throughput time range: high (surge)", 35, "minutes", "Group estimate", "As above", OCT, "Checks (calibration)", "0"),
    ("lead_call", "Refill after the 'running low' call if the food must be made (make + send)", 30, "minutes", "Measured",
     "Group: the 30 min starts when the mess calls the kitchen", OCT, "Decision Rule, S18, simulator", "0"),
    ("send_lo", "Refill if the food is already made: sending only (low)", 10, "minutes", "Measured", "Group: 10–14 min", OCT, "Decision Rule, simulator", "0"),
    ("send_hi", "Refill if the food is already made: sending only (high)", 14, "minutes", "Measured", "Group: 10–14 min", OCT, "Decision Rule, simulator", "0"),
    ("delay_obs", "Delay faced by students at the peak (observed)", 15, "minutes", "Measured", "Phase 1 deck: ~15 min", SEP, "Checks (calibration)", "0"),
    ("sec", "THE FOUR STAGES OF A VISIT (group estimates where given, else assumed)"),
    ("scan_s", "Stage 1: one face scan", 2, "seconds", "Assumed", "Stopwatch at the scanner, or gaps between scans in the logs", "—", "S15, simulator", "0.0"),
    ("plate_lo", "Stage 1: collect a plate after the scan (low)", 28, "seconds", "Group estimate", "Group: scan + plate takes 30–45 s", "—", "S15, simulator", "0"),
    ("plate_hi", "Stage 1: collect a plate after the scan (high)", 43, "seconds", "Group estimate", "As above", "—", "S15, simulator", "0"),
    ("mu", "Stage 2: service rate per serving station", 10, "students/min", "Assumed",
     "≈6 s per student. Must be about this fast for 2 stations to serve ~2,360 Central students, mostly within two hours. Stopwatch 20–30 students", "—", "S15, LP, Decision Rule, simulator", "0.0"),
    ("line_lo", "Stage 2: rest of food collection after the station (low)", 54, "seconds", "Group estimate", "Group: collecting food takes 1–2 min without a queue, incl. ~6 s at the station", "—", "S15, simulator", "0"),
    ("line_hi", "Stage 2: rest of food collection (high)", 114, "seconds", "Group estimate", "As above", "—", "S15, simulator", "0"),
    ("eat_lo", "Stage 3: eating at a table (low)", 14, "minutes", "Group estimate", "Group: 14–18 min", OCT, "S15, simulator", "0"),
    ("eat_hi", "Stage 3: eating at a table (high)", 18, "minutes", "Group estimate", "As above", OCT, "S15, simulator", "0"),
    ("disp_lo", "Stage 4: dispose of leftovers and the plate (low)", 1, "minutes", "Group estimate", "Group: 2 min at most", OCT, "S15, simulator", "0.0"),
    ("disp_hi", "Stage 4: dispose of leftovers and the plate (high)", 2, "minutes", "Group estimate", "As above", OCT, "S15, simulator", "0.0"),
    ("sec", "BEHAVIOUR AND DEMAND"),
    ("habit", "Share who go to Central CT by habit (no screens)", round(HABIT_A, 3), "share", "Measured",
     "Group: ~2,360 eat at Central and ~600 at Munch of ~2,960. A day of biometric logs confirms it (Data Collection tab)", OCT, "S15, LP, scenarios", "0.0%"),
    ("comply", "Share of students who follow the screen", 0.6, "share", "Assumed", "The pilot measures it; stress-tested at 30% and 100%", "—", "S15, LP, scenarios", "0%"),
    ("walk", "Walk between the two mess doors", 0.5, "minutes", "Assumed", "30 s; walk it with a stopwatch", "—", "LP, Decision Rule, simulator", "0.0"),
    ("lag_m", "Minutes from the start of a department's lunch break to the mess door: mean", LUNCH.lag_mean_min, "minutes", "Calibrated",
     "Chosen so the no-screen simulation fits the 17–35 min visit and ~15 min peak delay. Logs + timetable measure it", "—", "Arrival Curve, simulator", "0"),
    ("lag_sd", "Same lag: spread (standard deviation); cut off at the end of the break", LUNCH.lag_sd_min, "minutes", "Calibrated",
     "Stress-tested at 15 ± 10 min (everyone rushes at the bell)", "—", "Arrival Curve, simulator", "0"),
    *DEPT_ROWS,
    ("sec", "FOOD"),
    ("ready_p", "Chance the next batch is already made when the mess calls", 0.7, "share", "Group estimate", "Group: about 70% of the time", OCT, "Decision Rule, simulator", "0%"),
    ("low_left", "Food left when the manager taps 'running low' (= calls the kitchen)", 20, "minutes", "Assumed",
     "Protocol for the manager. Record tap times and run-out times to check it", "—", "Decision Rule, simulator", "0"),
    ("helpings", "Star-dish servings per student", 1.0, "servings", "Assumed", "Star dish is refillable: measure portions issued ÷ plates", "—", "LP Food Allocation", "0.0"),
    ("F_B", "Star-dish portions Munch can serve this lunch (plan)", 1000, "portions", "Assumed", "Ask CT: batches planned for Munch", "—", "LP Student Flow (food constraint)", "#,##0"),
    ("K_food", "Star-dish portions the kitchen can have ready before the peak", 2400, "portions", "Assumed", "Ask CT", "—", "LP Food Allocation", "#,##0"),
    ("sec", "KINDS OF DAY (for the payoff matrix; from the biometric logs once available)"),
    ("p_norm", "Share of lunches that are normal (−20% students)", 0.3, "share", "Assumed", "Count days by arrivals in the logs", "—", "S7 Payoff Matrix", "0%"),
    ("p_busy", "Share of lunches that are busy (~2,960 students)", 0.5, "share", "Assumed", "As above", "—", "S7 Payoff Matrix", "0%"),
    ("p_surge", "Share of lunches with a surge and late refills", 0.2, "share", "Assumed", "As above", "—", "S7 Payoff Matrix", "0%"),
    ("sec", "POLICY SETTINGS (our choice)"),
    ("rho_max", "Target maximum utilisation per station", 0.85, "share", "Policy", "Above ~85% waits rise steeply (S15)", "—", "S15", "0%"),
    ("min_save", "Minimum saving before a screen suggests switching", 2, "minutes", "Policy", "Prototype setting (config: layout.min_saving_min)", "—", "Decision Rule, S18, simulator", "0.0"),
    ("margin", "Extra margin for estimate uncertainty", 0.5, "minutes", "Policy", "Added to the minimum saving in the decision rule", "—", "Decision Rule", "0.0"),
    ("stale", "No advice if a scanner has sent nothing for", 3, "minutes", "Policy", "Data check: a silent scanner means the estimate is stale", "—", "Decision Rule", "0"),
]
REF = {}
r = 5
for row in ROWS:
    if row[0] == "sec":
        put(ws, f"A{r}", row[1], bold=True)
        ws[f"A{r}"].font = Font(name=FONT, size=10, bold=True, color="1F3A5F")
        r += 1
        continue
    key, label, val, unit, status, src, date, used, fmt = row
    put(ws, f"A{r}", label)
    c = put(ws, f"B{r}", val, kind="input", fmt=fmt)
    if status in ("Assumed", "Group estimate", "Calibrated"):
        c.fill = F_KEY
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", status, bold=status == "Measured")
    put(ws, f"E{r}", src, wrap=True)
    put(ws, f"F{r}", date)
    put(ws, f"G{r}", used, wrap=True)
    REF[key] = f"{q(INP)}!$B${r}"
    r += 1
INPUT_FIRST, INPUT_LAST = 5, r - 1
r += 1
put(ws, f"A{r}", "DERIVED (formulas: do not type here)", bold=True)
ws[f"A{r}"].font = Font(name=FONT, size=10, bold=True, color="1F3A5F")
r += 1
DERIVED = [
    ("cap_A", "Serving capacity: Central CT (stations × service rate)", f"={REF['c_A']}*{REF['mu']}", "students/min", "0.0"),
    ("cap_B", "Serving capacity: Munch Mess", f"={REF['c_B']}*{REF['mu']}", "students/min", "0.0"),
    ("scan_A", "Scanner capacity: Central (scanners × 60 ÷ seconds per scan)", f"={REF['sc_A']}*60/{REF['scan_s']}", "students/min", "0.0"),
    ("scan_B", "Scanner capacity: Munch", f"={REF['sc_B']}*60/{REF['scan_s']}", "students/min", "0.0"),
    ("entry", "Stage 1 time with no queue: scan + collect a plate", f"=({REF['scan_s']}+({REF['plate_lo']}+{REF['plate_hi']})/2)/60", "minutes", "0.00"),
    ("line", "Stage 2 time after the station: walk the food line", f"=({REF['line_lo']}+{REF['line_hi']})/2/60", "minutes", "0.00"),
    ("eat", "Stage 3 mean eating time (a seat is held while eating)", f"=({REF['eat_lo']}+{REF['eat_hi']})/2", "minutes", "0.00"),
    ("disp", "Stage 4 mean disposal time", f"=({REF['disp_lo']}+{REF['disp_hi']})/2", "minutes", "0.00"),
    ("thr0", "Throughput with no queues: stage 1 + serving + food line + eating + disposal", None, "minutes", "0.0"),
    ("refill", "Expected refill time from the call: ready × (10–14 mean) + not ready × 30", f"={REF['ready_p']}*({REF['send_lo']}+{REF['send_hi']})/2+(1-{REF['ready_p']})*{REF['lead_call']}", "minutes", "0.0"),
    ("seatcap_A", "Arrivals the seats can absorb: Central (Little's Law: seats ÷ eating time)", None, "students/min", "0.0"),
    ("seatcap_B", "Arrivals the seats can absorb: Munch", None, "students/min", "0.0"),
]
for key, label, f, unit, fmt in DERIVED:
    if key == "thr0":
        f = f"={REF['entry']}+1/{REF['mu']}+{REF['line']}+{REF['eat']}+{REF['disp']}"
    if key == "seatcap_A":
        f = f"={REF['seats_A']}/{REF['eat']}"
    if key == "seatcap_B":
        f = f"={REF['seats_B']}/{REF['eat']}"
    put(ws, f"A{r}", label)
    put(ws, f"B{r}", f, kind="formula", fmt=fmt)
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", "Derived")
    REF[key] = f"{q(INP)}!$B${r}"
    r += 1
ws.freeze_panes = "B5"


# =============================================================================
# S2-3 Problem & Root Cause
# =============================================================================
ws = sheet("S2-3 Problem & Root Cause", "Problem definition, decision context and root causes",
           "Sessions 2–3: Nature of business decisions · Problem identification, structuring, root cause analysis", [30, 36, 36, 34, 34])
put(ws, "A4", "Problem statement (Phase 2: Beyond the Bottleneck)", bold=True)
put(ws, "A5", "During the 11:30–14:30 lunch window, Chefs Touch serves about 2,960 students at Central CT and Munch Mess, which serve the same menu "
              "30 seconds apart. Total serving capacity is enough on average but is used unevenly: one mess saturates while the other has spare capacity, "
              "so students wait (~15 min observed), and star-dish run-outs at the busy mess make it worse.", wrap=True)
ws.merge_cells("A5:E5")
ws.row_dimensions[5].height = 46
put(ws, "A6", "Primary decision (LP Student Flow): how many students should be directed to each mess in each 10-minute slot, so that waiting falls "
              "without adding staff or space? Constraints: serving capacity, food availability, walking time, compliance, demand uncertainty. "
              "Secondary decision (LP Food Allocation): how should the star dish be allocated and replenished to support that flow?", wrap=True)
ws.merge_cells("A6:E6")
ws.row_dimensions[6].height = 46
put(ws, "A8", "Session 2: nature of the decision", bold=True)
table(ws, 9, 1, ["Dimension", "Classification", "Why"], [
    ["Level", "Operational", "Made every lunch, minute by minute, at the mess door and in the kitchen"],
    ["Structure", "Structured / programmable", "The same choice repeats daily; inputs can be measured (scans, stock, stations)"],
    ["Certainty", "Under risk / uncertainty", "Daily demand varies; probabilities come from the biometric logs"],
    ["Frequency", "Recurring (daily)", "Justifies a model and a decision rule instead of ad-hoc judgement"],
    ["Decision makers", "Mess manager (food status), students (which mess)", "Students' choice of mess is itself a decision we can inform"],
], wrap_cols=(1, 2))
put(ws, "A16", "Session 3: 5 Whys, backtracked. Phase 1 stopped at a symptom; Phase 2 follows the chain to the root cause", bold=True)
table(ws, 17, 1, ["Why?", "Phase 1 answer (symptom)", "Phase 2 answer (after backtracking)", "Evidence", "Status"], [
    ["1. Why do students wait ~15 min?", "Food runs out at peak", "Central's serving stations are overloaded at peak", "Line was at the stations; trays and seats free (field visit)", "Observed"],
    ["2. Why are they overloaded?", "—", "~30 arrive/min against 20/min capacity at the 13:10 overlap, while Munch gets ~8", "S15 Queuing, Scenarios (simulated)", "Simulated; logs will confirm"],
    ["3. Why so uneven?", "—", "About 80% go to Central by habit (~2,360 of ~2,960)", "Inputs: habit share", "Measured (group)"],
    ["4. Why habit?", "—", "At the moment of choosing, nobody can see how busy either mess is", "S4 Biases", "Hypothesis (survey)"],
    ["5. Why not?", "—", "Every entry is already scanned, but the data is never used live", "Biometric system exists (COSEC)", "Observed"],
], wrap_cols=(0, 1, 2, 3))
for rr in range(18, 23):
    ws.row_dimensions[rr].height = 30
put(ws, "A24", "Food chain: star dishes run out mid-peak → refills start only at a 'running low' call → 30 min if not already made → no forecast from live arrivals. "
               "Both chains end at the same gap: live demand data exists but nobody acts on it.", wrap=True)
ws.merge_cells("A24:E24")
ws.row_dimensions[24].height = 30
put(ws, "A26", "Session 3: fishbone (cause-and-effect) for 'long wait at lunch'", bold=True)
table(ws, 27, 1, ["People", "Process", "Policy", "Information", "Logistics / place"], [
    ["Students arrive together at peak", "2 serving stations and 1 face scanner per mess", "Replenishment is reactive", "No live view of demand", "Delivery shares the student walkway"],
    ["Habit: same mess every day", "Refilling at the counter stops the line", "Base foods under-buffered", "Published menu ≠ served menu", "Return station not measured"],
    ["Herding: a long line looks better", "Serving rate not measured", "No reorder point", "No per-mess forecast", "One kitchen supplies five centres"],
], wrap_cols=(0, 1, 2, 3, 4))
for rr in range(28, 31):
    ws.row_dimensions[rr].height = 30
put(ws, "A32", "Issue tree (problem structuring)", bold=True)
table(ws, 33, 1, ["Branch", "Sub-question", "Tool in this workbook"], [
    ["Demand", "When and where do students arrive? Is Central really busier?", "Data Collection, S15 Queuing"],
    ["Capacity", "How many stations, how fast, how much spare at Munch?", "S15 Queuing, Scenarios (stress tests)"],
    ["Allocation of students", "How many to send to each mess, when?", "LP Student Flow (primary model), Decision Rule"],
    ["Allocation of food", "How much of the star dish to each mess, and when to refill?", "LP Food Allocation, Decision Rule (refill clock), S18"],
    ["Choice of intervention", "Which option is best on normal, busy and surge days?", "S7 Payoff Matrix, Scenarios"],
    ["Model trust", "Do the spreadsheet and the simulator agree?", "Reconciliation, Simulation Method, Checks"],
], wrap_cols=(1, 2))

# =============================================================================
# S4 Biases & Ethics
# =============================================================================
ws = sheet("S4 Biases & Ethics", "Decision biases and ethical decision making", "Session 4: Decision-making frameworks, decision biases, ethical decision making", [26, 48, 52, 22])
table(ws, 4, 1, ["Bias", "Where it shows up in the mess problem", "How the project counters it", "Status"], [
    ["Status quo / habit", "Students go to the same mess daily even when the other is faster", "Door screens show the faster option at the moment of choice", "Hypothesis: survey + logs"],
    ["Herding", "A long line reads as a sign the food is better; if everyone follows one signal, the 'empty' mess becomes the busy one", "Equal-wait split + 2-minute minimum saving (Decision Rule)", "Shown in simulation (Scenarios: naive vs proposal)"],
    ["Loss aversion", "The 30-second walk feels like a cost; minutes in line don't", "Show the saving in minutes ('save ~8 min')", "Hypothesis: survey"],
    ["No information (bounded rationality)", "From the door you can't see the other mess's queue", "Live estimates on screens and phones", "Observed"],
    ["Anchoring (planning)", "Kitchen plans from the published menu; the served menu differed", "Record the actual menu; forecast from observed arrivals", "Observed (field visit)"],
    ["Confirmation (our team)", "We want the screens to look good", "Report observed / assumed / simulated separately; if the logs show Munch is not underused, revise the diagnosis", "Built into this workbook"],
], wrap_cols=(1, 2, 3))
for rr in range(5, 11):
    ws.row_dimensions[rr].height = 30
put(ws, "A12", "Ethics checklist", bold=True)
table(ws, 13, 1, ["Principle", "What we do", "Status"], [
    ["Data minimisation (DPDP Act 2023)", "Request only scan time + mess + pseudonymous ID; no face data or templates", "Built into data request"],
    ["Pseudonymisation", "IDs hashed on reading; names hidden by default", "Built into prototype"],
    ["Purpose limitation & retention", "Use for this project only; delete at semester end", "Committed in email"],
    ["Honesty to students", "Suggest switching only if it saves ≥ 2 min; no advice when data is stale", "Built into prototype"],
    ["Consent / approval", "Written approval from college and vendor before any live connection", "Pending"],
    ["Fairness", "Advice is the same for everyone; no priority for any group", "Built into prototype"],
], kinds=["text", "text", "input"], wrap_cols=(1,))

# =============================================================================
# S5-6 Priority Matrix
# =============================================================================
PM = "S5-6 Priority Matrix"
ws = sheet(PM, "Decision dilemma and priority matrices", "Sessions 5–6: Decision dilemma and project priority matrix", [32, 18, 14, 12, 34, 40])
put(ws, "A4", "1. Menu criticality × predictability (ABC/XYZ), MDS_dataset.xlsx 'Priority Matrix', menu week 31 Aug–6 Sep", bold=True)
table(ws, 5, 1, ["Policy", "Class", "Menu entries", "Share", "What to do"], [
    ["Tight Control", "AZ", 28, "=C6/$C$10", "Measure and model: star dishes, chapattis, curd/raitha"],
    ["Calculated Issue", "AX", 9, "=C7/$C$10", "Derive from plate count: one-per-plate sweets"],
    ["Buffered Issue", "CZ", 40, "=C8/$C$10", "Issue with a safety margin: rice, dal, sambar, rasam, dry veg"],
    ["Free Issue", "CX", 26, "=C9/$C$10", "Issue without control: pickle, salt, sugar, fryums"],
    ["Total", "", "=SUM(C6:C9)", "=SUM(D6:D9)", ""],
], kinds=["text", "text", "input", "formula", "text"], fmts=[None, None, "0", "0%", None], wrap_cols=(4,))
note(ws, "F6", "The dataset's field notes label curd AX while its menu ratings give AZ; we follow the ratings.", "F8", 30)
put(ws, "A12", "2. Tray weights used by the live system (config/default.toml [[tray]]): how much a tray running low or out changes the advice", bold=True)
table(ws, 13, 1, ["Tray", "Item type (matrix)", "Class", "Weight", "When OUT", "Why this weight"], [
    ["Gravy sabji, Special rice", "Star dish", "AZ", "★ 1.0", "Outage: that mess serves nobody until the refill", "'The one item everyone notices when it is gone'"],
    ["Roti", "Made fresh in batches", "AZ", 0.5, "Adds 0.5 × expected refill time", "Running out is a speed problem; another tawa fixes it"],
    ["Dessert", "One per plate", "AX", 0.3, "Adds 0.3 × expected refill time", "Demand = plate count; errors are headcount errors"],
    ["Curd / raita", "Fresh side", "AZ", 0.3, "Adds 0.3 × expected refill time", "Risk is surplus more than shortage"],
    ["Dry sabji, Dal, Rice, Sambar / rasam", "Base food", "CZ", 0.1, "Adds 0.1 × expected refill time", "Interchangeable: 'quietly absorbed by another'"],
    ["Salt, pickle, fryums", "Table item", "CX", 0, "Not tracked", "Free issue"],
], wrap_cols=(0, 4, 5))
note(ws, "A20", "Running low: a tray costs a student time only if they reach the counter after it empties and before its refill (Decision Rule). "
     "Weights are the group's reading of the matrix; confirm them with the CT manager.", "F20", 30)
put(ws, "A22", "3. Intervention priority matrix (impact vs effort). Impact from the Scenarios tab; effort scores are the group's judgement.", bold=True)
put(ws, "A23", "Quadrant threshold (score above this = high)")
put(ws, "C23", 3, kind="input")
table(ws, 25, 1, ["Intervention", "Impact (1–5)", "Effort (1–5)", "Quadrant", "Reason (impact)", "Reason (effort)"], [
    [n, i, e, f'=IF(B{26+k}>$C$23,IF(C{26+k}>$C$23,"Major project","Quick win"),IF(C{26+k}>$C$23,"Thankless task","Fill-in"))', ri, re]
    for k, (n, i, e, ri, re) in enumerate([
        ("A2 Door screens, queue information only", 4, 3, f"Busy day: wait {W1:.1f} → {W2:.1f} min (simulated)", "Two screens + a laptop; needs data access"),
        ("A3 Screens + food status (proposal)", 5, 3, f"Busy day: wait {W1:.1f} → {W3:.1f} min (simulated)", "Same as A2 + manager taps food status"),
        ("A4 3rd serving station at Central", 4, 4, f"Busy day: {W1:.1f} → {PAYW[('A4 3rd serving station at Central (no screens)', 'S2 Busy day (2,960 students)')]:.1f} min; best on normal days", "Staff cost every day; space at counter"),
        ("A6 Larger buffers for base foods (CZ)", 2, 1, "Base foods ran dry in the field visit", "Just send more rice/dal/sambar"),
        ("A7 Stagger class end times", 4, 5, f"SMI 15 min earlier: today's wait {W1:.1f} → {stress('Stagger: SMI'):.1f} min; "
         f"TAPMI 15 min later: → {stress('Stagger: TAPMI'):.1f} (simulated)", "Needs academic administration"),
    ])
], kinds=["text", "input", "input", "formula", "text", "text"], wrap_cols=(4, 5))
put(ws, "A32", "4. Decision dilemmas", bold=True)
table(ws, 33, 1, ["Dilemma", "Option 1", "Option 2", "", "Trade-off", "How we resolve it"], [
    ["Send students to the other mess?", "Strong advice (risk herding)", "No advice (uneven load)", "", "Balance vs trust", "Equal-wait split + 2-min threshold (Decision Rule, S18)"],
    ["React to 'running low'?", "Redirect early (needless walks)", "Wait for 'out' (late)", "", "Walks vs waits", "Delay only for students who would reach an empty tray (Decision Rule)"],
    ["Add a serving station?", "Yes (staff every day)", "No (long peak waits)", "", "Staff cost vs waiting", "S7 Payoff Matrix (A4, A5) and Scenarios"],
], wrap_cols=(0, 1, 2, 4, 5))


DEF = {k: v for k, _l, v, *_ in [r for r in ROWS if r[0] != "sec"]}  # default input values, for solving in Python


def _bins(slot, nb):
    """Arrivals per 10-min slot: the same sum of cut-off normal curves as the Arrival Curve tab."""
    sd = slot.lag_sd_min
    out = [0.0] * nb
    for _nm, n, a, b in slot.cohorts():
        mu = a + slot.lag_mean_min
        phi = lambda x: 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))  # noqa: E731
        z = phi(b) - phi(a)
        for k in range(nb):
            out[k] += n * (phi(min(b, max(a, (k + 1) * 10))) - phi(min(b, max(a, k * 10)))) / z
    return out



# =============================================================================
# Arrival Curve: one curve per department lunch break, added up
# =============================================================================
AC = "Arrival Curve"
ws = sheet(AC, "When students arrive: department lunch breaks added up", "Feeds S15 Queuing and the LP. The simulator uses the same curve (config/default.toml)",
           [26, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14])
put(ws, "A3", "Scale: plates served ÷ sum of the rough department sizes")
dn_keys = [k for k in REF if k.startswith("dn")]
put(ws, "E3", f"={REF['students']}/({'+'.join(REF[k] for k in dn_keys)})", kind="link", fmt="0.000")
COH = []  # (name, students formula, start key, end key)
for i_, g_ in enumerate(LUNCH.groups):
    n_, s_, e_ = REF[f"dn{i_}"], REF[f"ds{i_}"], REF[f"de{i_}"]
    if g_.alt_share:
        a_ = REF[f"da{i_}"]
        COH.append((g_.name, f"{n_}*(1-{a_})*$E$3", s_, e_))
        COH.append((f"{g_.name} (lab day)", f"{n_}*{a_}*$E$3", REF[f"dx{i_}"], REF[f"dy{i_}"]))
    else:
        COH.append((g_.name, f"{n_}*$E$3", s_, e_))
open_ = f"TIMEVALUE({REF['start']})"
table(ws, 5, 1, ["Cohort", "Students (scaled)", "Break starts (min after opening)", "Break ends (min)", "Mean arrival (min)", "Share of the curve inside the break"], [
    [nm, f"={nf}", f"=ROUND(({st}-{open_})*1440,0)", f"=ROUND(({en}-{open_})*1440,0)", f"=C{6+k}+{REF['lag_m']}",
     f"=NORMDIST(D{6+k},E{6+k},{REF['lag_sd']},TRUE)-NORMDIST(C{6+k},E{6+k},{REF['lag_sd']},TRUE)"]
    for k, (nm, nf, st, en) in enumerate(COH)
], fmts=[None, "0", "0", "0", "0", "0.000"])
ws.row_dimensions[5].height = 30
C_LAST = 5 + len(COH)
put(ws, f"A{C_LAST+1}", "Total")
put(ws, f"B{C_LAST+1}", f"=SUM(B6:B{C_LAST})", kind="formula", fmt="#,##0")
note(ws, f"A{C_LAST+2}", "Each department starts arriving when its lunch break starts. A student's lag after the break starts is Normal(mean, spread) from the Inputs tab, "
     "cut off at the end of the break, so each cohort's arrivals add up to its size. MIT eats 13:00–14:00 on lab days. The sizes are rough and add up to more than "
     "the plates served, so they are used as shares. The biometric logs replace this whole tab once available.", f"L{C_LAST+2}", 44)
AG = C_LAST + 4
put(ws, f"A{AG}", "Arrivals per 10-minute slot", bold=True)
heads = ["Slot", "Minute"] + [c[0] for c in COH] + ["Total", "Share"]
table(ws, AG + 1, 1, heads, [])
ws.row_dimensions[AG + 1].height = 30
AF = AG + 2
for b_ in range(18):
    r_ = AF + b_
    m_ = 11 * 60 + 30 + b_ * 10
    put(ws, f"A{r_}", f"{m_ // 60:02d}:{m_ % 60:02d}")
    put(ws, f"B{r_}", b_ * 10, fmt="0")
    for k, _c in enumerate(COH):
        cr = 6 + k
        lo = f"MIN($D${cr},MAX($C${cr},$B{r_}))"
        hi = f"MIN($D${cr},MAX($C${cr},$B{r_}+10))"
        put(ws, f"{L(3+k)}{r_}", f"=$B${cr}*(NORMDIST({hi},$E${cr},{REF['lag_sd']},TRUE)-NORMDIST({lo},$E${cr},{REF['lag_sd']},TRUE))/$F${cr}",
            kind="link", fmt="0")
    tc = L(3 + len(COH))
    put(ws, f"{tc}{r_}", f"=SUM(C{r_}:{L(2+len(COH))}{r_})", kind="formula", fmt="0", fill=F_OUT)
    put(ws, f"{L(4+len(COH))}{r_}", f"={tc}{r_}/SUM(${tc}${AF}:${tc}${AF+17})", kind="formula", fmt="0.0%")
AL = AF + 17
AC_TOT = f"{q(AC)}!${L(3+len(COH))}$"
AC_SHR = f"{q(AC)}!${L(4+len(COH))}$"
put(ws, f"A{AL+2}", "Busiest 10-minute slot")
put(ws, f"B{AL+2}", f"=INDEX(A{AF}:A{AL},MATCH(MAX({L(3+len(COH))}{AF}:{L(3+len(COH))}{AL}),{L(3+len(COH))}{AF}:{L(3+len(COH))}{AL},0))", kind="formula", fill=F_OUT)
put(ws, f"A{AL+3}", "Students arriving in it (both messes)")
put(ws, f"B{AL+3}", f"=MAX({L(3+len(COH))}{AF}:{L(3+len(COH))}{AL})", kind="formula", fmt="0", fill=F_OUT)
put(ws, f"A{AL+4}", "Capacity of both messes in 10 min (4 stations)")
put(ws, f"B{AL+4}", f"=({REF['cap_A']}+{REF['cap_B']})*10", kind="link", fmt="0")
_pk = max(_bins(LUNCH, 18))
_capb = (DEF["c_A"] + DEF["c_B"]) * DEF["mu"] * 10
note(ws, f"A{AL+5}", "Two surges: about 12:10 (MIT and SMI) and a larger one about 13:10–13:30, when MIT's lab-day batch, TAPMI, DOC/MICFE, DLHS/MILHS and MLS "
     f"overlap. In the busiest slot arrivals reach about {_pk / _capb:.0%} of what both messes together can serve, and {DEF['habit']:.0%} of them head to Central, "
     f"which alone can serve only {DEF['c_A'] * DEF['mu'] * 10:.0f}. Balancing uses Munch's spare capacity; "
     "staggering one department's break by 15 minutes is the demand-side fix (Scenarios: stagger tests).", f"L{AL+5}", 44)
bc = BarChart()
bc.type, bc.grouping, bc.overlap = "col", "stacked", 100
bc.title = "Arrivals per 10 minutes, by department"
bc.y_axis.title = "Students"
bc.add_data(Reference(ws, min_col=3, max_col=2 + len(COH), min_row=AG + 1, max_row=AL), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=1, min_row=AF, max_row=AL))
bc.height, bc.width = 9, 22
ws.add_chart(bc, f"A{AL+8}")


# =============================================================================
# S15 Queuing
# =============================================================================
QS = "S15 Queuing"
ws = sheet(QS, "Queuing analysis: M/M/1, M/M/c and lunch-peak overload, without vs with the screens",
           "Session 15: Introduction to queuing theory and waiting-line models", [12, 11, 11] + [10] * 40)
put(ws, "A4", "1. Check against the lecture example (Hatti Kaapi, M/M/1)", bold=True)
table(ws, 5, 1, ["λ /hour", "μ /hour", "ρ", "Wq (hours)", "Wq (min)", "W (min)", "Lq", "L"], [
    [18, 24, "=A6/B6", "=A6/(B6*(B6-A6))", "=D6*60", "=60/(B6-A6)", "=A6*D6", "=A6*F6/60"],
], kinds=["input", "input"] + ["formula"] * 6, fmts=["0", "0", "0%", "0.000", "0.0", "0.0", "0.00", "0.00"])
note(ws, "A7", "Lecture answers: ρ = 75%, Wq = 7.5 min, W = 10 min, Lq = 2.25. If these match, the formulas below are right.", "H7")
put(ws, "J4", "2. Why waits explode near 100% busy (M/M/1, one serving station)", bold=True)
put(ws, "J5", "μ per hour", kind="head")
put(ws, "K5", f"={REF['mu']}*60", kind="link", fmt="0")
table(ws, 6, 10, ["ρ", "λ /hour", "Wq (min)", "Lq"], [
    [rho, f"=J{7+k}*$K$5", f"=K{7+k}/($K$5*($K$5-K{7+k}))*60", f"=K{7+k}*L{7+k}/60"] for k, rho in enumerate([0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.93, 0.95, 0.96, 0.97, 0.98])
], kinds=["input", "formula", "formula", "formula"], fmts=["0%", "0", "0.00", "0.0"])
ch = LineChart()
ch.title = "Average wait vs utilisation (M/M/1)"
ch.y_axis.title = "Wq (minutes)"
ch.x_axis.title = "Utilisation ρ"
ch.add_data(Reference(ws, min_col=12, min_row=6, max_row=18), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=10, min_row=7, max_row=18))
ch.height, ch.width = 7, 12
ch.legend = None
ws.add_chart(ch, "O4")

B0 = 22
put(ws, f"A{B0}", "3. Lunch by 10-minute slot: without vs with the door screens (M/M/c, plus a fluid queue for overload)", bold=True)
note(ws, f"A{B0+1}", "Arrivals = the department lunch breaks added up (Arrival Curve tab; shape ASSUMED until the biometric logs "
     "replace column C). Backlog (end of slot) = max(0, backlog at the start + arrivals − capacity × 10): the line carried from slot to slot. "
     "Queue wait = (backlog at the start + backlog at the end) ÷ 2 ÷ capacity (the line a student meets half-way through the slot) + the M/M/c wait "
     "with ρ capped at 95% for the randomness a smooth average misses (P(wait) and Wq random use the capped rate; the live engine uses the same rule). Throughput = stage 1 + queue wait + serving + food line + "
     "eating + disposal. 'With screens' moves the share who comply toward equal utilisation in every slot, with perfect knowledge (see Reconciliation).", f"AK{B0+1}", 58)
put(ws, f"A{B0+3}", "Equal-utilisation share for Central")
put(ws, f"E{B0+3}", f"={REF['cap_A']}/({REF['cap_A']}+{REF['cap_B']})", kind="link", fmt="0.0%")
put(ws, f"A{B0+4}", "Realised share for Central with screens")
put(ws, f"E{B0+4}", f"={REF['habit']}+{REF['comply']}*(E{B0+3}-{REF['habit']})", kind="link", fmt="0.0%")
note(ws, f"F{B0+3}", "Formula: capacity of Central ÷ (capacity of Central + capacity of Munch)", f"N{B0+3}")
note(ws, f"F{B0+4}", "Formula: habit + compliance × (target − habit). Only students who follow the screen move", f"N{B0+4}")
HR = B0 + 6
SR = HR + 1
FR = SR + 1
N_BINS = 18
LR = FR + N_BINS - 1
groups = [("Without screens — Central CT", "A", "nA"), ("Without screens — Munch", "B", "nB"),
          ("With screens — Central CT", "A", "wA"), ("With screens — Munch", "B", "wB")]
put(ws, f"A{SR}", "Slot start", kind="head")
put(ws, f"B{SR}", "Curve share", kind="head")
put(ws, f"C{SR}", "Arrivals (both messes)", kind="head")
put(ws, f"D{SR}", "λ total /min", kind="head")
sub = ["λ /min", "Scanner ρ", "ρ", "P(wait)", "Wq random (min)", "Backlog end", "Queue wait (min)", "Throughput (min)", "People inside"]
COLS = {}
col = 5
for gname, mess, gk in groups:
    ws.merge_cells(start_row=HR, start_column=col, end_row=HR, end_column=col + len(sub) - 1)
    put(ws, f"{L(col)}{HR}", gname, kind="head")
    for j, s in enumerate(sub):
        put(ws, f"{L(col + j)}{SR}", s, kind="head")
    COLS[gk] = {s: L(col + j) for j, s in enumerate(sub)}
    COLS[gk]["mess"] = mess
    col += len(sub)
ws.row_dimensions[SR].height = 30
K = "{0,1,2,3,4,5,6,7,8,9}"
for i in range(N_BINS):
    r_ = FR + i
    m = (11 * 60 + 30 + i * 10)
    put(ws, f"A{r_}", f"{m // 60:02d}:{m % 60:02d}", kind="text")
    put(ws, f"B{r_}", f"={AC_SHR}{AF + i}", kind="link", fmt="0.0%")
    put(ws, f"C{r_}", f"={AC_TOT}{AF + i}", kind="link", fmt="0")
    put(ws, f"D{r_}", f"=C{r_}/10", kind="formula", fmt="0.0")
    for gk, cols in COLS.items():
        A = cols["mess"] == "A"
        c_ = REF["c_A"] if A else REF["c_B"]
        share = (f"{REF['habit']}" if gk == "nA" else f"(1-{REF['habit']})" if gk == "nB"
                 else f"$E${B0+4}" if gk == "wA" else f"(1-$E${B0+4})")
        lam, scr, rho, pw, wq, bl, ew, thr, ppl = (cols[s] for s in sub)
        put(ws, f"{lam}{r_}", f"=$D{r_}*{share}", kind="link", fmt="0.0")
        put(ws, f"{scr}{r_}", f"={lam}{r_}/{REF['scan_A'] if A else REF['scan_B']}", kind="link", fmt="0%")
        put(ws, f"{rho}{r_}", f"={lam}{r_}/({c_}*{REF['mu']})", kind="link", fmt="0%")
        # Randomness term: the M/M/c wait with ρ capped at 95% (Erlang C blows up at 100%; the backlog handles overload).
        # Same rule as the live engine (messq/waits.py, RHO_CAP).
        lc = f"MIN({lam}{r_},0.95*{c_}*{REF['mu']})"
        a = f"({lc}/{REF['mu']})"
        top = f"({a}^{c_}/FACT({c_})*{c_}/({c_}-{a}))"
        put(ws, f"{pw}{r_}", f'=IF({lam}{r_}>0,{top}/(SUMPRODUCT(--({K}<{c_}),{a}^{K}/FACT({K}))+{top}),0)', kind="link", fmt="0.00")
        put(ws, f"{wq}{r_}", f'=IF({lam}{r_}>0,{pw}{r_}/({c_}*{REF["mu"]}-{lc}),0)', kind="link", fmt="0.00")
        prev = "0" if i == 0 else f"{bl}{r_-1}"
        put(ws, f"{bl}{r_}", f"=MAX(0,{prev}+({lam}{r_}-{c_}*{REF['mu']})*10)", kind="link", fmt="0")
        # A student arriving during the slot meets, on average, the line half-way through it (fluid part), plus the
        # random part that a smooth average misses (M/M/c at ρ ≤ 95%).
        put(ws, f"{ew}{r_}", f"=({prev}+{bl}{r_})/2/({c_}*{REF['mu']})+{wq}{r_}", kind="link", fmt="0.0")
        put(ws, f"{thr}{r_}", f"={REF['entry']}+{ew}{r_}+1/{REF['mu']}+{REF['line']}+{REF['eat']}+{REF['disp']}", kind="link", fmt="0.0")
        put(ws, f"{ppl}{r_}", f"={lam}{r_}*{thr}{r_}", kind="formula", fmt="0")
S0 = LR + 2
put(ws, f"A{S0}", "Summary", bold=True)
table(ws, S0 + 1, 1, ["Measure", "", "", "", "Without: Central", "Without: Munch", "With: Central", "With: Munch", "Without: both", "With: both"], [])
mrow = S0 + 2
def rng(gk, s): return f"{COLS[gk][s]}{FR}:{COLS[gk][s]}{LR}"
measures = [
    ("Average queue wait per student (min)", lambda gk: f"=SUMPRODUCT({rng(gk,'Queue wait (min)')},{rng(gk,'λ /min')})/SUM({rng(gk,'λ /min')})", "0.00"),
    ("Average throughput, door to leaving (min)", lambda gk: f"=SUMPRODUCT({rng(gk,'Throughput (min)')},{rng(gk,'λ /min')})/SUM({rng(gk,'λ /min')})", "0.0"),
    ("Peak utilisation ρ (serving)", lambda gk: f"=MAX({rng(gk,'ρ')})", "0%"),
    ("Peak scanner utilisation", lambda gk: f"=MAX({rng(gk,'Scanner ρ')})", "0%"),
    ("Largest queue (students)", lambda gk: f"=MAX({rng(gk,'Backlog end')})", "0"),
    ("Longest queue wait (min)", lambda gk: f"=MAX({rng(gk,'Queue wait (min)')})", "0.0"),
    ("Peak people inside (Little's Law L = λW, includes the queue)", lambda gk: f"=MAX({rng(gk,'People inside')})", "0"),
    ("Peak seats needed (served per min × eating time; the stations cap the served rate)",
     lambda gk: f"=MIN(MAX({rng(gk,'λ /min')}),{REF['c_A'] if COLS[gk]['mess']=='A' else REF['c_B']}*{REF['mu']})*{REF['eat']}", "0"),
    ("Seats", lambda gk: f"={REF['seats_A'] if COLS[gk]['mess']=='A' else REF['seats_B']}", "0"),
]
for k, (label, fn, fmt) in enumerate(measures):
    rr = mrow + k
    put(ws, f"A{rr}", label)
    ws.merge_cells(f"A{rr}:D{rr}")
    for j, gk in enumerate(["nA", "nB", "wA", "wB"]):
        put(ws, f"{L(5+j)}{rr}", fn(gk), kind="formula", fmt=fmt)
    if k in (0, 1):
        put(ws, f"I{rr}", f"=(E{rr}*SUM({rng('nA','λ /min')})+F{rr}*SUM({rng('nB','λ /min')}))/SUM(D{FR}:D{LR})", kind="formula", fmt=fmt, fill=F_OUT)
        put(ws, f"J{rr}", f"=(G{rr}*SUM({rng('wA','λ /min')})+H{rr}*SUM({rng('wB','λ /min')}))/SUM(D{FR}:D{LR})", kind="formula", fmt=fmt, fill=F_OUT)
QS_AVG_WITHOUT = f"{q(QS)}!$I${mrow}"
QS_AVG_WITH = f"{q(QS)}!$J${mrow}"
QS_THR_WITHOUT = f"{q(QS)}!$I${mrow+1}"
QS_THR_WITH = f"{q(QS)}!$J${mrow+1}"
QS_PEAKRHO_WB = f"{q(QS)}!$H${mrow+2}"
QS_ARR = f"{q(QS)}!$C${FR}:$C${LR}"
QS_SHARE = f"{q(QS)}!$B${FR}:$B${LR}"
QS_FR, QS_LR = FR, LR
note(ws, f"A{mrow+len(measures)+1}", "Reading it: above ~85–90% utilisation waits climb steeply; above 100% the queue grows every minute (backlog column). "
     "The screens lower the peak utilisation of Central by moving some students to Munch. This spreadsheet measures the queue at the serving stations only; "
     "the simulator also counts the scanner queue and any wait for a seat, and adds run-outs (Reconciliation tab).", f"N{mrow+len(measures)+1}", 40)
ch = LineChart()
ch.title = "Queue wait per 10-min slot"
ch.y_axis.title = "Minutes"
for gk in ["nA", "wA", "nB", "wB"]:
    cl = ws[f"{COLS[gk]['Queue wait (min)']}{SR}"].column
    s = Series(Reference(ws, min_col=cl, min_row=FR, max_row=LR), title={"nA": "Central, without", "wA": "Central, with", "nB": "Munch, without", "wB": "Munch, with"}[gk])
    ch.series.append(s)
ch.set_categories(Reference(ws, min_col=1, min_row=FR, max_row=LR))
ch.height, ch.width = 8, 16
ws.add_chart(ch, f"L{S0}")
ws.freeze_panes = f"B{FR}"


# =============================================================================
# LP Student Flow (PRIMARY decision model)
# =============================================================================
D_BINS = _bins(LUNCH, N_BINS)
CAP_A, CAP_B = DEF["c_A"] * DEF["mu"], DEF["c_B"] * DEF["mu"]


def solve_flow(D, h, k, capA, capB, walk, FB):
    """min 10·Σ(QA+QB) + walk·Σy  s.t. fluid queue recursions, y ≤ k·h·D, Munch food ≤ FB."""
    T = len(D)
    n = 3 * T
    c = np.r_[np.full(T, walk), np.full(T, 10.0), np.full(T, 10.0)]
    A, b = [], []
    for t in range(T):
        row = np.zeros(n); row[T + t] = -1; row[t] = -1  # noqa: E702
        if t:
            row[T + t - 1] = 1
        A.append(row); b.append(-(h * D[t] - 10 * capA))  # noqa: E702
        row = np.zeros(n); row[2 * T + t] = -1; row[t] = 1  # noqa: E702
        if t:
            row[2 * T + t - 1] = 1
        A.append(row); b.append(-((1 - h) * D[t] - 10 * capB))  # noqa: E702
    row = np.zeros(n); row[:T] = 1  # noqa: E702
    A.append(row); b.append(FB - (1 - h) * sum(D))  # noqa: E702
    bounds = [(0, k * h * D[t]) for t in range(T)] + [(0, None)] * (2 * T)
    res = linprog(c, A_ub=np.array(A), b_ub=np.array(b), bounds=bounds, method="highs")
    assert res.status == 0, res.message
    return res.x[:T], res.x[T:2 * T], res.x[2 * T:], res.fun, -res.ineqlin.marginals[2 * T]


Y, QA, QB, LP_OBJ, LP_DUAL = solve_flow(D_BINS, DEF["habit"], DEF["comply"], CAP_A, CAP_B, DEF["walk"], DEF["F_B"])
LPF = "LP Student Flow"
ws = sheet(LPF, "Linear programming (primary model): how many students to direct to each mess in each 10-minute slot",
           "Sessions 10–11: LP formulation, constraints, Solver/simplex, shadow prices · solved with SciPy (HiGHS); re-solve in Excel with Solver",
           [14, 12, 12, 12, 12, 13, 12, 12, 13, 13, 12, 12, 13, 13])
put(ws, "A4", "Formulation (a fluid queue: each slot's queue = last slot's queue + arrivals − what the stations serve)", bold=True)
for k_, line in enumerate([
    "Decision variables: y(t) = students redirected from Central to Munch in slot t; QA(t), QB(t) = students still queueing at Central / Munch at the end of slot t",
    "Objective: minimise total student-minutes of waiting = 10 × Σ [QA(t) + QB(t)] + walk × Σ y(t)   (queue × 10-minute slot, plus 0.5 min per redirected student)",
    "Subject to: QA(t) ≥ QA(t−1) + h·D(t) − y(t) − 10·capA;   QB(t) ≥ QB(t−1) + (1−h)·D(t) + y(t) − 10·capB   (queues carry over; capacity per slot = 10 min × students/min)",
    "            0 ≤ y(t) ≤ κ·h·D(t)  (only students at Central's door who follow the screen can move);   Σ [(1−h)·D(t) + y(t)] ≤ F_B  (Munch's star-dish portions)",
    "            QA, QB ≥ 0.   Data: D(t) arrivals (S15), h habit share, κ compliance, cap = stations × service rate (Inputs). Food is the operational constraint.",
]):
    put(ws, f"A{5+k_}", line)
    ws.merge_cells(f"A{5+k_}:N{5+k_}")
put(ws, "A11", "Parameters (from Inputs)", bold=True)
pars = [("h: share heading to Central by habit", REF["habit"], "0%"), ("κ: share who follow the screen", REF["comply"], "0%"),
        ("capA: Central serving capacity (/min)", REF["cap_A"], "0.0"), ("capB: Munch serving capacity (/min)", REF["cap_B"], "0.0"),
        ("Walk between doors (min)", REF["walk"], "0.0"), ("F_B: Munch star-dish portions", REF["F_B"], "#,##0")]
PCELL = {}
for k_, (lab, ref, fmt) in enumerate(pars):
    put(ws, f"A{12+k_}", lab)
    ws.merge_cells(f"A{12+k_}:C{12+k_}")
    put(ws, f"D{12+k_}", f"={ref}", kind="link", fmt=fmt)
    PCELL[lab.split(":")[0]] = f"$D${12+k_}"
h_, k_c, cA, cB, wk, FB = (PCELL[x] for x in ["h", "κ", "capA", "capB", "Walk between doors (min)", "F_B"])
T0 = 19
hdr = ["Slot", "Arrivals D(t)", "At Central by habit h·D", "At Munch by habit", "Max redirect κ·h·D", "y(t) redirect (decision)",
       "QA(t) (decision)", "QB(t) (decision)", "Central constraint slack ≥ 0", "Munch constraint slack ≥ 0",
       "Today: QA (no redirect)", "Today: QB", "Central arrivals after", "Munch arrivals after"]
for j, hh in enumerate(hdr):
    put(ws, f"{L(1+j)}{T0}", hh, kind="head")
ws.row_dimensions[T0].height = 44
for i in range(N_BINS):
    r_ = T0 + 1 + i
    m = 11 * 60 + 30 + i * 10
    put(ws, f"A{r_}", f"{m // 60:02d}:{m % 60:02d}")
    put(ws, f"B{r_}", f"={q(QS)}!$C${QS_FR + i}", kind="link", fmt="0.0")
    put(ws, f"C{r_}", f"=B{r_}*{h_}", kind="formula", fmt="0.0")
    put(ws, f"D{r_}", f"=B{r_}*(1-{h_})", kind="formula", fmt="0.0")
    put(ws, f"E{r_}", f"={k_c}*C{r_}", kind="formula", fmt="0.0")
    put(ws, f"F{r_}", round(float(Y[i]), 6), kind="input", fmt="0.0", fill=F_KEY)
    put(ws, f"G{r_}", round(float(QA[i]), 6), kind="input", fmt="0.0", fill=F_KEY)
    put(ws, f"H{r_}", round(float(QB[i]), 6), kind="input", fmt="0.0", fill=F_KEY)
    pa, pb, pka, pkb = ("0", "0", "0", "0") if i == 0 else (f"G{r_-1}", f"H{r_-1}", f"K{r_-1}", f"L{r_-1}")
    put(ws, f"I{r_}", f"=G{r_}-({pa}+C{r_}-F{r_}-10*{cA})", kind="formula", fmt="0.0;-0.0;0.0")
    put(ws, f"J{r_}", f"=H{r_}-({pb}+D{r_}+F{r_}-10*{cB})", kind="formula", fmt="0.0;-0.0;0.0")
    put(ws, f"K{r_}", f"=MAX(0,{pka}+C{r_}-10*{cA})", kind="formula", fmt="0.0")
    put(ws, f"L{r_}", f"=MAX(0,{pkb}+D{r_}-10*{cB})", kind="formula", fmt="0.0")
    put(ws, f"M{r_}", f"=C{r_}-F{r_}", kind="formula", fmt="0.0")
    put(ws, f"N{r_}", f"=D{r_}+F{r_}", kind="formula", fmt="0.0")
T1, T2 = T0 + 1, T0 + N_BINS
TR = T2 + 1
put(ws, f"A{TR}", "Total", bold=True)
for cl in "BCDEFGHKLMN":
    put(ws, f"{cl}{TR}", f"=SUM({cl}{T1}:{cl}{T2})", kind="formula", fmt="#,##0")
R0 = TR + 2
put(ws, f"A{R0}", "Results", bold=True)
LPR = {}
res_rows = [
    ("obj", "Objective: student-minutes waiting + walking (LP optimum)", f"=10*SUM(G{T1}:H{T2})+{wk}*SUM(F{T1}:F{T2})", "#,##0"),
    ("base", "Today (no redirection): student-minutes waiting", f"=10*SUM(K{T1}:L{T2})", "#,##0"),
    ("avg_opt", "Average per student, LP optimum (min)", f"=B{R0+1}/B{TR}", "0.00"),
    ("avg_base", "Average per student, today (min)", f"=B{R0+2}/B{TR}", "0.00"),
    ("redir", "Students redirected to Munch", f"=F{TR}", "#,##0"),
    ("redir_pct", "Share of all students redirected", f"=F{TR}/B{TR}", "0.0%"),
    ("food_use", "Munch star-dish portions used (must be ≤ F_B)", f"=N{TR}", "#,##0"),
    ("food_ok", "Food constraint satisfied?", f'=IF(B{R0+7}<={FB}+0.5,"Yes","No")', None),
    ("min_slack", "Smallest constraint slack (must be ≥ 0)", f"=MIN(I{T1}:J{T2})", "0.00"),
    ("y_ok", "Every y(t) within 0 and κ·h·D(t)?", f'=IF(SUMPRODUCT(--(F{T1}:F{T2}>E{T1}:E{T2}+0.01))+COUNTIF(F{T1}:F{T2},"<0")=0,"Yes","No")', None),
]
for k_, (key, lab, f, fmt) in enumerate(res_rows):
    rr = R0 + 1 + k_
    put(ws, f"A{rr}", lab)
    ws.merge_cells(f"A{rr}:A{rr}")
    put(ws, f"B{rr}", f, kind="formula", fmt=fmt, fill=F_OUT if key in ("avg_opt", "avg_base", "redir") else None)
    LPR[key] = f"{q(LPF)}!$B${rr}"
ws.column_dimensions["A"].width = 52
# sensitivity on Munch's food
SENS = []
for fb in (650, 700, 800, 900, 1000, 1200):  # Munch needs ~600 for its habit share alone
    y_, *_r, obj_, dual_ = solve_flow(D_BINS, DEF["habit"], DEF["comply"], CAP_A, CAP_B, DEF["walk"], fb)
    SENS.append([fb, round(obj_), round(obj_ / sum(D_BINS), 2), round(float(sum(y_))), round(float(dual_), 1)])
S1 = R0 + len(res_rows) + 3
put(ws, f"A{S1}", "Sensitivity: how Munch's star-dish portions limit the plan (LP re-solved for each value)", bold=True)
table(ws, S1 + 1, 1, ["Munch portions F_B", "Student-minutes", "Avg per student (min)", "Redirected", "Shadow price: student-min saved per extra portion"], SENS,
      kinds=["input", "input", "input", "input", "input"], fmts=["#,##0", "#,##0", "0.00", "#,##0", "0.0"])
ws.row_dimensions[S1 + 1].height = 44
note(ws, f"A{S1+8}", f"Reading it: Munch needs about {round((1 - DEF['habit']) * sum(D_BINS) + sum(Y)):,} star-dish portions to carry the optimal flow. Below that, food "
     "becomes the binding constraint and every extra portion saves the student-minutes shown (the shadow price): routing and food allocation must be planned together. "
     "The LP is a fluid model with no randomness, so its optimum is a lower bound on waiting; the simulator adds random arrivals and service, live estimates with a delay, "
     "and run-outs (Scenarios, Reconciliation).", f"F{S1+8}", 58)
put(ws, f"A{S1+10}", "Re-solve in Excel", bold=True)
note(ws, f"A{S1+11}", f"Data → Solver. Set objective B{R0+1} to Min. By changing F{T1}:H{T2}. Constraints: I{T1}:J{T2} ≥ 0; F{T1}:F{T2} ≤ E{T1}:E{T2}; "
     f"N{TR} ≤ {FB}; F{T1}:H{T2} ≥ 0. Method: Simplex LP. If you change any input, re-run Solver: the yellow decision cells hold the optimum for the current Inputs.",
     f"F{S1+11}", 44)
ch = LineChart()
ch.title = "Queue at Central: today vs LP optimum"
ch.y_axis.title = "Students queueing"
ch.add_data(Reference(ws, min_col=11, min_row=T0, max_row=T2), titles_from_data=True)
ch.add_data(Reference(ws, min_col=7, min_row=T0, max_row=T2), titles_from_data=True)
ch.add_data(Reference(ws, min_col=6, min_row=T0, max_row=T2), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=T1, max_row=T2))
ch.height, ch.width = 8, 16
ws.add_chart(ch, f"P{T0}")

# =============================================================================
# LP Food Allocation (SECONDARY: food supports the flow)
# =============================================================================
LPA = "LP Food Allocation"
ws = sheet(LPA, "Linear programming (secondary model): splitting the star dish between the messes to support the student flow",
           "Sessions 10–11: LP formulation, graphical method (corner points), Solver/simplex", [46, 16, 16, 16, 16, 40])
put(ws, "A4", "Formulation", bold=True)
for k_, line in enumerate([
    "Decision variables: x1 = star-dish portions ready at Central before the peak, x2 = portions ready at Munch",
    "Objective: maximise Σ vᵢ·xᵢ, where vᵢ = students per minute who would meet an empty tray at mess i (its peak arrival rate under the flow plan)",
    "Subject to: x1 + x2 ≤ K (portions the kitchen can have ready);  xᵢ ≤ dᵢ (no point sending more than that mess's demand under the flow plan);  x ≥ 0",
]):
    put(ws, f"A{5+k_}", line)
    ws.merge_cells(f"A{5+k_}:F{5+k_}")
put(ws, "A9", "Data (all linked: change Inputs or the flow plan, not these)", bold=True)
peak_A = f"MAX({q(LPF)}!$M${T1}:$M${T2})/10"
peak_B = f"MAX({q(LPF)}!$N${T1}:$N${T2})/10"
fa_rows = [
    ("K: portions the kitchen can have ready before the peak", f"={REF['K_food']}", "#,##0"),
    ("d1: Central demand under the flow plan (students × servings)", f"={q(LPF)}!$M${TR}*{REF['helpings']}", "#,##0"),
    ("d2: Munch demand under the flow plan", f"={q(LPF)}!$N${TR}*{REF['helpings']}", "#,##0"),
    ("v1: students/min at Central's peak under the plan", f"={peak_A}", "0.0"),
    ("v2: students/min at Munch's peak under the plan", f"={peak_B}", "0.0"),
]
for k_, (lab, f, fmt) in enumerate(fa_rows):
    put(ws, f"A{10+k_}", lab)
    put(ws, f"B{10+k_}", f, kind="link", fmt=fmt)
put(ws, "A16", "Decision cells (Solver changes these)", bold=True)
put(ws, "A17", "x1 (Central)")
put(ws, "B17", "=IF(B13>=B14,MIN(B11,B10),MAX(0,MIN(B11,B10-MIN(B12,B10))))", kind="formula", fmt="#,##0", fill=F_KEY)
put(ws, "A18", "x2 (Munch)")
put(ws, "B18", "=IF(B13>=B14,MAX(0,MIN(B12,B10-B17)),MIN(B12,B10))", kind="formula", fmt="#,##0", fill=F_KEY)
note(ws, "C17", "Filled by the greedy rule that solves this LP exactly (fill the mess with the larger v first, then the other). Solver gives the same answer.", "F18", 30)
put(ws, "A19", "Objective Σ v·x (student-minutes of run-out exposure avoided per minute)")
put(ws, "B19", "=B13*B17+B14*B18", kind="formula", fmt="#,##0", fill=F_OUT)
put(ws, "A21", "Constraints", bold=True)
table(ws, 22, 1, ["Constraint", "Left side", "Sign", "Right side", "OK?"], [
    ["Kitchen batch: x1 + x2 ≤ K", "=B17+B18", "≤", "=B10", '=IF(B23<=D23,"OK","Violated")'],
    ["Central demand: x1 ≤ d1", "=B17", "≤", "=B11", '=IF(B24<=D24+0.5,"OK","Violated")'],
    ["Munch demand: x2 ≤ d2", "=B18", "≤", "=B12", '=IF(B25<=D25+0.5,"OK","Violated")'],
    ["Non-negativity", "=MIN(B17:B18)", "≥", "0", '=IF(B26>=0,"OK","Violated")'],
], kinds=["text", "formula", "text", "formula", "formula"], fmts=[None, "#,##0", None, "#,##0", None])
put(ws, "A28", "Graphical method: evaluate every corner point of the feasible region", bold=True)
table(ws, 29, 1, ["Corner point", "x1", "x2", "Feasible?", "Objective"], [
    ["Origin", 0, 0, "", ""],
    ["Central at demand, Munch 0", "=MIN(B11,B10)", 0, "", ""],
    ["Central at demand, rest to Munch", "=MIN(B11,B10)", "=MAX(0,MIN(B12,B10-MIN(B11,B10)))", "", ""],
    ["Munch at demand, rest to Central", "=MAX(0,MIN(B11,B10-MIN(B12,B10)))", "=MIN(B12,B10)", "", ""],
    ["Munch at demand, Central 0", 0, "=MIN(B12,B10)", "", ""],
], kinds=["text", "formula", "formula", "formula", "formula"], fmts=[None, "#,##0", "#,##0", None, "#,##0"])
for rr in range(30, 35):
    ws[f"D{rr}"].value = f'=IF(AND(B{rr}+C{rr}<=$B$10+0.5,B{rr}<=$B$11+0.5,C{rr}<=$B$12+0.5),"Yes","No")'
    ws[f"E{rr}"].value = f"=$B$13*B{rr}+$B$14*C{rr}"
put(ws, "A36", "Optimal corner (graphical method)", bold=True)
put(ws, "B36", '=INDEX(A30:A34,MATCH(MAX(E30:E34),E30:E34,0))', kind="formula", fill=F_OUT, wrap=True)
ws.merge_cells("B36:E36")
note(ws, "A38", "How this connects to the primary model: the flow plan (LP Student Flow) decides where students go; this tab then decides where the limited star dish "
     "should be before the peak. If K covers both demands, the constraint is slack and both messes are fully stocked. If not, the mess whose queue grows faster "
     "gets priority. Refills during service are handled by the Decision Rule (refill clock from the 'running low' call).", "F38", 58)


# =============================================================================
# S7 Payoff Matrix (every cell simulated)
# =============================================================================
PAY = "S7 Payoff Matrix"
ws = sheet(PAY, "Decision making under uncertainty and risk: payoff matrix, with and without the system",
           "Session 7: maximax, maximin, minimax regret, Hurwicz, Laplace, EMV, EVPI · every wait below is simulated, not estimated",
           [46, 15, 15, 15, 15, 15, 15, 15, 15, 15])
alts = PAYOFF["alternatives"]
states = PAYOFF["states"]
cell = {(c["row"], c["col"]): c for c in PAYOFF["cells"]}
short_states = ["S1 Normal day", "S2 Busy day", "S3 Surge + late refills"]
put(ws, "A4", f"Average queue wait per student (minutes). {SIM_SOURCE}. Kinds of day: S1 = 20% fewer students; S2 = 2,960; "
              "S3 = 20% more students and the next batch never ready.", wrap=True)
ws.merge_cells("A4:J4")
ws.row_dimensions[4].height = 44
put(ws, "A6", "Average wait (minutes)  [lower is better]", kind="head")
for j, s_ in enumerate(short_states):
    put(ws, f"{L(2+j)}6", s_, kind="head")
    put(ws, f"{L(6+j)}6", s_ + " (±95% CI)", kind="head")
for i, a_ in enumerate(alts):
    put(ws, f"A{7+i}", a_)
    for j, s_ in enumerate(states):
        w = cell[(a_, s_)]["mean_wait_min"]
        put(ws, f"{L(2+j)}{7+i}", round(w["mean"], 2), kind="input", fmt="0.00",
            comment=f"Simulated: {PAYOFF['runs']} lunches, ±{w['ci95']:.2f} (95% CI)")
        put(ws, f"{L(6+j)}{7+i}", f"±{w['ci95']:.2f}", kind="note")
ws.row_dimensions[6].height = 30
put(ws, "A13", "Probability of each kind of day (Inputs)", kind="head")
for j, key in enumerate(["p_norm", "p_busy", "p_surge"]):
    put(ws, f"{L(2+j)}13", short_states[j], kind="head")
    put(ws, f"{L(2+j)}14", f"={REF[key]}", kind="link", fmt="0%")
put(ws, "A14", "P(kind of day): from the biometric logs once available")
put(ws, "E14", "=SUM(B14:D14)", kind="formula", fmt="0%")
put(ws, "F14", "← must be 100%", kind="note")
put(ws, "A15", "Students per lunch (busy day)")
put(ws, "B15", f"={REF['students']}", kind="link", fmt="#,##0")
put(ws, "A17", "Payoff = minutes saved per student compared with today = wait(A1) − wait(alternative)   [higher is better]", bold=True)
hdr = ["Alternative"] + short_states + ["Maximax (optimistic)", "Maximin (pessimistic)", "Hurwicz", "Laplace (equal likelihood)", "EMV (with probabilities)", "Student-hours saved per lunch (EMV)"]
for j, hh in enumerate(hdr):
    put(ws, f"{L(1+j)}18", hh, kind="head")
ws.row_dimensions[18].height = 44
put(ws, "A27", "Hurwicz α (degree of optimism, analyst's choice)")
put(ws, "B27", 0.4, kind="input", fmt="0.0")
for i, a_ in enumerate(alts):
    r_ = 19 + i
    put(ws, f"A{r_}", a_)
    for j in range(3):
        cl = L(2 + j)
        put(ws, f"{cl}{r_}", f"={cl}$7-{cl}{7+i}", kind="formula", fmt="0.00")
    put(ws, f"E{r_}", f"=MAX(B{r_}:D{r_})", kind="formula", fmt="0.00")
    put(ws, f"F{r_}", f"=MIN(B{r_}:D{r_})", kind="formula", fmt="0.00")
    put(ws, f"G{r_}", f"=$B$27*E{r_}+(1-$B$27)*F{r_}", kind="formula", fmt="0.00")
    put(ws, f"H{r_}", f"=AVERAGE(B{r_}:D{r_})", kind="formula", fmt="0.00")
    put(ws, f"I{r_}", f"=SUMPRODUCT(B{r_}:D{r_},$B$14:$D$14)", kind="formula", fmt="0.00")
    put(ws, f"J{r_}", f"=I{r_}*$B$15/60", kind="formula", fmt="#,##0")
put(ws, "A24", "Best alternative by criterion", bold=True)
put(ws, "A25", "Best without an extra station's staff (A1–A3 only)", bold=True)
for cl in "EFGHI":
    put(ws, f"{cl}24", f"=INDEX($A$19:$A$23,MATCH(MAX({cl}19:{cl}23),{cl}19:{cl}23,0))", kind="formula", fill=F_OUT, wrap=True)
    put(ws, f"{cl}25", f"=INDEX($A$19:$A$21,MATCH(MAX({cl}19:{cl}21),{cl}19:{cl}21,0))", kind="formula", fill=F_OUT, wrap=True)
ws.row_dimensions[24].height = 58
ws.row_dimensions[25].height = 58
put(ws, "A28", "Regret (opportunity loss, minutes) = best payoff on that kind of day − this payoff", bold=True)
for j, hh in enumerate(["Alternative"] + short_states + ["Maximum regret", "Expected regret (EOL)"]):
    put(ws, f"{L(1+j)}29", hh, kind="head")
for i, a_ in enumerate(alts):
    r_ = 30 + i
    put(ws, f"A{r_}", a_)
    for j in range(3):
        cl = L(2 + j)
        put(ws, f"{cl}{r_}", f"=MAX({cl}$19:{cl}$23)-{cl}{19+i}", kind="formula", fmt="0.00")
    put(ws, f"E{r_}", f"=MAX(B{r_}:D{r_})", kind="formula", fmt="0.00")
    put(ws, f"F{r_}", f"=SUMPRODUCT(B{r_}:D{r_},$B$14:$D$14)", kind="formula", fmt="0.00")
put(ws, "A35", "Minimax regret choice", bold=True)
put(ws, "E35", "=INDEX($A$30:$A$34,MATCH(MIN(E30:E34),E30:E34,0))", kind="formula", fill=F_OUT, wrap=True)
put(ws, "A36", "Minimum expected regret (= EMV choice)", bold=True)
put(ws, "F36", "=INDEX($A$30:$A$34,MATCH(MIN(F30:F34),F30:F34,0))", kind="formula", fill=F_OUT, wrap=True)
ws.row_dimensions[35].height = 44
ws.row_dimensions[36].height = 44
put(ws, "A38", "Value of perfect information (minutes per student)", bold=True)
put(ws, "A39", "Expected payoff WITH perfect information (best alternative for each kind of day)")
put(ws, "B39", "=B14*MAX(B19:B23)+C14*MAX(C19:C23)+D14*MAX(D19:D23)", kind="formula", fmt="0.00")
put(ws, "A40", "Best EMV without perfect information")
put(ws, "B40", "=MAX(I19:I23)", kind="formula", fmt="0.00")
put(ws, "A41", "EVPI = extra minutes per student if we knew the kind of day in advance")
put(ws, "B41", "=B39-B40", kind="formula", fmt="0.00", fill=F_OUT)
put(ws, "A42", "Check: EVPI equals the minimum expected regret")
put(ws, "B42", "=MIN(F30:F34)", kind="formula", fmt="0.00")
_alts, _states = PAYOFF["alternatives"], PAYOFF["states"]
_best = {st: min(_alts, key=lambda a: PAYW[(a, st)]) for st in _states}
if len(set(_best.values())) == 1:
    _dom = (f"{next(iter(_best.values()))[:2]} has the lowest wait on every kind of day, so EVPI is 0: "
            "knowing the kind of day in advance would not change the choice. ")
else:
    _dom = ("No alternative has the lowest wait on every kind of day (" + "; ".join(f"{st[:2]}: {a[:2]}" for st, a in _best.items())
            + "), but the differences on the busy day are within the simulation's confidence interval, so EVPI (B41) is small. ")
_a3, _a4 = "A3 Door screens + food status (proposal)", "A4 3rd serving station at Central (no screens)"
_quiet = (f"On normal days a third station alone does a little better ({PAYW[(_a4, _states[0])]:.1f} vs {PAYW[(_a3, _states[0])]:.1f} min). "
          if PAYW[(_a4, _states[0])] < PAYW[(_a3, _states[0])] else "")
note(ws, "A44", "Reading it: the payoff is waiting time only, so the objective stays explicit. " + _dom +
     "Staff cost is not in these minutes: A4 and A5 need a third station's staff every day, "
     "while A3 needs two screens and the manager's taps. Without extra staff, the proposal (A3) is the best choice (row 25). " + _quiet +
     
     "A1 and A4 are without the system; A2, A3 and A5 are with it. For a table of waits (lower is better) the criteria would be minimin and minimax; "
     "turning waits into minutes saved makes higher better, so the maximax / maximin names apply.", "J44", 58)
bc = BarChart()
bc.title = "Expected minutes saved per student (EMV)"
bc.add_data(Reference(ws, min_col=9, min_row=18, max_row=23), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=1, min_row=19, max_row=23))
bc.legend = None
bc.height, bc.width = 7.5, 16
ws.add_chart(bc, "L18")

# =============================================================================
# S18 Heuristics
# =============================================================================
base = {r["scenario"]: r for r in SCEN["results"] if r["group"] == "base"}
B1, B2, B3, BN = (base[k] for k in ["1 Current system", "2 Queue information only", "3 Queue + food (proposal)", "N Naive: go to the shorter queue"])
HE = "S18 Heuristics"
ws = sheet(HE, "Heuristics: simple rules that give good answers fast", "Session 18: Heuristics and metaheuristics — concepts and business applications", [50, 16, 16, 46])
put(ws, "A4", "1. Door-screen switching rule (used in the prototype)", bold=True)
put(ws, "A5", "Predicted wait if you stay (min)")
put(ws, "B5", 6, kind="input", fmt="0.0")
put(ws, "A6", "Predicted wait at the other mess (min)")
put(ws, "B6", 2, kind="input", fmt="0.0")
put(ws, "A7", "Walk between doors (min)")
put(ws, "B7", f"={REF['walk']}", kind="link", fmt="0.0")
put(ws, "A8", "Minimum saving to suggest a switch (min)")
put(ws, "B8", f"={REF['min_save']}", kind="link", fmt="0.0")
put(ws, "A9", "Saving after the walk (min)")
put(ws, "B9", "=B5-(B6+B7)", kind="formula", fmt="0.0")
put(ws, "A10", "Screen says")
put(ws, "B10", '=IF(B9>=B8,"Other mess is faster → walk over",IF(B9>0,"Small saving: stay","Come on in"))', kind="formula", fill=F_OUT)
ws.merge_cells("B10:D10")
put(ws, "A12", "2. When should the manager tap 'running low' (call the kitchen)? A reorder point", bold=True)
put(ws, "A13", "Star dish served per minute at peak (= Central's serving capacity)")
put(ws, "B13", f"={REF['cap_A']}", kind="link", fmt="0.0")
put(ws, "A14", "Lead time from the call (worst case: has to be made, then sent)")
put(ws, "B14", f"={REF['lead_call']}", kind="link", fmt="0")
put(ws, "A15", "Lead time from the call (expected: 70% already made)")
put(ws, "B15", f"={REF['refill']}", kind="link", fmt="0.0")
put(ws, "A16", "Reorder point, worst case (portions left when the call must go)")
put(ws, "B16", "=B13*B14", kind="formula", fmt="0", fill=F_OUT)
put(ws, "A17", "Reorder point, expected case")
put(ws, "B17", "=B13*B15", kind="formula", fmt="0", fill=F_OUT)
put(ws, "A18", "Our protocol: tap 'running low' with this many minutes of food left")
put(ws, "B18", f"={REF['low_left']}", kind="link", fmt="0")
put(ws, "A19", "Portions left at the tap (at peak)")
put(ws, "B19", "=B13*B18", kind="formula", fmt="0")
note(ws, "C16", "The protocol (20 min of food) covers the expected refill but not the worst case (30 min): in that case a gap opens, and the Decision Rule "
     "charges it only to students who would reach the empty tray.", "D19", 40)
put(ws, "A21", "3. Heuristic vs full model (busy day, 60% follow the screens)", bold=True)
table(ws, 22, 1, ["Policy", "Average wait (min)", "90th pct wait (min)", "Comment"], [
    ["No advice (today)", round(B1["mean_wait_min"]["mean"], 2), round(B1["p90_wait_min"]["mean"], 1), "Baseline (simulated)"],
    ["Naive heuristic: send people to the shorter queue (≥ 2 min saving)", round(BN["mean_wait_min"]["mean"], 2), round(BN["p90_wait_min"]["mean"], 1), "Simple rule; works at the doors because feedback is fast (30 s walk)"],
    ["Equal-wait split, queues only", round(B2["mean_wait_min"]["mean"], 2), round(B2["p90_wait_min"]["mean"], 1), "Ignores food status"],
    ["Equal-wait split + food status (proposal)", round(B3["mean_wait_min"]["mean"], 2), round(B3["p90_wait_min"]["mean"], 1), "Bisection search for the split; food delays only for students who would meet an empty tray"],
    ["LP lower bound (fluid model, perfect foresight)", f"={LPR['avg_opt']}", "", "Not achievable live: no randomness, no estimation delay"],
], kinds=["text", "input", "input", "text"], fmts=[None, "0.00", "0.0", None], wrap_cols=(0, 3))
for rr in range(23, 28):
    ws.row_dimensions[rr].height = 30
put(ws, "A29", "4. Metaheuristics (next step)", bold=True)
note(ws, "A30", "A replenishment schedule that minimises waiting + waste over a whole lunch has no closed-form answer because of the queues. A metaheuristic "
     "(simulated annealing or a genetic algorithm) can search over schedules, scoring each candidate by running our simulator: 'simulation-optimisation'.", "D30", 44)

# =============================================================================
# Decision Rule: when to recommend Central, Munch, or neither
# =============================================================================
DR = "Decision Rule"
ws = sheet(DR, "Decision rule: when the screen outside Central recommends Munch, and when it gives no advice",
           "The objective stays explicit: minimise each student's expected time to food (queue + walk + any food delay), without overloading the other mess",
           [36, 10, 10, 10, 10, 10, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11, 12, 12, 40])
put(ws, "A4", "The rule (the same logic the prototype runs; config/default.toml)", bold=True)
for k_, line in enumerate([
    "1. No advice if the data are stale: a scanner silent for longer than the limit on the Inputs tab.",
    "2. No advice if the star dish is out at both messes (no better option).",
    "3. Time if you stay = queue wait here + food delay here. Time if you switch = walk + queue wait there + food delay there.",
    "4. Food delay for a tray marked 'running low' or 'out': only if you would reach the counter after it empties and before its refill (refill clock runs from the call).",
    "5. Recommend switching only if it saves at least the minimum saving + an uncertainty margin, AND the other mess still has spare capacity after the move.",
    "6. Never send everyone: move only enough students to equalise utilisation (capacity-weighted), so the other mess doesn't become the new bottleneck.",
]):
    put(ws, f"A{5+k_}", line)
    ws.merge_cells(f"A{5+k_}:T{5+k_}")
p, lo, hi, T_, LEFT = REF["ready_p"], REF["send_lo"], REF["send_hi"], REF["lead_call"], REF["low_left"]
H0 = 13
heads = ["Situation", "Wait at Central (min)", "Wait at Munch (min)", "Central star dish", "Min since Central called kitchen",
         "Munch star dish", "Min since Munch called kitchen", "Arrivals Central (/min)", "Arrivals Munch (/min)", "Min since last scan",
         "Central refill due in (min)", "Central food delay (min)", "Munch refill due in (min)", "Munch food delay (min)",
         "Time if you stay", "Time if you switch", "Saving (min)", "Move /min to equalise", "Munch ρ after the move", "Screen outside Central says"]
for j, hh in enumerate(heads):
    put(ws, f"{L(1+j)}{H0}", hh, kind="head")
ws.row_dimensions[H0].height = 58
cases = [
    ("Quiet start of lunch", 0.2, 0.1, "OK", 0, "OK", 0, 5, 1, 0.2),
    ("Peak: Central queue, Munch quiet", 9, 1, "OK", 0, "OK", 0, 29, 5, 0.2),
    ("Peak, but Munch is nearly full too", 9, 6, "OK", 0, "OK", 0, 29, 19, 0.2),
    ("Central star dish OUT, kitchen just called", 3, 1, "OUT", 0, "OK", 0, 25, 6, 0.2),
    ("Central star dish OUT, called 16 min ago (late batch)", 3, 1, "OUT", 16, "OK", 0, 25, 6, 0.2),
    ("Central running low, called 2 min ago", 2, 1, "LOW", 2, "OK", 0, 25, 6, 0.2),
    ("Central running low, called 18 min ago, 4-min queue", 4, 1, "LOW", 18, "OK", 0, 25, 6, 0.2),
    ("Central scanner silent for 5 minutes", 9, 1, "OK", 0, "OK", 0, 29, 5, 5),
    ("Star dish out at both messes", 3, 3, "OUT", 5, "OUT", 5, 20, 10, 0.2),
]


def remaining(e):
    """Expected refill minutes still to come, e minutes after the call (no refill seen yet)."""
    pr = f"{p}*IF({e}<={lo},1,MAX(0,({hi}-{e})/({hi}-{lo})))"
    pc = f"(1-{p})*IF({e}<{T_},1,0)"
    rr_ = f"IF({e}<{hi},(MAX({e},{lo})+{hi})/2-{e},0)"
    rc = f"({T_}-{e})"
    return f"IF(({pr})+({pc})=0,0,(({pr})*({rr_})+({pc})*{rc})/(({pr})+({pc})))"


def delay(status, e, t, rem):
    return (f'IF({status}="OUT",MAX(0,{rem}-{t}),IF({status}="LOW",IF(AND({t}>=MAX(0,{LEFT}-{e}),{t}<{rem}),{rem}-{t},0),0))')


for i, cs in enumerate(cases):
    r_ = H0 + 1 + i
    for j, v in enumerate(cs):
        put(ws, f"{L(1+j)}{r_}", v, kind="input" if j else "text", fmt="0.0" if isinstance(v, (int, float)) else None)
    put(ws, f"K{r_}", f'=IF(D{r_}="OK","",{remaining(f"E{r_}")})', kind="formula", fmt="0.0")
    put(ws, f"L{r_}", f"={delay(f'D{r_}', f'E{r_}', f'B{r_}', f'K{r_}')}", kind="formula", fmt="0.0")
    put(ws, f"M{r_}", f'=IF(F{r_}="OK","",{remaining(f"G{r_}")})', kind="formula", fmt="0.0")
    put(ws, f"N{r_}", f"={delay(f'F{r_}', f'G{r_}', f'({REF['walk']}+C{r_})', f'M{r_}')}", kind="formula", fmt="0.0")
    put(ws, f"O{r_}", f"=B{r_}+L{r_}", kind="formula", fmt="0.0")
    put(ws, f"P{r_}", f"={REF['walk']}+C{r_}+N{r_}", kind="formula", fmt="0.0")
    put(ws, f"Q{r_}", f"=O{r_}-P{r_}", kind="formula", fmt="0.0")
    put(ws, f"R{r_}", f"=MAX(0,(H{r_}*{REF['cap_B']}-I{r_}*{REF['cap_A']})/({REF['cap_A']}+{REF['cap_B']}))", kind="formula", fmt="0.0")
    put(ws, f"S{r_}", f"=(I{r_}+MIN(R{r_},{REF['comply']}*H{r_}))/{REF['cap_B']}", kind="formula", fmt="0%")
    put(ws, f"T{r_}", (f'=IF(J{r_}>{REF["stale"]},"No advice: scan data stale",'
                       f'IF(AND(D{r_}="OUT",F{r_}="OUT"),"No advice: star dish out at both messes",'
                       f'IF(Q{r_}<{REF["min_save"]}+{REF["margin"]},"Come on in (saving under "&TEXT({REF["min_save"]}+{REF["margin"]},"0.0")&" min)",'
                       f'IF(S{r_}>=1,"Come on in: Munch has no spare capacity",'
                       f'"Munch is faster → save ~"&TEXT(Q{r_},"0")&" min"))))'), kind="formula", fill=F_OUT, wrap=True)
    ws.row_dimensions[r_].height = 30
DR_LAST = H0 + len(cases)
note(ws, f"A{DR_LAST+2}", "Blue cells are example situations: change them to test the rule. 'Refill due in' is the expected time still to wait given the minutes since the "
     "call and no refill yet: if 15 minutes have passed, the 10–14 minute 'already made' case is ruled out, so only the 30-minute case remains. 'Move /min to "
     "equalise' is how many students per minute would make both messes equally busy; the screen asks only that share (never everyone). The simulator applies "
     "the same rule through an equal-wait split (bisection), which also accounts for the walk and the queues the moved students create.", f"T{DR_LAST+2}", 58)


# =============================================================================
# Scenarios: the four scenarios and the stress tests (simulated)
# =============================================================================
SC = "Scenarios"
ws = sheet(SC, "Baseline vs intervention: four scenarios and stress tests (simulated, same students in every scenario)",
           SIM_SOURCE, [44, 14, 14, 14, 14, 14, 14, 12, 12, 12, 12, 12, 12, 13, 13])
def mv(r, k, fmt="{:.2f}"):
    v = r[k]["mean"]
    return None if v is None else round(v, 4)
put(ws, "A4", "1. The four scenarios on a busy day (2,960 students, 60% follow the screens)", bold=True)
cols = [("Avg queue wait (min)", "mean_wait_min", "0.00"), ("±95% CI", "mean_wait_min", "ci"), ("90th pct wait (min)", "p90_wait_min", "0.0"),
        ("Avg throughput, door to leaving (min)", "mean_throughput_min", "0.0"), ("90th pct throughput (min)", "p90_throughput_min", "0.0"),
        ("Total incl. walk, decision to leaving (min)", "mean_total_min", "0.0"), ("Central stations busy", "util_A", "0%"), ("Munch stations busy", "util_B", "0%"),
        ("Central peak load (30 min)", "peak_load_A", "0%"), ("Munch peak load (30 min)", "peak_load_B", "0%"), ("Run-outs per lunch", "outages", "0.0"),
        ("Redirected students", "redirected", "0"), ("Followed the advice", "compliance_rate", "0%"), ("Unsuccessful redirects", "unsuccessful_rate", "0%")]
for j, (hh, _k, _f) in enumerate(cols):
    put(ws, f"{L(2+j)}5", hh, kind="head")
put(ws, "A5", "Scenario", kind="head")
ws.row_dimensions[5].height = 58
order = ["1 Current system", "2 Queue information only", "3 Queue + food (proposal)", "N Naive: go to the shorter queue"]
for i, name in enumerate(order):
    r_ = 6 + i
    res = base[name]
    put(ws, f"A{r_}", name, bold=name.startswith("3"))
    for j, (hh, k, f) in enumerate(cols):
        if f == "ci":
            put(ws, f"{L(2+j)}{r_}", f"±{res[k]['ci95']:.2f}", kind="note")
            continue
        v = mv(res, k)
        put(ws, f"{L(2+j)}{r_}", "–" if v is None else v, kind="input", fmt=f)
put(ws, "A11", "Change vs today (proposal)", bold=True)
put(ws, "B11", "=B8-B6", kind="formula", fmt="+0.00;-0.00")
put(ws, "C11", "=1-B8/B6", kind="formula", fmt="0% \"shorter\"")
put(ws, "D11", "=D8-D6", kind="formula", fmt="+0.0;-0.0")
put(ws, "E11", "=E8-E6", kind="formula", fmt="+0.0;-0.0")
note(ws, "A12", "Definitions. Queue wait = minutes queueing for the scanner, a serving station and a seat (eating, the food line and disposal are activity time, not waiting). "
     "Throughput = door to leaving, all four stages. 90th percentile = the wait that 1 in 10 students exceed, per lunch, then averaged. Stations busy = share of "
     "11:30–14:30 the serving stations were in use; peak load = arrivals ÷ capacity in the busiest 30 minutes (above 100% the queue grows). Unsuccessful redirect = "
     "a redirected student whose wait + walk exceeded the average wait of students who stayed at the mess they left and arrived within 2 minutes. "
     "Scenario 2 = the screens use queues but never hear about food; N = a naive 'go to the shorter queue' rule, shown for the herding point.", "O12", 72)
bc = BarChart()
bc.title = "Average queue wait by scenario (busy day)"
bc.add_data(Reference(ws, min_col=2, min_row=5, max_row=9), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=1, min_row=6, max_row=9))
bc.legend = None
bc.height, bc.width = 7, 14
ws.add_chart(bc, "Q4")
put(ws, "A15", "2. Stress tests: does the benefit persist? One input changed at a time", bold=True)
st_h = ["Stress test", "1 Current: wait", "2 Queue only: wait", "3 Proposal: wait", "3 Proposal: ±95% CI", "1 Current: p90", "3 Proposal: p90",
        "Reduction (3 vs 1)", "3 beats 2?", "Run-outs: 1", "Run-outs: 3", "Unsuccessful: 2", "Unsuccessful: 3"]
for j, hh in enumerate(st_h):
    put(ws, f"{L(1+j)}16", hh, kind="head")
ws.row_dimensions[16].height = 44
groups_ = [g for g in dict.fromkeys(r["group"] for r in SCEN["results"]) if g != "base"]
by = {(r["group"], r["scenario"]): r for r in SCEN["results"]}
STR_FIRST = 17
for i, g in enumerate(groups_):
    r_ = STR_FIRST + i
    s1, s2, s3 = by[(g, "1 Current system")], by[(g, "2 Queue information only")], by[(g, "3 Queue + food (proposal)")]
    vals = [g, mv(s1, "mean_wait_min"), mv(s2, "mean_wait_min"), mv(s3, "mean_wait_min"), f"±{s3['mean_wait_min']['ci95']:.2f}",
            mv(s1, "p90_wait_min"), mv(s3, "p90_wait_min")]
    for j, v in enumerate(vals):
        put(ws, f"{L(1+j)}{r_}", v, kind="note" if j == 4 else ("input" if j else "text"), fmt="0.00" if j in (1, 2, 3) else "0.0")
    put(ws, f"H{r_}", f"=1-D{r_}/B{r_}", kind="formula", fmt="0%")
    ci2, ci3 = s2["mean_wait_min"]["ci95"], s3["mean_wait_min"]["ci95"]
    put(ws, f"I{r_}", f'=IF(D{r_}+{ci3}<C{r_}-{ci2},"Yes",IF(D{r_}<C{r_},"Tie (within noise)","No"))', kind="formula")
    for j, (s_, k) in enumerate([(s1, "outages"), (s3, "outages"), (s2, "unsuccessful_rate"), (s3, "unsuccessful_rate")]):
        v = mv(s_, k)
        put(ws, f"{L(10+j)}{r_}", "–" if v is None else v, kind="input", fmt="0.0" if k == "outages" else "0%")
STR_LAST = STR_FIRST + len(groups_) - 1
put(ws, f"A{STR_LAST+1}", "Smallest reduction across all stress tests", bold=True)
put(ws, f"H{STR_LAST+1}", f"=MIN(H{STR_FIRST}:H{STR_LAST})", kind="formula", fmt="0%", fill=F_OUT)
note(ws, f"A{STR_LAST+3}", "Reading it: the proposal cuts the average wait in every stress test and beats or ties 'queue information only' in every one. With no stock-outs the "
     "food signal adds nothing (2 and 3 converge); with more stock-outs it matters most. The timetable matters as much as any operational input: "
     "the stagger rows show what moving one department's lunch by 15 minutes does with no screens at all. One limitation: everything here rests on the assumed 10 students/min per station, the rough department sizes and the "
     "calibrated arrival lag until the biometric logs and a stopwatch replace them (Data Collection).", f"M{STR_LAST+3}", 58)

# =============================================================================
# Reconciliation: spreadsheet vs simulator
# =============================================================================
RC = "Reconciliation"
ws = sheet(RC, "Why the spreadsheet (S15) and the simulator give different numbers",
           "Start the simulator with the spreadsheet's simplifications, then add one real-world feature at a time. Same students in every row.",
           [60, 15, 15, 15, 15, 46])
rc = {(c["row"], c["col"]): c for c in RECON["cells"]}
table(ws, 4, 1, ["Model", "Without screens: avg wait", "With screens: avg wait", "Without: 90th pct", "With: 90th pct", "What changes"], [])
put(ws, "A5", "S15 spreadsheet (analytic: M/M/c + fluid queue per 10-min slot)")
put(ws, "B5", f"={QS_AVG_WITHOUT}", kind="link", fmt="0.00")
put(ws, "C5", f"={QS_AVG_WITH}", kind="link", fmt="0.00")
put(ws, "F5", "Deterministic slots; 'with screens' moves the complying share toward equal utilisation with perfect knowledge, every slot", wrap=True)
why = [
    "Same assumptions as S15 except that arrivals and service are random and routing uses live estimates (with a delay and the 2-min rule). "
    "Without screens it matches S15; with screens it is worse than S15's perfect routing",
    "Real serving is more regular than exponential: slightly shorter queues",
    "A single 2 s scanner rarely limits flow: almost no change",
    "Seats rarely fill (eating 14–18 min): no change",
    "Run-outs stop service until the refill: today's waits rise; the screens absorb most of it",
]
for i, step in enumerate(RECON["steps"]):
    r_ = 6 + i
    a, b = rc[(step, "Without screens")], rc[(step, "With screens")]
    put(ws, f"A{r_}", "Simulator " + step)
    put(ws, f"B{r_}", round(a["mean_wait_min"]["mean"], 2), kind="input", fmt="0.00")
    put(ws, f"C{r_}", round(b["mean_wait_min"]["mean"], 2), kind="input", fmt="0.00")
    put(ws, f"D{r_}", round(a["p90_wait_min"]["mean"], 1), kind="input", fmt="0.0")
    put(ws, f"E{r_}", round(b["p90_wait_min"]["mean"], 1), kind="input", fmt="0.0")
    put(ws, f"F{r_}", why[i], wrap=True)
    ws.row_dimensions[r_].height = 44 if i == 0 else 30
put(ws, f"A{6+len(RECON['steps'])}", "LP Student Flow: fluid optimum (perfect foresight, no randomness)")
put(ws, f"C{6+len(RECON['steps'])}", f"={LPR['avg_opt']}", kind="link", fmt="0.00")
put(ws, f"B{6+len(RECON['steps'])}", f"={LPR['avg_base']}", kind="link", fmt="0.00")
put(ws, f"F{6+len(RECON['steps'])}", "A lower bound: the best any routing could do in a smooth-flow world", wrap=True)
RC_GAP = 7 + len(RECON["steps"])
put(ws, f"A{RC_GAP}", "Gap without screens: spreadsheet vs spreadsheet-like simulator (should be small)")
put(ws, f"B{RC_GAP}", "=B6-B5", kind="formula", fmt="+0.00;-0.00", fill=F_OUT)
put(ws, f"A{RC_GAP+1}", "Gap as a share of the simulator's figure (the check allows 15%)")
put(ws, f"B{RC_GAP+1}", f"=B{RC_GAP}/B6", kind="formula", fmt="+0%;-0%", fill=F_OUT)
note(ws, f"A{RC_GAP+2}", "Conclusion: the two models agree when they make the same assumptions (first two rows, without screens), within 15%. The spreadsheet "
     "is a little higher because it adds the steady-state M/M/c wait in every 10-minute slot; near 100% busy a slot is too short for the queue to reach "
     "steady state, and the department surge passes through several such slots. The headline numbers come from the full "
     f"simulator (last simulator row) because it includes the things the spreadsheet cannot: randomness, live estimation, the scanner, seats and run-outs. "
     "The spreadsheet's 'with screens' figure is optimistic because it routes with perfect knowledge; the LP is the theoretical best case. "
     f"{RECON['runs']} lunches per simulator row.", f"F{RC_GAP+2}", 58)

# =============================================================================
# Simulation Method
# =============================================================================
SM = "Simulation Method"
ws = sheet(SM, "How the simulator works (messq/simulation.py, messq/engine.py)", "Reproduce every number: python -m messq.scenarios [--payoff | --reconcile] --runs 20",
           [26, 64, 40, 22])
table(ws, 4, 1, ["Component", "How it is modelled", "Parameters (Inputs / config)", "Status"], [
    ["Time", "Discrete steps of 5 seconds (the scanner poll interval), 11:30–14:30; the run continues until everyone has food", "step_s = 5", "Design"],
    ["Arrivals", "Random (Poisson) arrivals; the rate is the department lunch breaks added up (Arrival Curve tab): each department starts arriving when its break starts, "
     "lag Normal(20, 20) min cut off at the end of the break; total = students per lunch", "students, department breaks, lag_m, lag_sd", "Total and timetable measured; sizes rough; lag calibrated"],
    ["Where students head", "Each student heads to Central with probability h (habit), else Munch", "habit share h", "Assumed"],
    ["Advice at the door", "The screen at the mess they reach asks a share of students to walk to the other mess (none in scenario 1)", "Decision Rule; min saving 2 min", "Policy"],
    ["Compliance", "Each advised student follows with probability κ; followers walk 30 s to the other door", "comply κ, walk", "Assumed"],
    ["Stage 1: entrance", "FCFS queue for the face scanner (2 s each, cv 0.3), then collecting a plate (uniform 28–43 s; 30–45 s with the scan). The scan time is what the biometric log records", "scan_s, plate_lo/hi", "Assumed"],
    ["Stage 2: food", "FCFS queue for 2 serving stations; service time gamma with mean 6 s and cv 0.6 (M/G/c); then the rest of food collection (uniform 54–114 s; 1–2 min in all)", "mu, line_lo/hi, service_cv", "Stations measured; times assumed"],
    ["Food stock", "Star dish in batches (Central 900, Munch 500). At the call level the mess calls the kitchen; refill arrives in 10–14 min (70%) or 30 min. At zero stock nobody is served until the refill", "food_batch, refill trigger, ready_p, lead times", "Lead times measured; batches assumed"],
    ["Manager taps", "'Running low' at the call, 'out' at zero, 'refilled' on arrival; each tap made 90% of the time (forgotten taps expire)", "staff_signal_prob 0.9", "Assumed"],
    ["Stage 3: eating", "Take a seat if free (900 / 492), else wait; eat for uniform 14–18 min", "seats, eat_lo/hi", "Seats measured; eating group estimate"],
    ["Stage 4: disposal", "Dispose of plate and leftovers, uniform 1–2 min (the seat is already free)", "disp_lo/hi", "Group estimate"],
    ["What the system sees", "Only scans and the manager's taps. Arrival rate from the last 5 min of scans; queue by a fluid model; wait by M/M/c + fluid growth + food delay", "rate window 5 min, horizon 5 min", "Design"],
    ["Routing", "Equal-wait (Wardrop) split found by bisection; at each door ask (h − p)/(h·κ) of students to switch, only if it saves ≥ 2 min after the walk", "min_save", "Design"],
    ["Food in the advice", "Star dish out = outage; other trays and 'running low' add delay only for students who would reach an empty tray; refill clock from the call", "tray weights, low_left", "Design (weights: group judgement)"],
    ["Measures", "Per student: queue wait (scanner + station + seat), throughput (door to leaving), total incl. walk. Per lunch: mean and 90th percentile", "—", "Design"],
    ["Runs", "20 lunches per scenario, seeds 0–19; the same seeds in every scenario (paired comparison). ± = 1.96 × sd ÷ √20 across lunches", "--runs", "Design"],
], wrap_cols=(1, 2, 3))
for rr in range(5, 21):
    ws.row_dimensions[rr].height = 44
note(ws, "A22", "Validation so far: the simulated normal visit and peak throughput fall in the group's 17–35 min range (Checks), the no-screen 90th percentile wait is "
     "close to the ~15 min observed, and the spreadsheet-like simulator reproduces S15 without screens (Reconciliation). Not yet validated: the arrival curve, "
     "the habit split and the service rate (Data Collection).", "D22", 44)

# =============================================================================
# Data Collection (Stage 2): template + automatic diagnosis
# =============================================================================
DC = "Data Collection"
ws = sheet(DC, "Stage 2: collect the minimum data to prove (or disprove) the bottleneck",
           "Fill the blue grid from logs or a manual pilot at BOTH messes over the same lunch. The diagnosis below updates itself.",
           [22, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13])
table(ws, 4, 1, ["Data", "How to capture it", "Why it matters", "Who / when"], [
    ["Arrivals per 10 min", "Biometric logs (aggregated), or a tally counter at each door", "Demand distribution and the habit split", "IT logs / 2 volunteers per mess"],
    ["Queue length", "Count people queueing at the stations every 10 min", "Validates congestion", "1 volunteer per mess"],
    ["Sampled waiting time", "Note time joining the queue and reaching the station for ~20 students per hour", "Measures actual delay", "1 volunteer per mess"],
    ["Service rate", "Count plates completed per station per minute while there is a queue", "Usable capacity (μ)", "Stopwatch, 3 × 5 min at peak"],
    ["Food availability", "Time-stamped 'running low' / 'out' / 'refilled' taps (or notes)", "Tests whether food drives routing", "Mess manager"],
    ["Replenishment time", "Time of the call and time the refill arrives", "Lead time (30 vs 10–14 min)", "Mess manager"],
    ["Destination preference", "Short neutral survey at the door: 'why this mess today?'", "Tests the bias hypotheses (S4)", "Survey, 50+ students"],
], wrap_cols=(1, 2, 3))
for rr in range(5, 12):
    ws.row_dimensions[rr].height = 30
note(ws, "A12", "Measure arrivals and service capacity separately: a mess can be quiet because demand is low, because it cannot serve faster, or because its food is "
     "less attractive. Each points to a different intervention. If live logs are not available, run a structured manual pilot and label its limits.", "D12", 40)
G0 = 15
gh = ["Slot", "Central: arrivals", "Central: served", "Central: queue at slot start", "Central: sampled avg wait (min)",
      "Munch: arrivals", "Munch: served", "Munch: queue at slot start", "Munch: sampled avg wait (min)",
      "Central share of arrivals", "Central ρ (assumed μ)", "Munch ρ (assumed μ)"]
for j, hh in enumerate(gh):
    put(ws, f"{L(1+j)}{G0}", hh, kind="head")
ws.row_dimensions[G0].height = 58
put(ws, f"A{G0+1}", "Example (not counted)", kind="note")
for j, v in enumerate([240, 200, 35, 6.5, 40, 40, 0, 0.3]):
    put(ws, f"{L(2+j)}{G0+1}", v, kind="note")
DFR = G0 + 2
for i in range(N_BINS):
    r_ = DFR + i
    m = 11 * 60 + 30 + i * 10
    put(ws, f"A{r_}", f"{m // 60:02d}:{m % 60:02d}")
    for j in range(8):
        c = put(ws, f"{L(2+j)}{r_}", None, kind="input", fmt="0.0" if j in (3, 7) else "0")
        c.fill = F_KEY
    put(ws, f"J{r_}", f'=IF(COUNT(B{r_},F{r_})<2,"",B{r_}/MAX(1,B{r_}+F{r_}))', kind="formula", fmt="0%")
    put(ws, f"K{r_}", f'=IF(COUNT(B{r_})=0,"",B{r_}/10/{REF["cap_A"]})', kind="formula", fmt="0%")
    put(ws, f"L{r_}", f'=IF(COUNT(F{r_})=0,"",F{r_}/10/{REF["cap_B"]})', kind="formula", fmt="0%")
DLR = DFR + N_BINS - 1
D0 = DLR + 2
put(ws, f"A{D0}", "Automatic diagnosis (blank until data are entered)", bold=True)
diag = [
    ("Slots with data", f"=COUNT(B{DFR}:B{DLR})", "0"),
    ("Central share of all arrivals (measured habit split)", f'=IF(B{D0+1}=0,"",SUM(B{DFR}:B{DLR})/MAX(1,SUM(B{DFR}:B{DLR})+SUM(F{DFR}:F{DLR})))', "0%"),
    ("Central's share of the seats (900 ÷ 1,400) for comparison", f"={REF['seats_A']}/({REF['seats_A']}+{REF['seats_B']})", "0%"),
    ("Peak Central ρ (busiest slot)", f'=IF(B{D0+1}=0,"",MAX(K{DFR}:K{DLR}))', "0%"),
    ("Peak Munch ρ in the same lunch", f'=IF(B{D0+1}=0,"",MAX(L{DFR}:L{DLR}))', "0%"),
    ("Measured service rate at Central (served ÷ stations ÷ 10, busiest slot with a queue)",
     f'=IF(B{D0+1}=0,"",SUMPRODUCT(MAX((D{DFR}:D{DLR}>0)*C{DFR}:C{DLR}))/{REF["c_A"]}/10)', "0.0"),
    ("Is Central disproportionately busy?", f'=IF(B{D0+1}=0,"",IF(AND(B{D0+2}>B{D0+3},B{D0+4}>={REF["rho_max"]}),"Yes: more than its seat share and above target utilisation","No: revise the diagnosis"))', None),
    ("Does Munch have usable spare capacity at Central's peak?", f'=IF(B{D0+1}=0,"",IF(B{D0+5}<0.7,"Yes: below 70% busy","No: redistribution would just move the queue"))', None),
]
for k_, (lab, f, fmt) in enumerate(diag):
    rr = D0 + 1 + k_
    put(ws, f"A{rr}", lab)
    ws.merge_cells(f"A{rr}:F{rr}")
    put(ws, f"G{rr}", f, kind="formula", fmt=fmt, fill=F_OUT if k_ >= 6 else None)
    ws.merge_cells(f"G{rr}:L{rr}")
note(ws, f"A{D0+len(diag)+2}", "If the answers are 'No', don't force the original hypothesis: update the Inputs (habit split, service rate) and let the scenarios show what "
     "the evidence implies. Changing course on evidence is a strength in an MDS project.", f"L{D0+len(diag)+2}", 30)

# =============================================================================
# Checks
# =============================================================================
CK = "Checks"
ws = sheet(CK, "Validation checks: every one should say OK", "Recalculate (F9) after changing inputs; a CHECK means something needs a look",
           [64, 18, 12, 50])
table(ws, 4, 1, ["Check", "Value", "Result", "What it tests"], [])
inputs_rng = f"{q(INP)}!$B${INPUT_FIRST}:$B${INPUT_LAST}"
n_numeric = sum(1 for row in ROWS if row[0] != "sec" and not isinstance(row[2], str))
s15_rng = f"{q(QS)}!$A${QS_FR}:$AN${QS_LR}"
sim_quiet = round(base["1 Current system"]["quiet_throughput_min"]["mean"], 1)
sim_peak = round(base["1 Current system"]["peak_throughput_min"]["mean"], 1)
checks = [
    ("Every numeric input is a number (no text such as '14-15')", f"=COUNT({inputs_rng})", f"=IF(B5={n_numeric},\"OK\",\"CHECK\")", f"{n_numeric} numeric inputs expected"),
    ("No formula errors in S15 Queuing", f"=SUMPRODUCT(--ISERROR({s15_rng}))", "=IF(B6=0,\"OK\",\"CHECK\")", "The earlier errors came from a text input ('14-15')"),
    ("No formula errors in LP Student Flow", f"=SUMPRODUCT(--ISERROR({q(LPF)}!$A$19:$N$40))", "=IF(B7=0,\"OK\",\"CHECK\")", ""),
    ("No formula errors in Decision Rule", f"=SUMPRODUCT(--ISERROR({q(DR)}!$A$14:$T${DR_LAST}))", "=IF(B8=0,\"OK\",\"CHECK\")", ""),
    ("Arrival curve shares sum to 100%", f"=SUM({QS_SHARE})", "=IF(ABS(B9-1)<0.0001,\"OK\",\"CHECK\")", "Demand balance"),
    ("S15 arrivals add up to students per lunch", f"=SUM({QS_ARR})-{REF['students']}", "=IF(ABS(B10)<0.5,\"OK\",\"CHECK\")", "Demand balance"),
    ("Habit share and compliance are between 0 and 1", f"=AND({REF['habit']}>=0,{REF['habit']}<=1,{REF['comply']}>=0,{REF['comply']}<=1)", "=IF(B11,\"OK\",\"CHECK\")", ""),
    ("Kinds of day sum to 100%", f"={REF['p_norm']}+{REF['p_busy']}+{REF['p_surge']}", "=IF(ABS(B12-1)<0.0001,\"OK\",\"CHECK\")", "Payoff matrix probabilities"),
    ("LP: every constraint holds (smallest slack ≥ 0)", f"={LPR['min_slack']}", "=IF(B13>=-0.01,\"OK\",\"CHECK (re-run Solver)\")", "Fluid queue recursions"),
    ("LP: redirects within compliance limits", f"={LPR['y_ok']}", "=IF(B14=\"Yes\",\"OK\",\"CHECK (re-run Solver)\")", "0 ≤ y ≤ κ·h·D"),
    ("LP: Munch's food constraint holds", f"={LPR['food_ok']}", "=IF(B15=\"Yes\",\"OK\",\"CHECK (re-run Solver)\")", "Food as the operational constraint"),
    ("LP improves on today", f"={LPR['avg_opt']}-{LPR['avg_base']}", "=IF(B16<0,\"OK\",\"CHECK\")", ""),
    ("Response: a faster serving rate lowers the M/M/c wait (λ = 17/min, c = 2)", "=_wq(17,1.1*%MU%)-_wq(17,%MU%)", "=IF(B17<0,\"OK\",\"CHECK\")", "Outputs move in the right direction"),
    ("With screens, Munch's peak utilisation stays below 100% (S15)", f"={QS_PEAKRHO_WB}", "=IF(B18<1,\"OK\",\"CHECK\")", "Redistribution must not overload Munch"),
    ("Throughput with no queues is within the measured range", f"={REF['thr0']}", f"=IF(AND(B19>={REF['thr_lo']}-1,B19<={REF['thr_hi']}),\"OK\",\"CHECK\")", "17–35 min (group); quiet visit ~18"),
    ("Simulated throughput for students who met no queue (today)", sim_quiet, f"=IF(AND(B20>={REF['thr_lo']}-1,B20<={REF['thr_hi']}),\"OK\",\"CHECK\")", "Simulator calibration"),
    ("Simulated throughput at the peak (today)", sim_peak, f"=IF(AND(B21>={REF['thr_lo']},B21<={REF['thr_hi']}+3),\"OK\",\"CHECK\")", "Group: up to ~25 min in a surge"),
    ("Spreadsheet vs spreadsheet-like simulator, without screens", f"={q(RC)}!$B${RC_GAP}", f"=IF(ABS(B22)<=0.15*{q(RC)}!$B$6,\"OK\",\"CHECK\")", "The two models agree within 15% under the same assumptions"),
    ("Payoff matrix: no errors", f"=SUMPRODUCT(--ISERROR({q(PAY)}!$A$6:$J$42))", "=IF(B23=0,\"OK\",\"CHECK\")", ""),
    ("Arrival Curve: no errors", f"=SUMPRODUCT(--ISERROR({q(AC)}!$A$3:$N${AL+4}))", "=IF(B24=0,\"OK\",\"CHECK\")", ""),
    ("Department cohorts add up to students per lunch", f"={q(AC)}!$B${C_LAST+1}-{REF['students']}", "=IF(ABS(B25)<0.5,\"OK\",\"CHECK\")", "Rough sizes scaled to the plates served"),
]
mm1 = lambda lam, mu: (f"IF({lam}/(2*{mu})<1,(({lam}/{mu})^2/2*2/(2-{lam}/{mu}))/(1+{lam}/{mu}+({lam}/{mu})^2/2*2/(2-{lam}/{mu}))/(2*{mu}-{lam}),99)")  # noqa: E731
for k_, (lab, v, res, what) in enumerate(checks):
    rr = 5 + k_
    if isinstance(v, str) and "_wq(" in v:
        mu_ref = REF["mu"]
        v = f"={mm1(17, '(1.1*' + mu_ref + ')')}-{mm1(17, mu_ref)}"
    put(ws, f"A{rr}", lab)
    put(ws, f"B{rr}", v, kind="link" if isinstance(v, str) and "!" in v else ("input" if not isinstance(v, str) else "formula"), fmt="0.00")
    put(ws, f"C{rr}", res, kind="formula", fill=F_OUT)
    put(ws, f"D{rr}", what, kind="note")
CK_LAST = 5 + len(checks) - 1
put(ws, f"A{CK_LAST+2}", "All checks", bold=True)
put(ws, f"C{CK_LAST+2}", f'=IF(COUNTIF(C5:C{CK_LAST},"OK")={len(checks)},"ALL OK","CHECK")', kind="formula", fill=F_OUT)
ALL_OK = f"{q(CK)}!$C${CK_LAST+2}"

# =============================================================================
# Start Here (first)
# =============================================================================
ws = wb.create_sheet("Start Here", 0)
for i, w in enumerate([24, 34, 78], start=1):
    ws.column_dimensions[L(i)].width = w
ws.sheet_view.showGridLines = False
put(ws, "A1", "MDS decision workbook — Beyond the Bottleneck (Group WGB3)", size=14, bold=True)
ws["A1"].font = Font(name=FONT, size=14, bold=True, color="FFFFFF")
for cl in "ABC":
    ws[f"{cl}1"].fill = F_TITLE
put(ws, "A2", "Enabling smarter lunch flow by optimising queue management and capacity utilisation across Chefs Touch centres (Central CT and Munch Mess, 11:30–14:30).", kind="note")
ws.merge_cells("A2:C2")
put(ws, "A4", "How to use", bold=True)
for k_, line in enumerate([
    "1. Change only BLUE cells, and almost all of them live on the Inputs tab. Black cells are formulas; GREEN cells pull values from another tab.",
    "2. YELLOW cells are not measured yet (assumed or group estimate). Replace them with measurements (Data Collection tab).",
    "3. Green-filled cells are the key results. The Checks tab must say ALL OK:",
]):
    put(ws, f"A{5+k_}", line)
    ws.merge_cells(f"A{5+k_}:{'B' if k_ == 2 else 'C'}{5+k_}")
put(ws, "C7", f"={ALL_OK}", kind="link", fill=F_OUT)
put(ws, "A9", "How the parts fit together", bold=True)
for k_, line in enumerate([
    "Inputs → S15 Queuing (the analytic model) → LP Student Flow (the primary decision: students per mess per slot) → LP Food Allocation (food supports the flow)",
    "Inputs → the simulator (python -m messq.scenarios) → Scenarios, S7 Payoff Matrix, Reconciliation (why the two models differ)",
    "Decision Rule = how the screens turn estimates into advice: when Central, when Munch, when no advice",
]):
    put(ws, f"A{10+k_}", line)
    ws.merge_cells(f"A{10+k_}:C{10+k_}")
put(ws, "A14", "Status tags", bold=True)
table(ws, 15, 1, ["Tag", "Meaning", "Example"], [
    ["Measured", "From field work, CT or the group", "2,960 students; seats 900 / 492; 2 stations + 1 scanner per mess"],
    ["Group estimate", "The group's figure, not yet timed", "Eating 14–18 min; disposal ≤ 2 min; food ready 70% of the time"],
    ["Assumed", "A placeholder until measured", "10 students/min per station; MIT lab share; DLHS/MILHS size"],
    ["Calibrated", "Not measured: chosen so the model reproduces what was observed", "Lag from the start of a lunch break to the mess door"],
    ["Simulated", "Output of the simulator, 20 lunches per row", f"Average wait {W1:.1f} → {W3:.1f} min on a busy day"],
    ["Policy", "Our design choice", "Minimum saving 2 min before suggesting a switch"],
], wrap_cols=(1, 2))
put(ws, "A22", "Tabs", bold=True)
tabs = [
    ("Inputs", "—", "One assumptions table: value, unit, status, source, date, where it is used"),
    ("S2-3 Problem & Root Cause", "2–3", "Problem and decision; 5 Whys backtracked from the Phase 1 symptom; fishbone; issue tree"),
    ("S4 Biases & Ethics", "4", "Status quo, herding, loss aversion, missing information (hypotheses vs findings); DPDP ethics"),
    ("S5-6 Priority Matrix", "5–6", "ABC/XYZ menu matrix; tray weights; impact–effort matrix; decision dilemmas"),
    ("Arrival Curve", "15", "Department lunch breaks added up: when students arrive, and the 13:10–13:30 overlap"),
    ("S15 Queuing", "15", "M/M/1 check, utilisation curve, M/M/c + fluid queue by 10-min slot, four-stage throughput"),
    ("LP Student Flow", "10–11", "PRIMARY model: students to direct to each mess per slot; food as a constraint; shadow price"),
    ("LP Food Allocation", "10–11", "SECONDARY model: the star dish split that supports the flow; graphical method"),
    ("S7 Payoff Matrix", "7", "Five alternatives × three kinds of day, every cell simulated: maximax, maximin, Hurwicz, Laplace, EMV, regret, EVPI"),
    ("S18 Heuristics", "18", "Door-screen rule, reorder point, heuristic vs full model vs LP bound, metaheuristics"),
    ("Decision Rule", "—", "When the screen recommends Munch, Central, or gives no advice; worked situations"),
    ("Scenarios", "—", "Current vs queue-only vs queue + food, with uncertainty; stress tests"),
    ("Reconciliation", "—", "Why the spreadsheet and the simulator differ, step by step"),
    ("Simulation Method", "—", "Arrivals, queues, service, food, routing, measures, runs"),
    ("Data Collection", "—", "Stage 2 template: what to measure at both messes, with an automatic diagnosis"),
    ("Checks", "—", "Validation: no errors, balances, constraints, calibration, response to inputs"),
]
table(ws, 23, 1, ["Tab", "Session(s)", "What it does"], [[t, s, d] for t, s, d in tabs], wrap_cols=(2,))
for k_, (t, _, _) in enumerate(tabs):
    c = ws[f"A{24+k_}"]
    c.hyperlink = f"#{q(t)}!A1"
    c.font = Font(name=FONT, size=10, color="0563C1", underline="single")

for wsx in wb.worksheets:
    for row in wsx.iter_rows():
        for c in row:
            if c.value is not None and (c.font is None or c.font.name != FONT):
                c.font = Font(name=FONT, size=c.font.size or 10, bold=c.font.bold, italic=c.font.italic, color=c.font.color)
wb.calculation.fullCalcOnLoad = True  # no cached values from openpyxl: make Excel compute every formula on open
wb.save(OUT)
print("saved", OUT, "| LP optimum avg", round(LP_OBJ / sum(D_BINS), 3), "redirected", round(float(sum(Y))), "food dual", round(float(LP_DUAL), 2))
