"""Build docs/Queue_Capacity_LoadBalancing.xlsx: queue management (M/M/1, M/M/c per process),
capacity management (seat turnover, bottleneck) and load balancing (dynamic vs static), all on
SIMULATED data.

    python tools/queue_capacity_data.py              # simulate -> results/queue_capacity.json
    python tools/build_queue_capacity_workbook.py    # -> docs/Queue_Capacity_LoadBalancing.xlsx

Every number the sheets compute is a live formula on the Assumptions and Sim Data tabs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, Series
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from messq.config import load_config  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "docs" / "Queue_Capacity_LoadBalancing.xlsx")
D = json.loads((ROOT / "results" / "queue_capacity.json").read_text())
CFG = load_config()
LUNCH = CFG.simulation.slot("lunch")
A_, B_ = CFG.mess("A"), CFG.mess("B")
SIM = CFG.simulation

FONT = "Arial"
BLUE, GREEN, BLACK, GREY = "0000FF", "008000", "000000", "595959"
F_HEAD = PatternFill("solid", fgColor="E7E6E1")
F_TITLE = PatternFill("solid", fgColor="1F3A5F")
F_KEY = PatternFill("solid", fgColor="FFFF00")
F_NOTE = PatternFill("solid", fgColor="EEF4FB")
F_OUT = PatternFill("solid", fgColor="E8F3E8")
F_DATA = PatternFill("solid", fgColor="F2F2F2")
F_BAD = PatternFill("solid", fgColor="FBE3E3")
THIN = Side(style="thin", color="C9C8C3")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

wb = Workbook()
wb.remove(wb.active)


def sheet(name, title, sub, widths):
    ws = wb.create_sheet(name)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[L(i)].width = w
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color="FFFFFF")
    for c in range(1, len(widths) + 1):
        ws.cell(row=1, column=c).fill = F_TITLE
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, size=10, italic=True, color=GREY)
    return ws


def put(ws, ref, v, kind="text", fmt=None, bold=False, fill=None, wrap=False):
    c = ws[ref]
    c.value = v
    color = {"input": BLUE, "data": BLUE, "link": GREEN}.get(kind, BLACK)
    if kind == "auto":
        color = GREEN if isinstance(v, str) and "!" in v else BLACK
    c.font = Font(name=FONT, size=10, bold=bold or kind == "head", color=color)
    if kind == "head":
        c.fill, c.alignment, c.border = F_HEAD, CENTER, BOX
    if kind in ("input", "data", "link", "formula", "auto"):
        c.border = BOX
    if kind == "data":
        c.fill = F_DATA
    if kind == "note":
        c.fill, c.alignment = F_NOTE, WRAP
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if wrap:
        c.alignment = WRAP
    return c


def note(ws, ref, text, span_to=None, height=None):
    put(ws, ref, text, kind="note")
    if span_to:
        ws.merge_cells(f"{ref}:{span_to}")
    if height:
        ws.row_dimensions[ws[ref].row].height = height


def heads(ws, row, col, names, height=30):
    for j, h in enumerate(names):
        put(ws, f"{L(col + j)}{row}", h, kind="head")
    ws.row_dimensions[row].height = height


def rule_label(p):
    """Rule names as shown: static assignments are orders, so they assume everyone obeys unless stated."""
    return p + " (enforced: all obey)" if p.startswith("Static") and "obey" not in p else p


def q(name):
    return "'" + name.replace("'", "''") + "'"


def clock(m):
    t = 11 * 60 + 30 + m
    return f"{t // 60:02d}:{t % 60:02d}"


# =============================================================================
# Assumptions (every input lives here)
# =============================================================================
AS = "Assumptions"
ws = sheet(AS, "Assumptions: every input behind the simulated data", "Blue = input. Yellow = not measured yet. Change an input here, re-run "
           "python tools/queue_capacity_data.py to refresh the Sim Data tab, then rebuild.", [62, 12, 14, 16, 70])
heads(ws, 4, 1, ["Assumption", "Value", "Unit", "Status", "Source / note"])
ROWS = [
    ("sec", "DEMAND"),
    ("students", "Students per lunch (both messes)", LUNCH.expected_students, "students", "Measured", "Plates served (Phase 1)", "#,##0"),
    ("hA", "Share who eat at Central by habit (no screens)", round(SIM.habit_share["A"], 3), "share", "Measured", "Group: ~2,360 Central, ~600 Munch", "0.0%"),
    ("window", "Lunch window", LUNCH.duration_min, "minutes", "Measured", "11:30–14:30", "0"),
    ("lag_m", "Arrival lag after a department's lunch break starts: mean", LUNCH.lag_mean_min, "minutes", "Calibrated",
     "Fits the 17–25 min visit and ~15 min peak delay; department breaks from the group's timetable", "0"),
    ("lag_sd", "Arrival lag: spread", LUNCH.lag_sd_min, "minutes", "Calibrated", "As above", "0"),
    ("sec", "STAGE 1: BIOMETRIC SCAN (M/M/1 per mess: one scanner)"),
    ("scanners", "Face scanners per mess", A_.scanners, "scanners", "Measured", "Group observation", "0"),
    ("scan_s", "Time per face scan", A_.scan_time_s, "seconds", "Assumed", "Stopwatch at the scanner", "0.0"),
    ("plate", "Collect a plate after the scan (mean of 15–35 s)", sum(SIM.plate_pickup_s) / 2, "seconds", "Assumed", "Group: scan + plate up to ~45 s", "0"),
    ("sec", "STAGE 2: SERVING STATIONS (M/M/c per mess, c = 2)"),
    ("c", "Serving stations per mess", A_.counters, "stations", "Measured", "Group observation", "0"),
    ("mu", "Service rate per station", A_.service_rate_per_counter_per_min, "students/min", "Assumed", "≈6 s per student; stopwatch 20–30 students", "0.0"),
    ("cv", "Variability of serving time (coefficient of variation)", SIM.service_cv, "ratio", "Assumed", "1.0 would be exponential, as M/M/c assumes", "0.0"),
    ("line", "Walk the rest of the food line (mean of 40–80 s)", sum(SIM.food_line_s) / 2, "seconds", "Assumed", "Time a few students", "0"),
    ("sec", "STAGE 3: EATING (seats as servers)"),
    ("seats_A", "Seats: Central CT", A_.seats, "seats", "Measured", "Group count", "#,##0"),
    ("seats_B", "Seats: Munch Mess", B_.seats, "seats", "Measured", "Group recount (Oct 2026)", "#,##0"),
    ("eat_lo", "Eating time: low", SIM.eat_min[0], "minutes", "Group estimate", "Group: 12–15 min", "0"),
    ("eat_hi", "Eating time: high", SIM.eat_min[1], "minutes", "Group estimate", "As above", "0"),
    ("changeover", "Seat changeover (next diner sits after the last leaves)", 0, "minutes", "Assumed",
     "Students clear their own plate; no table cleaning between diners. Raise it to test", "0.0"),
    ("sec", "STAGE 4: DISPOSAL (no queue: M/M/∞)"),
    ("disp_lo", "Disposal: low", SIM.dispose_min[0], "minutes", "Group estimate", "Group: 2 min at most", "0.0"),
    ("disp_hi", "Disposal: high", SIM.dispose_min[1], "minutes", "Group estimate", "As above", "0.0"),
    ("sec", "LOAD BALANCING (door screens)"),
    ("comply", "Share who follow a screen's advice", SIM.compliance, "share", "Assumed", "The pilot measures it", "0%"),
    ("walk", "Walk between the two mess doors", CFG.layout.switch_walk_s / 60, "minutes", "Assumed", "30 s", "0.0"),
    ("min_save", "Minimum saving before a screen suggests switching", CFG.layout.min_saving_min, "minutes", "Policy", "Our design choice", "0.0"),
    ("sec", "SIMULATION"),
    ("seeds", "Simulated lunches averaged per scenario", D["seeds"], "lunches", "Design", "Seeds 0–19; the same students in every scenario", "0"),
    ("slot", "Time-slot length in the tables", 10, "minutes", "Design", "18 slots from 11:30", "0"),
]
REF = {}
r = 5
for row in ROWS:
    if row[0] == "sec":
        put(ws, f"A{r}", row[1], bold=True)
        ws[f"A{r}"].font = Font(name=FONT, size=10, bold=True, color="1F3A5F")
        r += 1
        continue
    key, label, val, unit, status, src, fmt = row
    put(ws, f"A{r}", label)
    c = put(ws, f"B{r}", val, kind="input", fmt=fmt)
    if status in ("Assumed", "Group estimate", "Calibrated"):
        c.fill = F_KEY
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", status, bold=status == "Measured")
    put(ws, f"E{r}", src, wrap=True)
    REF[key] = f"{q(AS)}!$B${r}"
    r += 1
r += 1
put(ws, f"A{r}", "Department lunch breaks (shape the arrival surge; sizes are rough and scaled to the plates served)", bold=True)
r += 1
heads(ws, r, 1, ["Department", "Students (scaled)", "Break starts", "Break ends", "Status"])
for name, n, a, b in LUNCH.cohorts():
    r += 1
    put(ws, f"A{r}", name)
    put(ws, f"B{r}", round(n), kind="input", fmt="#,##0")
    put(ws, f"C{r}", clock(a), kind="input")
    put(ws, f"D{r}", clock(b), kind="input")
    put(ws, f"E{r}", "Timetable from the group" + ("; timing assumed" if name == "MIRM" else "") +
        ("; MIT eats here on lab days (45% assumed)" if "lab" in name else ""))
ws.freeze_panes = "B5"

# =============================================================================
# Variables
# =============================================================================
VA = "Variables"
ws = sheet(VA, "Variables and formulas", "Queuing notation used on every tab", [16, 34, 70, 34])
heads(ws, 4, 1, ["Symbol", "Name", "Meaning at the mess", "Formula"])
VARS = [
    ("λ (lambda)", "Arrival rate", "Students reaching a stage per minute (e.g. reaching the scanner at Central)", "Counted in the simulation per 10-min slot"),
    ("μ (mu)", "Service rate per server", "Students one server can finish per minute: one scanner, one serving station, one seat", "μ = 1 ÷ mean service time"),
    ("c", "Number of servers", "1 scanner per mess; 2 serving stations per mess; 900 / 492 seats", "Measured"),
    ("a", "Offered load", "Work arriving, in server-equivalents", "a = λ ÷ μ"),
    ("ρ (rho)", "Utilisation", "Share of the time each server is busy", "M/M/1: ρ = λ ÷ μ.   M/M/c: ρ = λ ÷ (c·μ)"),
    ("Stable?", "Stability condition", "A queue settles to a steady size only if servers can keep up", "Stable if ρ < 1; above 1 the queue grows by (λ − c·μ) every minute"),
    ("P0", "Probability the stage is empty", "Chance nobody is waiting or being served", "M/M/1: 1 − ρ.   M/M/c: [Σₖ₌₀^{c−1} aᵏ/k! + a^c/(c!(1−ρ))]⁻¹"),
    ("C(c, a)", "Erlang C (probability of waiting)", "Chance an arriving student has to wait at all", "M/M/c: a^c/(c!(1−ρ)) · P0.   M/M/1: ρ"),
    ("Wq", "Mean wait in queue", "Minutes from joining the line to reaching the server", "M/M/1: ρ ÷ (μ − λ).   M/M/c: C(c,a) ÷ (c·μ − λ)"),
    ("Ws", "Mean service time", "Minutes being served", "Ws = 1 ÷ μ"),
    ("W", "Mean time in the stage", "Queue + service", "W = Wq + Ws"),
    ("Lq", "Mean number waiting", "Students standing in the line (time average)", "Lq = λ · Wq  (Little's Law)"),
    ("Ls", "Mean number in service", "Students being served", "Ls = λ · Ws = a"),
    ("L", "Mean number in the stage", "Everyone in the stage", "L = λ · W  (Little's Law)"),
    ("Little's Law", "L = λW", "Holds for any stable stage in steady state: time-average number = arrival rate × time each spends",
     "Check: simulated Lq vs λ × simulated Wq. A big gap means the stage is not in steady state (queue growing or draining)"),
    ("cv", "Coefficient of variation of service", "Real service is more regular than exponential", "M/G/1 (Pollaczek–Khinchine): Wq = (1 + cv²)/2 × Wq(M/M/1); M/G/c ≈ the same factor"),
    ("Turnover time", "Seat turnover time", "Minutes a seat is held by one diner, plus changeover", "T = eating time + changeover"),
    ("Turns/hour", "Seat turnover rate", "Diners one seat serves per hour", "60 ÷ T"),
]
for i, row in enumerate(VARS):
    for j, v in enumerate(row):
        put(ws, f"{L(1 + j)}{5 + i}", v, wrap=True, bold=j == 0)
    ws.row_dimensions[5 + i].height = 32
r = 6 + len(VARS)
put(ws, f"A{r}", "Which model for which process", bold=True)
heads(ws, r + 1, 1, ["Process", "Model", "Why", "Tab"])
MAP = [
    ("Biometric face scan", "M/M/1 (one scanner per mess)", "One server; students queue outside the door. Real scan times are regular (cv 0.3), so M/G/1 is closer", "Q1 Scanner"),
    ("Serving stations (kitchen counters)", "M/M/c with c = 2", "Two stations fed from one line. Serving time cv 0.6", "Q2 Serving stations"),
    ("Seats while eating", "M/G/c with c = seats", "Each seat is a server; a 'service' is one meal. With 900 / 492 seats nobody waits unless ρ ≥ 1", "Q3 Seats & disposal"),
    ("Disposal of plates", "M/G/∞ (no queue)", "Several bins; no one waits, so L = λ·W only", "Q3 Seats & disposal"),
    ("Whole visit", "Network of the four stages", "Little's Law on the whole mess: people inside = λ × visit time", "Littles Law"),
]
for i, row in enumerate(MAP):
    for j, v in enumerate(row):
        put(ws, f"{L(1 + j)}{r + 2 + i}", v, wrap=True)
    ws.row_dimensions[r + 2 + i].height = 32

# =============================================================================
# Sim Data (long format)
# =============================================================================
SD = "Sim Data"
ws = sheet(SD, "Simulated data: per 10-minute slot, mess, process and scenario",
           f"SIMULATED, not measured: average of {D['seeds']} simulated lunches (python tools/queue_capacity_data.py). Grey cells = data", [22, 14, 12, 10, 14, 16, 16, 16, 16])
heads(ws, 4, 1, ["Scenario", "Mess", "Process", "Slot", "λ arrivals (/min)", "Wq simulated (min)", "Stage time Ws simulated (min)",
                 "Lq simulated (avg waiting)", "Ls simulated (avg in service)"], 44)
WORLD = {"today": "Today (no screens)", "screens": "With Smart Scan screens"}
MESS = {"A": "Central CT", "B": "Munch Mess"}
STAGE = {"scanner": "Biometric scan", "station": "Serving station", "seat": "Seat (eating)", "disposal": "Disposal", "visit": "Whole visit"}
ROW = {}
r = 5
for w in WORLD:
    for m in MESS:
        for st in STAGE:
            for b, x in enumerate(D["worlds"][w][m][st]):
                put(ws, f"A{r}", WORLD[w])
                put(ws, f"B{r}", MESS[m])
                put(ws, f"C{r}", STAGE[st])
                put(ws, f"D{r}", clock(b * 10))
                for j, k in enumerate(["lam", "wq_min", "ws_min", "lq", "ls"]):
                    put(ws, f"{L(5 + j)}{r}", round(x[k], 4), kind="data", fmt="0.00")
                ROW[(w, m, st, b)] = r
                r += 1
SD_LAST = r - 1
ws.auto_filter.ref = f"A4:I{SD_LAST}"
ws.freeze_panes = "E5"
r += 1
put(ws, f"A{r}", "Per mess, whole lunch", bold=True)
heads(ws, r + 1, 1, ["Scenario", "Mess", "Students served", "Peak seats in use", "Stock-out minutes"])
TOT = {}
for k, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
    rr = r + 2 + k
    x = D["worlds"][w][m]
    put(ws, f"A{rr}", WORLD[w])
    put(ws, f"B{rr}", MESS[m])
    put(ws, f"C{rr}", round(x["students"], 1), kind="data", fmt="#,##0")
    put(ws, f"D{rr}", round(x["peak_seated"], 1), kind="data", fmt="#,##0")
    put(ws, f"E{rr}", round(x["outage_min"], 2), kind="data", fmt="0.0")
    TOT[(w, m)] = rr


def sd(w, m, st, b, col):
    return f"{q(SD)}!${col}${ROW[(w, m, st, b)]}"


# =============================================================================
# Queue tabs
# =============================================================================
def queue_tab(name, title, stage, c_ref, model, summary_note):
    ws = sheet(name, title, f"Model: {model}. λ, Wq and Lq come from the Sim Data tab (simulated); ρ, stability and the textbook waits are formulas.",
               [22, 12, 8, 11, 12, 10, 9, 10, 26, 12, 12, 12, 12, 12, 13, 26])
    cols = ["Scenario", "Mess", "Slot", "λ (/min)", "Service time (min)", "μ (/min)", "c", "ρ", "Stable?", "Wq textbook (min)",
            "Wq with cv correction (min)", "Wq simulated (min)", "Lq simulated", "λ × Wq simulated", "Little's Law: Lq ÷ λWq", "Reading"]
    top = 12
    heads(ws, top, 1, cols, 44)
    rows = []
    r = top + 1
    for w in WORLD:
        for m in MESS:
            for b in range(18):
                put(ws, f"A{r}", WORLD[w])
                put(ws, f"B{r}", MESS[m])
                put(ws, f"C{r}", clock(b * 10))
                put(ws, f"D{r}", f"={sd(w, m, stage, b, 'E')}", kind="link", fmt="0.00")
                put(ws, f"E{r}", f"={sd(w, m, stage, b, 'G')}", kind="link", fmt="0.000")
                put(ws, f"F{r}", f"=IF(E{r}>0,1/E{r},{DEFAULT_MU[stage]})", kind="formula", fmt="0.0")
                put(ws, f"G{r}", f"={c_ref(m)}", kind="link", fmt="0")
                put(ws, f"H{r}", f"=D{r}/(G{r}*F{r})", kind="formula", fmt="0%")
                put(ws, f"I{r}", f'=IF(D{r}=0,"No arrivals",IF(H{r}<0.85,"Stable",IF(H{r}<1,"Stable, near capacity","UNSTABLE: queue grows")))', kind="formula")
                a = f"(D{r}/F{r})"
                if model.startswith("M/M/1"):
                    wq = f"=IF(AND(D{r}>0,H{r}<1),H{r}/(F{r}-D{r}),\"—\")"
                else:
                    K = "{0,1,2,3,4,5,6,7,8,9}"
                    top_ = f"({a}^G{r}/FACT(G{r})/(1-H{r}))"
                    wq = (f"=IF(AND(D{r}>0,H{r}<1),{top_}/(SUMPRODUCT(--({K}<G{r}),{a}^{K}/FACT({K}))+{top_})/(G{r}*F{r}-D{r}),\"—\")")
                put(ws, f"J{r}", wq, kind="formula", fmt="0.00")
                put(ws, f"K{r}", f'=IF(ISNUMBER(J{r}),(1+{CV[stage]}^2)/2*J{r},"—")', kind="formula", fmt="0.00")
                put(ws, f"L{r}", f"={sd(w, m, stage, b, 'F')}", kind="link", fmt="0.00")
                put(ws, f"M{r}", f"={sd(w, m, stage, b, 'H')}", kind="link", fmt="0.0")
                put(ws, f"N{r}", f"=D{r}*L{r}", kind="formula", fmt="0.0")
                put(ws, f"O{r}", f'=IF(MAX(M{r},N{r})<0.5,"both ≈ 0",IF(N{r}=0,"no new arrivals",M{r}/N{r}))', kind="formula", fmt="0.00")
                put(ws, f"P{r}", f'=IF(D{r}=0,"",IF(H{r}>=1,"No steady state: line grows by ~"&TEXT((D{r}-G{r}*F{r})*10,"0")&" in this slot",IF(ISNUMBER(O{r}),IF(ABS(O{r}-1)<=0.2,"Little\'s Law holds (steady)",'
                                 f'IF(O{r}>1,"More waiting than λWq: queue left over from before","Fewer waiting than λWq: queue still building")),"Hardly any queue")))',
                    kind="formula")
                rows.append((w, m, b, r))
                r += 1
    last = r - 1
    ws.auto_filter.ref = f"A{top}:P{last}"
    ws.freeze_panes = f"D{top + 1}"
    # summary
    heads(ws, 4, 1, ["Scenario", "Mess", "Peak ρ", "Slots unstable (ρ ≥ 1)", "Slots near capacity (0.85–1)", "Worst simulated Wq (min)", "Avg simulated Wq (min)"], 44)
    for k, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
        rr = 5 + k
        rng = lambda col: f"{col}{top + 1}:{col}{last}"  # noqa: E731
        crit = f'{rng("A")},"{WORLD[w]}",{rng("B")},"{MESS[m]}"'
        put(ws, f"A{rr}", WORLD[w])
        put(ws, f"B{rr}", MESS[m])
        put(ws, f"C{rr}", f"=_xlfn.MAXIFS({rng('H')},{crit})", kind="formula", fmt="0%", fill=F_OUT)
        put(ws, f"D{rr}", f'=COUNTIFS({crit},{rng("H")},">=1")', kind="formula", fmt="0", fill=F_OUT)
        put(ws, f"E{rr}", f'=COUNTIFS({crit},{rng("H")},">=0.85",{rng("H")},"<1")', kind="formula", fmt="0")
        put(ws, f"F{rr}", f"=_xlfn.MAXIFS({rng('L')},{crit})", kind="formula", fmt="0.00")
        put(ws, f"G{rr}", f"=SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('L')}*{rng('D')})/"
                          f"SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('D')})", kind="formula", fmt="0.00")
    note(ws, "I4", summary_note, "P9", None)
    for rr in range(4, 10):
        ws.row_dimensions[rr].height = 22
    ws.row_dimensions[4].height = 44
    # chart: utilisation by slot
    cr = last + 3
    put(ws, f"A{cr}", "Utilisation ρ by slot (for the chart)", bold=True)
    heads(ws, cr + 1, 1, ["Slot"] + [f"{MESS[m]}, {WORLD[w].split(' (')[0]}" for w in WORLD for m in MESS] + ["Capacity (ρ = 1)"])
    for b in range(18):
        rr = cr + 2 + b
        put(ws, f"A{rr}", clock(b * 10))
        for j, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
            src = next(rw for ww, mm, bb, rw in rows if ww == w and mm == m and bb == b)
            put(ws, f"{L(2 + j)}{rr}", f"=H{src}", kind="formula", fmt="0%")
        put(ws, f"F{rr}", 1, fmt="0%")
    ch = LineChart()
    ch.title = f"{title.split(':')[0]}: utilisation ρ per 10-min slot"
    ch.y_axis.title = "ρ"
    ch.y_axis.number_format = "0%"
    ch.add_data(Reference(ws, min_col=2, max_col=6, min_row=cr + 1, max_row=cr + 19), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=cr + 2, max_row=cr + 19))
    ch.height, ch.width = 8, 18
    ws.add_chart(ch, f"H{cr}")
    return ws, rows, top, last


DEFAULT_MU = {"scanner": f"60/{REF['scan_s']}", "station": REF["mu"]}
CV = {"scanner": "0.3", "station": REF["cv"]}
Q1, Q1_ROWS, Q1_TOP, Q1_LAST = queue_tab(
    "Q1 Scanner", "Biometric scan: M/M/1 per mess", "scanner", lambda m: REF["scanners"], "M/M/1 (one face scanner per mess)",
    "Each mess has ONE face scanner (c = 1, μ ≈ 30 students/min at 2 s per scan). It is stable except where λ nears 30/min at Central in the 13:10 "
    "surge. Textbook M/M/1 overstates the wait because real scans are regular (cv 0.3); the cv-corrected column (M/G/1) is closer to the simulation. "
    "Students queueing here are OUTSIDE the door and not yet scanned, so the live system cannot see them.")
def _peak_rho(w, m, stage, c):
    return max(x["lam"] * x["ws_min"] / c for x in D["worlds"][w][m][stage])


_pA, _pAs, _pBs = _peak_rho("today", "A", "station", 2), _peak_rho("screens", "A", "station", 2), _peak_rho("screens", "B", "station", 2)
Q2, Q2_ROWS, Q2_TOP, Q2_LAST = queue_tab(
    "Q2 Serving stations", "Serving stations: M/M/c per mess (c = 2)", "station", lambda m: REF["c"], "M/M/c with c = 2 stations per mess",
    f"Two stations per mess (c = 2, μ = 10/min each, capacity 20/min). Today Central reaches ρ ≈ {_pA:.0%} in the 13:10 surge: the line grows every "
    f"minute, no steady state exists, and Little's Law only balances once the surge passes. With the screens Central's peak falls to ≈ {_pAs:.0%}: "
    f"still briefly over capacity in the surge (only 60% follow, and a screen only asks when walking saves ≥ 2 min), while Munch takes the overflow "
    f"(peak ≈ {_pBs:.0%}). This is the bottleneck stage.")

# =============================================================================
# Q3 Seats & disposal
# =============================================================================
Q3 = "Q3 Seats & disposal"
ws = sheet(Q3, "Seats (M/G/c, c = seats) and disposal (M/G/∞)", "Each seat is a server and one meal is its service; disposal has no queue. Little's Law: seats in use = λ × eating time",
           [22, 12, 8, 11, 12, 9, 10, 14, 12, 12, 14, 26])
heads(ws, 4, 1, ["Scenario", "Mess", "Slot", "λ sitting down (/min)", "Eating time W (min)", "Seats c", "ρ = λW ÷ c", "Stable?",
                 "Seats in use: simulated", "Seats in use: λ × W", "Little's Law ratio", "Disposal: L = λ × W (people at the bins)"], 44)
r = 5
Q3_ROWS = []
for w in WORLD:
    for m in MESS:
        seats = REF["seats_A"] if m == "A" else REF["seats_B"]
        for b in range(18):
            put(ws, f"A{r}", WORLD[w])
            put(ws, f"B{r}", MESS[m])
            put(ws, f"C{r}", clock(b * 10))
            put(ws, f"D{r}", f"={sd(w, m, 'seat', b, 'E')}", kind="link", fmt="0.00")
            put(ws, f"E{r}", f"=IF({sd(w, m, 'seat', b, 'G')}>0,{sd(w, m, 'seat', b, 'G')},({REF['eat_lo']}+{REF['eat_hi']})/2)", kind="link", fmt="0.0")
            put(ws, f"F{r}", f"={seats}", kind="link", fmt="#,##0")
            put(ws, f"G{r}", f"=D{r}*E{r}/F{r}", kind="formula", fmt="0%")
            put(ws, f"H{r}", f'=IF(D{r}=0,"No arrivals",IF(G{r}<1,"Stable: a seat is free","UNSTABLE: students wait for seats"))', kind="formula")
            put(ws, f"I{r}", f"={sd(w, m, 'seat', b, 'I')}", kind="link", fmt="0")
            put(ws, f"J{r}", f"=D{r}*E{r}", kind="formula", fmt="0")
            put(ws, f"K{r}", f'=IF(MAX(I{r},J{r})<5,"≈ 0",IF(J{r}=0,"no new diners",I{r}/J{r}))', kind="formula", fmt="0.00")
            put(ws, f"L{r}", f"={sd(w, m, 'disposal', b, 'E')}*{sd(w, m, 'disposal', b, 'G')}", kind="link", fmt="0.0")
            Q3_ROWS.append((w, m, b, r))
            r += 1
Q3_LAST = r - 1
ws.auto_filter.ref = f"A4:L{Q3_LAST}"
ws.freeze_panes = "D5"
note(ws, f"A{Q3_LAST + 2}", "Reading it: seats are never the constraint here. Even at the peak, ρ = λ × eating time ÷ seats stays well below 1 at both messes, so nobody "
     "waits for a seat (the simulated seat wait is ≈ 0). Little's Law holds well for seats in the middle of the lunch; in the first and last slots the ratio "
     "drifts because students who sat down in one slot are still eating in the next (the slot is shorter than a meal). Disposal never queues.", f"L{Q3_LAST + 2}", 58)

# =============================================================================
# Little's Law on the whole visit
# =============================================================================
LL = "Littles Law"
ws = sheet(LL, "Little's Law on the whole visit: where the system is steady and where it is not",
           "L = λ × W. Simulated people inside vs arrivals × visit time, per 10-minute slot", [22, 12, 8, 12, 12, 14, 14, 12, 40])
heads(ws, 4, 1, ["Scenario", "Mess", "Slot", "λ arriving (/min)", "Visit time W (min)", "People inside: simulated L", "λ × W", "L ÷ λW", "Reading"], 44)
r = 5
for w in WORLD:
    for m in MESS:
        for b in range(18):
            put(ws, f"A{r}", WORLD[w])
            put(ws, f"B{r}", MESS[m])
            put(ws, f"C{r}", clock(b * 10))
            put(ws, f"D{r}", f"={sd(w, m, 'visit', b, 'E')}", kind="link", fmt="0.00")
            put(ws, f"E{r}", f"={sd(w, m, 'visit', b, 'G')}", kind="link", fmt="0.0")
            put(ws, f"F{r}", f"={sd(w, m, 'visit', b, 'I')}", kind="link", fmt="0")
            put(ws, f"G{r}", f"=D{r}*E{r}", kind="formula", fmt="0")
            put(ws, f"H{r}", f'=IF(MAX(F{r},G{r})<10,"≈ 0",IF(G{r}=0,"no new arrivals",F{r}/G{r}))', kind="formula", fmt="0.00")
            put(ws, f"I{r}", f'=IF(D{r}=0,"",IF(ISNUMBER(H{r}),IF(ABS(H{r}-1)<=0.15,"Steady: L = λW holds",IF(H{r}<1,"Filling up: arrivals rising faster than people leave","Emptying: people from earlier slots still inside")),IF(G{r}=0,"Emptying: no new arrivals","Almost empty")))', kind="formula")
            r += 1
LL_LAST = r - 1
ws.auto_filter.ref = f"A4:I{LL_LAST}"
ws.freeze_panes = "D5"
note(ws, f"A{LL_LAST + 2}", "How to use Little's Law here: a stable stage in steady state has L = λW. Slot by slot the mess is never perfectly steady because arrivals "
     "follow the department lunch breaks. When L ÷ λW is well below 1 the mess is filling (the 12:00 and 13:00 surges); when it is above 1 people from the "
     "busy slot are still inside while new arrivals have dropped. Over the whole lunch the totals agree (Checks tab). The queue tabs apply the same test to "
     "each process: where ρ ≥ 1 the line keeps growing and no steady state exists.", f"I{LL_LAST + 2}", 70)

# =============================================================================
# Capacity
# =============================================================================
CP = "Capacity"
ws = sheet(CP, "Capacity management: seat turnover, stage capacities and the bottleneck", "Simulated averages from Sim Data; assumptions from Assumptions",
           [58, 16, 16, 50])
heads(ws, 4, 1, ["Measure", "Central CT", "Munch Mess", "How it is calculated"])


def wavg(w, m, st, col):
    """λ-weighted average of a Sim Data column over the lunch."""
    lam = f"{q(SD)}!$E${ROW[(w, m, st, 0)]}:$E${ROW[(w, m, st, 17)]}"
    x = f"{q(SD)}!${col}${ROW[(w, m, st, 0)]}:${col}${ROW[(w, m, st, 17)]}"
    return f"SUMPRODUCT({lam},{x})/SUM({lam})"


# Each formula is fn(m, X): m = mess id, X(key) = this column's cell for another row.
CAP = [
    ("sec", "1. AVERAGE TIMES (today, no screens; simulated)"),
    ("scan", "Average scan time (seconds)", lambda m, X: f"={wavg('today', m, 'scanner', 'G')}*60", "0.0", "Mean time at the face scanner, excluding the queue"),
    ("scanq", "Average wait for the scanner (minutes)", lambda m, X: f"={wavg('today', m, 'scanner', 'F')}", "0.00", "Queue outside the door"),
    ("stq", "Average wait at the serving station (minutes)", lambda m, X: f"={wavg('today', m, 'station', 'F')}", "0.00", "Queue for the 2 stations"),
    ("sts", "Average serving time (minutes)", lambda m, X: f"={wavg('today', m, 'station', 'G')}", "0.00", "At the station"),
    ("stt", "Average time at the kitchen / serving station (wait + serving, minutes)", lambda m, X: f"={X('stq')}+{X('sts')}", "0.00", "Queue + service"),
    ("eat", "Average lunch (eating) time at the table (minutes)", lambda m, X: f"={wavg('today', m, 'seat', 'G')}", "0.0", "Seat held from sitting down to getting up"),
    ("visit", "Average total visit, door to leaving (minutes)", lambda m, X: f"={wavg('today', m, 'visit', 'G')}", "0.0", "All four stages, queues included"),
    ("sec", "2. SEAT TURNOVER"),
    ("seats", "Seats", lambda m, X: f"={REF['seats_A'] if m == 'A' else REF['seats_B']}", "#,##0", "Measured (Munch recounted: 492)"),
    ("turn", "Seat turnover time T (minutes per diner)", lambda m, X: f"={X('eat')}+{REF['changeover']}", "0.0", "Eating time + changeover (assumed 0)"),
    ("turns_h", "Seat turnover rate (diners per seat per hour)", lambda m, X: f"=60/{X('turn')}", "0.00", "60 ÷ T"),
    ("seatcap", "Seating capacity (students per minute)", lambda m, X: f"={X('seats')}/{X('turn')}", "0.0", "Seats ÷ T (Little's Law: λmax = L ÷ W)"),
    ("seatcap_l", "Seating capacity over the lunch window (students)", lambda m, X: f"={X('seats')}*{REF['window']}/{X('turn')}", "#,##0", "Seats × 180 ÷ T"),
    ("served", "Students served this lunch (simulated)", lambda m, X: f"={q(SD)}!$C${TOT[('today', m)]}", "#,##0", "Sim Data"),
    ("turns", "Actual turns per seat this lunch", lambda m, X: f"={X('served')}/{X('seats')}", "0.00", "Students served ÷ seats"),
    ("peak", "Peak seats in use (simulated)", lambda m, X: f"={q(SD)}!$D${TOT[('today', m)]}", "#,##0", "Sim Data"),
    ("peakutil", "Peak seat utilisation", lambda m, X: f"={X('peak')}/{X('seats')}", "0%", "Peak in use ÷ seats"),
    ("sec", "3. CAPACITY OF EACH STAGE (students per minute) AND THE BOTTLENECK"),
    ("cap_scan", "Scanner capacity", lambda m, X: f"={REF['scanners']}*60/{REF['scan_s']}", "0.0", "Scanners × 60 ÷ seconds per scan"),
    ("cap_st", "Serving-station capacity", lambda m, X: f"={REF['c']}*{REF['mu']}", "0.0", "Stations × μ"),
    ("cap_seat", "Seating capacity", lambda m, X: f"={X('seatcap')}", "0.0", "From section 2"),
    ("cap_disp", "Disposal capacity", lambda m, X: "no limit", None, "No queue: several bins, 1–2 min each"),
    ("bottle", "Bottleneck (smallest capacity)", lambda m, X: (
        f'=IF(MIN({X("cap_scan")},{X("cap_st")},{X("cap_seat")})={X("cap_st")},"Serving stations",'
        f'IF(MIN({X("cap_scan")},{X("cap_st")},{X("cap_seat")})={X("cap_scan")},"Scanner","Seats"))'), None, "The stage with the smallest capacity"),
    ("design", "Design capacity per lunch (bottleneck × window, students)", lambda m, X: f"=MIN({X('cap_scan')},{X('cap_st')},{X('cap_seat')})*{REF['window']}", "#,##0", "Best possible output"),
    ("outage", "Stock-out minutes this lunch (simulated)", lambda m, X: f"={q(SD)}!$E${TOT[('today', m)]}", "0.0", "Stations idle while the star dish is out"),
    ("effective", "Effective capacity per lunch (students)", lambda m, X: f"={X('design')}*(1-{X('outage')}/{REF['window']})", "#,##0", "Design × share of time food is available"),
    ("util", "Utilisation = actual ÷ design", lambda m, X: f"={X('served')}/{X('design')}", "0%", "OM definition"),
    ("eff", "Efficiency = actual ÷ effective", lambda m, X: f"={X('served')}/{X('effective')}", "0%", "OM definition"),
    ("peak_arr", "Peak 10-min arrival rate at the serving stations (today, /min)",
     lambda m, X: f"=MAX({q(SD)}!$E${ROW[('today', m, 'station', 0)]}:$E${ROW[('today', m, 'station', 17)]})", "0.0", "Sim Data"),
    ("peak_ratio", "Peak arrivals ÷ serving capacity", lambda m, X: f"={X('peak_arr')}/{X('cap_st')}", "0%", "Above 100% the line grows"),
]
CROW = {}
r = 5
for row in CAP:
    if row[0] == "sec":
        put(ws, f"A{r}", row[1], bold=True)
        ws[f"A{r}"].font = Font(name=FONT, size=10, bold=True, color="1F3A5F")
    else:
        CROW[row[0]] = r
    r += 1
CAP_LAST = r - 1
for row in CAP:
    if row[0] == "sec":
        continue
    key, label, fn, fmt, how = row
    rr = CROW[key]
    put(ws, f"A{rr}", label)
    for m, col in (("A", "B"), ("B", "C")):
        put(ws, f"{col}{rr}", fn(m, lambda k, col=col: f"{col}{CROW[k]}"), kind="auto", fmt=fmt,
            fill=F_OUT if key in ("turn", "turns_h", "seatcap", "bottle", "peakutil", "util") else None)
    put(ws, f"D{rr}", how, wrap=True)
note(ws, f"A{CAP_LAST + 2}", "Reading it: seat turnover is about one diner every ~13.5 minutes, i.e. about 4.4 diners per seat per hour, so seats could absorb "
     "~67 students/min at Central and ~36/min at Munch. The serving stations (20/min per mess) are the bottleneck at both messes, well below the "
     "scanner (30/min) and the seats. Capacity is lost to stock-outs (effective < design). In the surges Central's arrivals exceed its 20/min "
     "while Munch's sit far below theirs: the capacity problem is one of balance, which is what load balancing addresses.", f"D{CAP_LAST + 2}", 70)
bc = BarChart()
bc.title = "Stage capacity (students/min): the bottleneck is the serving stations"
bc.add_data(Reference(ws, min_col=2, max_col=3, min_row=CROW["cap_scan"], max_row=CROW["cap_seat"]), titles_from_data=False)
bc.set_categories(Reference(ws, min_col=1, min_row=CROW["cap_scan"], max_row=CROW["cap_seat"]))
from openpyxl.chart.series import SeriesLabel  # noqa: E402
bc.series[0].tx = SeriesLabel(v="Central CT")
bc.series[1].tx = SeriesLabel(v="Munch Mess")
bc.height, bc.width = 8, 16
ws.add_chart(bc, f"F4")

# =============================================================================
# Load Balancing
# =============================================================================
LB = "Load Balancing"
ws = sheet(LB, "Load balancing with Smart Scan: when we route students to the other mess, and why a fixed rule fails",
           "Dynamic routing from live scans vs static 'department / year X eats at mess Y' rules, on simulated lunches", [56, 14, 14, 14, 14, 14, 14, 14, 14])
put(ws, "A4", "1. How the routing works (every 5 seconds)", bold=True)
STEPS = [
    "Scans in: every face scan arrives with a timestamp and the mess (no face data, only id + time + mess).",
    "Arrival rate: λ̂ for each mess = scans in the last 5 minutes ÷ 5.",
    "Queue estimate: fluid model. Backlog B grows by (λ̂ − c·μ) per minute when arrivals exceed the 2 stations' capacity, and drains otherwise.",
    "Predicted wait at each mess for someone arriving now = B ÷ (c·μ) + M/M/c wait + food delay (a star dish out = nobody served until the refill).",
    "Equal-wait split: find the share p of arrivals for Central at which both predicted waits are equal (Wardrop equilibrium, by bisection).",
    "Door advice: at the busier mess's door, ask a share (h − p) ÷ (h × κ) of students to switch (h = habit share, κ = share who follow).",
    "Threshold: only advise a switch if it saves at least the minimum saving after the 30 s walk; otherwise 'come in, this is still your fastest'.",
    "Feedback: the advice changes arrivals, which changes the next scans and the next estimate, so it never sends everyone to one mess (no herding).",
]
for i, t in enumerate(STEPS):
    put(ws, f"A{5 + i}", f"{i + 1}. {t}", wrap=True)
    ws.merge_cells(f"A{5 + i}:I{5 + i}")
    ws.row_dimensions[5 + i].height = 28
r = 14
put(ws, f"A{r}", "2. Try the rule (change the blue cells)", bold=True)
TRY = [("Predicted wait if you stay at Central (min)", 6, "0.0"), ("Predicted wait at Munch (min)", 1, "0.0"),
       ("Walk between doors (min)", f"={REF['walk']}", "0.0"), ("Minimum saving to suggest a switch (min)", f"={REF['min_save']}", "0.0"),
       ("Habit share h for Central", f"={REF['hA']}", "0%"), ("Equal-wait share p for Central (from the engine)", 0.6, "0%"),
       ("Share who follow κ", f"={REF['comply']}", "0%")]
for i, (lab, v, fmt) in enumerate(TRY):
    put(ws, f"A{r + 1 + i}", lab)
    put(ws, f"B{r + 1 + i}", v, kind="link" if isinstance(v, str) else "input", fmt=fmt)
t0 = r + 1
put(ws, f"A{r + 9}", "Saving after the walk (min)")
put(ws, f"B{r + 9}", f"=B{t0}-B{t0 + 1}-B{t0 + 2}", kind="formula", fmt="0.0", fill=F_OUT)
put(ws, f"A{r + 10}", "Share of arrivals at Central's door asked to switch")
put(ws, f"B{r + 10}", f"=IF(B{r + 9}>=B{t0 + 3},MIN(1,MAX(0,(B{t0 + 4}-B{t0 + 5})/(B{t0 + 4}*B{t0 + 6}))),0)", kind="formula", fmt="0%", fill=F_OUT)
put(ws, f"A{r + 11}", "What the screen outside Central says")
put(ws, f"B{r + 11}", f'=IF(B{r + 10}>=0.5,"Munch is faster right now →",IF(B{r + 10}>=0.15,"In a hurry? Munch is "&TEXT(B{r + 9},"0")&" min faster →","Come on in"))',
    kind="formula", fill=F_OUT)
ws.merge_cells(f"B{r + 11}:E{r + 11}")

r = r + 13
put(ws, f"A{r}", "3. What the screens decided at moments of one simulated lunch (seed 0, with screens)", bold=True)
heads(ws, r + 1, 1, ["Time", "Central: arrivals /min", "Central: predicted wait (min)", "Munch: arrivals /min", "Munch: predicted wait (min)",
                     "Equal-wait share for Central", "Central door: share asked to switch", "Saving (min)", "Screen outside Central"], 44)
for i, s in enumerate(D["snapshots"]):
    rr = r + 2 + i
    dA = s["doors"]["A"]
    say = ("Munch is faster right now →" if dA["level"] == "strong" else f"In a hurry? Munch is ~{round(dA['saving'])} min faster →"
           if dA["level"] == "soft" else "Come on in")
    for j, v in enumerate([clock(s["t_min"]), s["A"]["rate"], s["A"]["to_food"], s["B"]["rate"], s["B"]["to_food"], s["A"]["share"],
                           dA["p_switch"] if dA["go_to"] else 0, dA["saving"] if dA["go_to"] else 0, say]):
        put(ws, f"{L(1 + j)}{rr}", v, kind="data" if j not in (0, 8) else "text", fmt="0%" if j in (5, 6) else "0.0")
r = r + 3 + len(D["snapshots"])
put(ws, f"A{r}", "4. When routing happens: students asked to switch per 10-min slot (with screens; simulated average)", bold=True)
heads(ws, r + 1, 1, ["Slot", "Students deciding", "Asked to switch", "Actually switched", "Share asked", "Departments on lunch break"], 30)
ADV0 = r + 2
for b, (n_, asked, moved) in enumerate(D["worlds"]["screens"]["advice"]):
    rr = ADV0 + b
    put(ws, f"A{rr}", clock(b * 10))
    put(ws, f"B{rr}", round(n_, 1), kind="data", fmt="0")
    put(ws, f"C{rr}", round(asked, 1), kind="data", fmt="0")
    put(ws, f"D{rr}", round(moved, 1), kind="data", fmt="0")
    put(ws, f"E{rr}", f"=IF(B{rr}>0,C{rr}/B{rr},0)", kind="formula", fmt="0%")
    put(ws, f"F{rr}", ", ".join(LUNCH.on_break(b * 10, b * 10 + 10)))
ADV1 = ADV0 + 17
put(ws, f"A{ADV1 + 1}", "Total")
for col in "BCD":
    put(ws, f"{col}{ADV1 + 1}", f"=SUM({col}{ADV0}:{col}{ADV1})", kind="formula", fmt="#,##0", bold=True)
note(ws, f"G{ADV0}", "The screens stay quiet when both messes are quick (before 12:00, and between the surges) and ask students to walk only when "
     "Central's predicted wait exceeds Munch's by more than the minimum saving: in the 12:00 and 13:00–13:30 surges. Students are never assigned; "
     "each one sees advice based on the queue at that moment.", f"I{ADV0 + 8}")

r = ADV1 + 4
put(ws, f"A{r}", "5. Static rules vs dynamic routing (average day, simulated)", bold=True)
heads(ws, r + 1, 1, ["Rule", "Average wait (min)", "90th pct wait (min)", "Students waiting > 10 min", "Share eating at Munch", "Students moved from their usual mess",
                     "Munch stock-outs per lunch", "Peak queue: Central", "Peak queue: Munch"], 44)
P0 = r + 2
pol_names = list(D["policies"])
for i, p in enumerate(pol_names):
    v = D["policies"][p]
    rr = P0 + i
    put(ws, f"A{rr}", rule_label(p), wrap=True)
    put(ws, f"B{rr}", round(v["wait"], 2), kind="data", fmt="0.00")
    put(ws, f"C{rr}", round(v["p90"], 1), kind="data", fmt="0.0")
    put(ws, f"D{rr}", round(v["long"]), kind="data", fmt="#,##0")
    put(ws, f"E{rr}", round(v["munch_share"], 3), kind="data", fmt="0%")
    put(ws, f"F{rr}", f"=MAX(0,E{rr}-(1-{REF['hA']}))*{REF['students']}", kind="formula", fmt="#,##0")
    put(ws, f"G{rr}", round(v["outages_B"], 2), kind="data", fmt="0.0")
    put(ws, f"H{rr}", round(v["peak_q"]["A"]), kind="data", fmt="0")
    put(ws, f"I{rr}", round(v["peak_q"]["B"]), kind="data", fmt="0")
    ws.row_dimensions[rr].height = 28
P1 = P0 + len(pol_names) - 1
bc = BarChart()
bc.type = "bar"
bc.title = "Average wait by rule (min)"
bc.add_data(Reference(ws, min_col=2, min_row=P0 - 1, max_row=P1), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=1, min_row=P0, max_row=P1))
bc.legend = None
bc.height, bc.width = 8, 18
ws.add_chart(bc, f"K{P0 - 1}")

r = P1 + 3
put(ws, f"A{r}", "6. Does the rule hold on other kinds of day? Average wait (min)", bold=True)
variants = D["variants"]
heads(ws, r + 1, 1, ["Rule"] + variants, 44)
R0 = r + 2
for i, p in enumerate(D["robust"]):
    rr = R0 + i
    put(ws, f"A{rr}", rule_label(p), wrap=True)
    for j, v in enumerate(variants):
        put(ws, f"{L(2 + j)}{rr}", round(D["robust"][p][v]["wait"], 2), kind="data", fmt="0.00")
    ws.row_dimensions[rr].height = 28
R1 = R0 + len(D["robust"]) - 1
rr = R1 + 1
put(ws, f"A{rr}", "Best rule on this kind of day", bold=True)
for j in range(len(variants)):
    col = L(2 + j)
    put(ws, f"{col}{rr}", f"=INDEX($A${R0}:$A${R1},MATCH(MIN({col}{R0}:{col}{R1}),{col}{R0}:{col}{R1},0))", kind="formula", fill=F_OUT, wrap=True)
ws.row_dimensions[rr].height = 56
rr += 1
put(ws, f"A{rr}", "Dynamic (60% follow) vs a fixed 40% share at the SAME 60% compliance: minutes saved", bold=True)
dyn = next(R0 + i for i, p in enumerate(D["robust"]) if p.startswith("Dynamic: Smart Scan screens (60%"))
st60 = next(R0 + i for i, p in enumerate(D["robust"]) if "60% obey" in p)
for j in range(len(variants)):
    col = L(2 + j)
    put(ws, f"{col}{rr}", f"={col}{st60}-{col}{dyn}", kind="formula", fmt="+0.00;-0.00", fill=F_OUT)
COMP_ROW = rr

r = rr + 2
put(ws, f"A{r}", "7. Why 'department / year X eats at mess Y' does not work, and why the routing must be dynamic", bold=True)
pol = D["policies"]
fr, d40, d50, s60, dept, mit, dyn60, dyn100, today = (pol[k] for k in [
    "Static: freshers to Munch (25% of every department)", "Static: fixed 40% to Munch", "Static: fixed 50/50 split (equal stations)",
    "Static: 40% assigned to Munch, 60% obey", "Static: TAPMI + DOC/MICFE to Munch, rest to Central", "Static: MIT to Munch, rest to Central",
    "Dynamic: Smart Scan screens (60% follow)", "Dynamic: Smart Scan screens (everyone follows)", "Today: habit 80/20, no screens"])
rob = D["robust"]
WHY = [
    f"It has been tried. The messes first split students by year: freshers at Munch, seniors at Central. Simulated, that rule (freshers ≈ 25% of every "
    f"department, assumed) still leaves an average wait of {fr['wait']:.1f} min and {fr['long']:.0f} students waiting over 10 min, against "
    f"{today['wait']:.1f} min today: it moves too few students, and the wrong ones, because who you are does not tell you when the queue is long.",
    f"Department rules overload the other mess instead. Sending TAPMI and DOC/MICFE to Munch puts their whole 13:05 surge on Munch's two stations "
    f"(peak queue {dept['peak_q']['B']:.0f} at Munch); average wait {dept['wait']:.1f} min. On a day with no MIT labs it gives "
    f"{rob['Static: TAPMI + DOC/MICFE to Munch, rest to Central']['No MIT labs (MIT + SMI at 12:00)']['wait']:.1f} min, worse than doing nothing "
    f"({rob['Today: habit 80/20, no screens']['No MIT labs (MIT + SMI at 12:00)']['wait']:.1f}).",
    f"Demand moves with the timetable. The surge depends on which departments break when (lab days, TAPMI at 13:05), so the right split changes "
    f"from slot to slot and day to day. A fixed rule is right at one moment and wrong at the next; the screens re-decide every 5 seconds.",
    f"Food changes the answer. A run-out at one mess makes it the slow one for 10–30 minutes. A static rule keeps sending students there; the "
    f"dynamic rule treats a star-dish run-out as an outage and routes around it. With late refills, the fixed 50/50 split averages "
    f"{rob['Static: fixed 50/50 split (equal stations)']['Late refills (next batch never ready)']['wait']:.2f} min vs "
    f"{rob['Dynamic: Smart Scan screens (60% follow)']['Late refills (next batch never ready)']['wait']:.2f} with the screens.",
    f"A well-chosen fixed share only works if it is enforced. A fixed 40% to Munch, obeyed by everyone, averages {d40['wait']:.2f} min, similar to "
    f"the screens ({dyn60['wait']:.2f}). But it forces about {(d40['munch_share'] - (1 - SIM.habit_share['A'])) * LUNCH.expected_students:,.0f} "
    f"students a day to change mess, every day and in every slot, including when both messes are empty; doubles Munch's food demand "
    f"({d40['outages_B']:.1f} Munch stock-outs per lunch vs {dyn60['outages_B']:.1f}); and 40% was found by our own simulation sweep, with hindsight. "
    f"At the same 60% compliance as the screens it averages {s60['wait']:.2f} min, worse than the screens on every busy kind of day (row {COMP_ROW}).",
    f"The screens move fewer students for more benefit: about {dyn60['munch_share'] * LUNCH.expected_students - (1 - SIM.habit_share['A']) * LUNCH.expected_students:,.0f} "
    f"students walk over, only in the surges, and only when it saves at least {CFG.layout.min_saving_min:.0f} minutes after the walk. Nobody is "
    f"assigned; advice is a nudge, and students who ignore it still get the shortest wait available to them.",
]
for i, t in enumerate(WHY):
    put(ws, f"A{r + 1 + i}", f"{i + 1}. {t}", wrap=True)
    ws.merge_cells(f"A{r + 1 + i}:I{r + 1 + i}")
    ws.row_dimensions[r + 1 + i].height = 58
LB_LAST = r + len(WHY)

# per-slot comparison chart data
r = LB_LAST + 3
put(ws, f"A{r}", "8. Average wait by 10-min slot (both messes, weighted by students): today vs static rules vs dynamic", bold=True)
pick = ["Today: habit 80/20, no screens", "Static: freshers to Munch (25% of every department)", "Static: TAPMI + DOC/MICFE to Munch, rest to Central",
        "Static: 40% assigned to Munch, 60% obey", "Dynamic: Smart Scan screens (60% follow)"]
heads(ws, r + 1, 1, ["Slot"] + [rule_label(p) for p in pick], 56)
for b in range(18):
    rr = r + 2 + b
    put(ws, f"A{rr}", clock(b * 10))
    for j, p in enumerate(pick):
        ps = D["policies"][p]["per_slot"]
        nA, nB = ps["A"][b][1], ps["B"][b][1]
        v = (ps["A"][b][0] * nA + ps["B"][b][0] * nB) / (nA + nB) if nA + nB else 0
        put(ws, f"{L(2 + j)}{rr}", round(v, 2), kind="data", fmt="0.0")
ch = LineChart()
ch.title = "Average wait by slot (min)"
ch.y_axis.title = "Minutes"
ch.add_data(Reference(ws, min_col=2, max_col=1 + len(pick), min_row=r + 1, max_row=r + 19), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=r + 2, max_row=r + 19))
ch.height, ch.width = 9, 22
ws.add_chart(ch, f"A{r + 21}")

# =============================================================================
# Checks
# =============================================================================
CK = "Checks"
ws = sheet(CK, "Checks: every one should say OK", "Recalculate after changing inputs", [70, 16, 12])
heads(ws, 4, 1, ["Check", "Value", "Result"])
arr_today = "+".join(f"SUMPRODUCT(({q(SD)}!$A$5:$A${SD_LAST}=\"{WORLD['today']}\")*({q(SD)}!$B$5:$B${SD_LAST}=\"{MESS[m]}\")*"
                     f"({q(SD)}!$C$5:$C${SD_LAST}=\"{STAGE['visit']}\")*{q(SD)}!$E$5:$E${SD_LAST})*10" for m in MESS)
checks = [
    ("Simulated arrivals add up to the students per lunch (within 2%)", f"=({arr_today})/{REF['students']}", "=IF(ABS(B5-1)<0.02,\"OK\",\"CHECK\")", "0.0%"),
    ("No formula errors in Q1 Scanner", f"=SUMPRODUCT(--ISERROR({q(Q1.title)}!$A$4:$P${Q1_LAST}))", "=IF(B6=0,\"OK\",\"CHECK\")", "0"),
    ("No formula errors in Q2 Serving stations", f"=SUMPRODUCT(--ISERROR({q(Q2.title)}!$A$4:$P${Q2_LAST}))", "=IF(B7=0,\"OK\",\"CHECK\")", "0"),
    ("No formula errors in Q3 Seats & disposal", f"=SUMPRODUCT(--ISERROR({q(Q3)}!$A$4:$L${Q3_LAST}))", "=IF(B8=0,\"OK\",\"CHECK\")", "0"),
    ("No formula errors in Capacity", f"=SUMPRODUCT(--ISERROR({q(CP)}!$B$5:$C${CAP_LAST}))", "=IF(B9=0,\"OK\",\"CHECK\")", "0"),
    ("Little's Law over the whole lunch (today, Central): Σ people-minutes inside ≈ Σ arrivals × visit time",
     f"=SUMPRODUCT({q(SD)}!$I${ROW[('today', 'A', 'visit', 0)]}:$I${ROW[('today', 'A', 'visit', 17)]})/"
     f"SUMPRODUCT({q(SD)}!$E${ROW[('today', 'A', 'visit', 0)]}:$E${ROW[('today', 'A', 'visit', 17)]},{q(SD)}!$G${ROW[('today', 'A', 'visit', 0)]}:$G${ROW[('today', 'A', 'visit', 17)]})",
     "=IF(ABS(B10-1)<0.1,\"OK\",\"CHECK\")", "0.00"),
    ("Seats never the constraint: peak seat utilisation below 100% (both messes)", f"=MAX({q(CP)}!B{CROW['peakutil']},{q(CP)}!C{CROW['peakutil']})", "=IF(B11<1,\"OK\",\"CHECK\")", "0%"),
    ("Dynamic routing beats a fixed share at the same compliance on the average day", f"={q(LB)}!B{COMP_ROW}", "=IF(B12>0,\"OK\",\"CHECK\")", "0.00"),
]
for i, (lab, v, res, fmt) in enumerate(checks):
    put(ws, f"A{5 + i}", lab, wrap=True)
    put(ws, f"B{5 + i}", v, kind="auto", fmt=fmt)
    put(ws, f"C{5 + i}", res, kind="formula", bold=True)
CK_LAST = 4 + len(checks)
put(ws, f"A{CK_LAST + 2}", "All checks", bold=True)
put(ws, f"C{CK_LAST + 2}", f'=IF(COUNTIF(C5:C{CK_LAST},"OK")={len(checks)},"ALL OK","CHECK")', kind="formula", fill=F_OUT, bold=True)
note(ws, f"A{CK_LAST + 3}", "Over a whole lunch, Σ(time-average people inside × 10 min) = Σ(arrivals × visit time) exactly; the check allows 10% because students "
     "who arrive late in a slot spill their minutes into the next one and the run ends when the last student has a seat.", "C" + str(CK_LAST + 3), 44)

# =============================================================================
# Start Here (first tab)
# =============================================================================
ST = "Start Here"
ws = wb.create_sheet(ST, 0)
for i, w_ in enumerate([30, 100], start=1):
    ws.column_dimensions[L(i)].width = w_
ws["A1"] = "Queue, capacity and load balancing: Smart Mess (Central CT and Munch Mess)"
ws["A1"].font = Font(name=FONT, size=14, bold=True, color="FFFFFF")
ws["A1"].fill = ws["B1"].fill = F_TITLE
put(ws, "A2", "SIMULATED DATA ONLY. Nothing here is a measurement of a real lunch: every arrival, wait and queue comes from the Smart Mess simulator "
    f"({D['seeds']} simulated lunches per scenario) driven by the assumptions on the Assumptions tab.", bold=True, wrap=True)
ws.merge_cells("A2:B2")
ws.row_dimensions[2].height = 32
put(ws, "A4", "How to read the colours", bold=True)
legend = [("Blue text", "an input or simulated data you can change"), ("Yellow fill", "an assumption not yet measured"),
          ("Grey fill", "simulated data (pasted from python tools/queue_capacity_data.py)"), ("Black text", "a formula"),
          ("Green text", "a formula that pulls from another tab"), ("Green fill", "a key result")]
for i, (a, b) in enumerate(legend):
    put(ws, f"A{5 + i}", a)
    put(ws, f"B{5 + i}", b)
ws["A5"].font = Font(name=FONT, size=10, color=BLUE)
ws["A6"].fill = F_KEY
ws["A7"].fill = F_DATA
ws["A9"].font = Font(name=FONT, size=10, color=GREEN)
ws["A10"].fill = F_OUT
put(ws, "A12", "Tabs", bold=True)
TABS = [
    (AS, "Every assumption, with its status (measured / group estimate / assumed / calibrated)"),
    (VA, "Every queuing variable and formula; which model fits which process"),
    (SD, "The simulated data: per 10-minute slot, mess, process and scenario"),
    (Q1.title, "1. QUEUE MANAGEMENT: biometric scan as M/M/1; stability and Little's Law per slot"),
    (Q2.title, "1. QUEUE MANAGEMENT: serving stations as M/M/c (c = 2); stability and Little's Law per slot"),
    (Q3, "1. QUEUE MANAGEMENT: seats as M/G/c and disposal as M/G/∞"),
    (LL, "1. Little's Law on the whole visit: where the mess is steady and where it is filling or emptying"),
    (CP, "2. CAPACITY MANAGEMENT: seat turnover (900 / 492 seats), stage capacities, bottleneck, utilisation, efficiency"),
    (LB, "3. LOAD BALANCING: how Smart Scan routes students, when, and why fixed rules (freshers at Munch, seniors at Central) fail"),
    (CK, "Validation checks"),
]
for i, (t, d) in enumerate(TABS):
    c = put(ws, f"A{13 + i}", t)
    c.hyperlink = f"#{q(t)}!A1"
    c.font = Font(name=FONT, size=10, color="0563C1", underline="single")
    put(ws, f"B{13 + i}", d, wrap=True)
r = 14 + len(TABS)
put(ws, f"A{r}", "Key results (live)", bold=True)
KEY = [
    ("Serving-station utilisation at Central, worst slot today", f"={q(Q2.title)}!C5", "0%"),
    ("Slots where Central's stations are unstable (ρ ≥ 1), today → with screens", f"={q(Q2.title)}!D5&\" → \"&{q(Q2.title)}!D7", None),
    ("Bottleneck at both messes", f"={q(CP)}!B{CROW['bottle']}", None),
    ("Seat turnover time (min) and diners per seat per hour, Central", f"=TEXT({q(CP)}!B{CROW['turn']},\"0.0\")&\" min · \"&TEXT({q(CP)}!B{CROW['turns_h']},\"0.0\")&\" per hour\"", None),
    ("Peak seat utilisation: Central / Munch", f"=TEXT({q(CP)}!B{CROW['peakutil']},\"0%\")&\" / \"&TEXT({q(CP)}!C{CROW['peakutil']},\"0%\")", None),
    ("Average wait: today → fixed freshers rule → Smart Scan (min)",
     f"=TEXT({q(LB)}!B{P0},\"0.0\")&\" → \"&TEXT({q(LB)}!B{P0 + 1},\"0.0\")&\" → \"&TEXT({q(LB)}!B{P0 + pol_names.index('Dynamic: Smart Scan screens (60% follow)')},\"0.0\")", None),
    ("Checks", f"={q(CK)}!C{CK_LAST + 2}", None),
]
for i, (a, f, fmt) in enumerate(KEY):
    put(ws, f"A{r + 1 + i}", a, wrap=True)
    put(ws, f"B{r + 1 + i}", f, kind="link", fmt=fmt, fill=F_OUT)
    ws.row_dimensions[r + 1 + i].height = 28

for wsx in wb.worksheets:
    for row in wsx.iter_rows():
        for c in row:
            if c.value is not None and (c.font is None or c.font.name != FONT):
                c.font = Font(name=FONT, size=c.font.size or 10, bold=c.font.bold, italic=c.font.italic, color=c.font.color)
wb.save(OUT)
print("saved", OUT)
