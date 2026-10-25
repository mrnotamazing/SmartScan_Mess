"""Build docs/Final_Queue_Capacity_LoadBalancing.xlsx: queue management (M/M/1, M/M/c per process),
capacity management (seat turnover, bottleneck) and load balancing (dynamic vs static), all on
SIMULATED data.

    python tools/queue_capacity_data.py              # simulate -> results/queue_capacity.json
    python tools/build_queue_capacity_workbook.py    # -> docs/Final_Queue_Capacity_LoadBalancing.xlsx

Every number the sheets compute is a live formula on the Assumptions and Sim Data tabs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, Series
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from messq.config import load_config  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "docs" / "Final_Queue_Capacity_LoadBalancing.xlsx")
D = json.loads((ROOT / "results" / "queue_capacity.json").read_text())
CFG = load_config()
LUNCH = CFG.simulation.slot("lunch")
A_, B_ = CFG.mess("A"), CFG.mess("B")
SIM = CFG.simulation
SIM_PLATE = f"{SIM.plate_pickup_s[0]:.0f}–{SIM.plate_pickup_s[1]:.0f} s"
SIM_LINE = f"{SIM.food_line_s[0]:.0f}–{SIM.food_line_s[1]:.0f} s"
EAT_MEAN = sum(SIM.eat_min) / 2
TURN_T = EAT_MEAN + 0.2


FONT = "Aptos Narrow"
NAVY, ACCENT, INK, MUTED = "1F3864", "2F5597", "262626", "6B6B6B"
BLUE, GREEN, BLACK, GREY = "1F4E9C", "2E6B30", INK, MUTED      # inputs, cross-tab links, formulas, notes
F_HEAD = PatternFill("solid", fgColor="DCE3EE")
F_TITLE = PatternFill("solid", fgColor=NAVY)
F_KEY = PatternFill("solid", fgColor="FFF2CC")      # not measured yet
F_NOTE = PatternFill("solid", fgColor="F4F6FA")
F_OUT = PatternFill("solid", fgColor="E2EFDA")      # key result
F_DATA = PatternFill("solid", fgColor="F2F2F2")     # simulated data
F_BAD = PatternFill("solid", fgColor="F8D7DA")
F_WARN = PatternFill("solid", fgColor="FCE8C3")
HAIR = Side(style="thin", color="D9D9D9")
LINE = Border(bottom=HAIR)
HEADLINE = Border(bottom=Side(style="medium", color=NAVY))
NOTE_EDGE = Border(left=Side(style="thick", color=ACCENT))
BOX = LINE
WRAP = Alignment(wrap_text=True, vertical="top")
MID = Alignment(vertical="center")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
TAB_COLORS = {"guide": NAVY, "inputs": "7F7F7F", "queue": ACCENT, "capacity": "548235", "balance": "C55A11", "checks": "A5A5A5"}

wb = Workbook()
wb.remove(wb.active)


def sheet(name, title, sub, widths, group="queue"):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 100
    ws.sheet_properties.tabColor = TAB_COLORS[group]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[L(i)].width = w
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=18, bold=True, color="FFFFFF")
    ws["A1"].alignment = Alignment(vertical="center", indent=1)
    for c in range(1, len(widths) + 1):
        ws.cell(row=1, column=c).fill = F_TITLE
    ws.row_dimensions[1].height = 36
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, size=11, italic=True, color=MUTED)
    ws["A2"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 8
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    return ws


def put(ws, ref, v, kind="text", fmt=None, bold=False, fill=None, wrap=False, italic=False, size=11, color=None):
    c = ws[ref]
    c.value = v
    col = {"input": BLUE, "data": BLUE, "link": GREEN}.get(kind, BLACK)
    if kind == "auto":
        col = GREEN if isinstance(v, str) and "!" in v else BLACK
    if kind == "note":
        col = "404040"
    c.font = Font(name=FONT, size=size, bold=bold or kind == "head", italic=italic or kind == "note",
                  color=color or (NAVY if kind == "head" else col))
    c.alignment = MID
    if kind == "head":
        c.fill, c.alignment, c.border = F_HEAD, CENTER, HEADLINE
    if kind in ("input", "data", "link", "formula", "auto"):
        c.border = LINE
    if kind == "data":
        c.fill = F_DATA
    if kind == "note":
        c.fill, c.alignment, c.border = F_NOTE, Alignment(wrap_text=True, vertical="top", indent=1), NOTE_EDGE
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if wrap:
        c.alignment = WRAP
    return c


def section(ws, ref, text):
    c = put(ws, ref, text, bold=True, size=13, color=NAVY)
    ws.row_dimensions[c.row].height = 24
    return c


def note(ws, ref, text, span_to=None, height=None, label="Takeaway"):
    put(ws, ref, f"{label}: {text}" if label else text, kind="note")
    if span_to:
        ws.merge_cells(f"{ref}:{span_to}")
        top, bottom = ws[ref].row, ws[span_to].row
        for rr in range(top, bottom + 1):
            ws.cell(row=rr, column=ws[ref].column).border = NOTE_EDGE
    if height:
        ws.row_dimensions[ws[ref].row].height = height


def heads(ws, row, col, names, height=None):
    for j, h in enumerate(names):
        put(ws, f"{L(col + j)}{row}", h, kind="head")


def _rich(sz=900, b=False):
    from openpyxl.chart.text import RichText
    from openpyxl.drawing.text import CharacterProperties, Font as DFont, Paragraph, ParagraphProperties
    return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(latin=DFont(typeface=FONT), sz=sz, b=b)),
                                 endParaRPr=CharacterProperties())])


def _title(text, sz=1200):
    from openpyxl.chart.text import RichText, Text
    from openpyxl.chart.title import Title
    from openpyxl.drawing.text import CharacterProperties, Font as DFont, Paragraph, ParagraphProperties, RegularTextRun
    cp = CharacterProperties(latin=DFont(typeface=FONT), sz=sz, b=True, solidFill=NAVY)
    return Title(tx=Text(rich=RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=cp), r=[RegularTextRun(rPr=cp, t=text)])])), overlay=False)


def style_chart(ch, title, y_title=None, colors=None):
    """Aptos Narrow text, visible axes, legend below, a muted palette."""
    ch.title = _title(title)
    if y_title:
        ch.y_axis.title = _title(y_title, 1000)
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.x_axis.txPr = _rich()
    ch.y_axis.txPr = _rich()
    if ch.legend is not None:
        ch.legend.position = "b"
        ch.legend.txPr = _rich()
    palette = colors or [ACCENT, "C55A11", "9DC3E6", "F4B183", "A5A5A5", "548235"]
    for k, sr in enumerate(ch.series):
        col = palette[k % len(palette)]
        if isinstance(ch, LineChart):
            sr.graphicalProperties.line.solidFill = col
            sr.graphicalProperties.line.width = 22000
            sr.smooth = False
        else:
            sr.graphicalProperties.solidFill = col
            sr.graphicalProperties.line.solidFill = col
    return ch


def fit_rows(ws, skip=(1, 2, 3)):
    """Row heights from the wrapped text they hold (Aptos Narrow 11: ~1.25 characters per width unit)."""
    merged = {}
    for rng in ws.merged_cells.ranges:
        w = sum(ws.column_dimensions[L(c)].width or 9 for c in range(rng.min_col, rng.max_col + 1))
        merged[(rng.min_row, rng.min_col)] = (w, rng.max_row - rng.min_row + 1)
    need = {}
    for row in ws.iter_rows():
        for c in row:
            if c.row in skip or c.value is None or not isinstance(c.value, str) or c.value.startswith("="):
                continue
            al = c.alignment
            w, span = merged.get((c.row, c.column), (ws.column_dimensions[L(c.column)].width or 9, 1))
            size = (c.font.size or 11) if c.font else 11
            per = max(4, w * 1.0 * 11 / size)
            if al is not None and al.wrap_text:
                lines = sum(max(1, -(-len(part) // int(per))) for part in c.value.split("\n"))
            else:
                lines = 1
            h = lines * size * 1.45 + 6
            need[c.row] = max(need.get(c.row, 0), h / span)
    for r_, h in need.items():
        ws.row_dimensions[r_].height = max(18, min(409, h))


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
ws = sheet(AS, "Assumptions", "Every input behind the simulated lunches, and where it comes from. Blue = input; shaded yellow = not measured yet.",
           [60, 12, 14, 16, 66], group="inputs")
heads(ws, 4, 1, ["Assumption", "Value", "Unit", "Status", "Source / note"])
ROWS = [
    ("sec", "Demand"),
    ("students", "Students per lunch (both messes)", LUNCH.expected_students, "students", "Measured", "Plates served (Phase 1)", "#,##0"),
    ("hA", "Share who eat at Central by habit (no screens)", round(SIM.habit_share["A"], 3), "share", "Measured", "Group: ~2,360 Central, ~600 Munch", "0.0%"),
    ("window", "Lunch window", LUNCH.duration_min, "minutes", "Measured", "11:30–14:30", "0"),
    ("visit_lo", "Total time in the mess: low (quiet)", 17, "minutes", "Group estimate", "Group: 17–35 min door to leaving, depending on the rush", "0"),
    ("visit_hi", "Total time in the mess: high (rush)", 35, "minutes", "Group estimate", "As above", "0"),
    ("lag_m", "Arrival lag after a department's lunch break starts: mean", LUNCH.lag_mean_min, "minutes", "Calibrated",
     "Fits the 17–35 min visit and ~15 min peak delay; department breaks from the group's timetable", "0"),
    ("lag_sd", "Arrival lag: spread", LUNCH.lag_sd_min, "minutes", "Calibrated", "As above", "0"),
    ("sec", "Stage 1 · Scan & collect plate (30–45 s)"),
    ("scanners", "Face scanners per mess", A_.scanners, "scanners", "Measured", "Group observation", "0"),
    ("scan_s", "Time per face scan", A_.scan_time_s, "seconds", "Assumed", "Stopwatch at the scanner", "0.0"),
    ("plate", f"Collect a plate after the scan ({SIM_PLATE})", sum(SIM.plate_pickup_s) / 2, "seconds", "Group estimate", "Group: scan + plate takes 30–45 s", "0"),
    ("sec", "Stage 2 · Collect food (1–2 min, plus the queue)"),
    ("c", "Serving stations per mess", A_.counters, "stations", "Measured", "Group observation", "0"),
    ("mu", "Service rate per station", A_.service_rate_per_counter_per_min, "students/min", "Assumed", "≈6 s per student; stopwatch 20–30 students", "0.0"),
    ("cv", "Variability of serving time (coefficient of variation)", SIM.service_cv, "ratio", "Assumed", "1.0 would be exponential, as M/M/c assumes", "0.0"),
    ("line", f"Rest of food collection after the station ({SIM_LINE})", sum(SIM.food_line_s) / 2, "seconds", "Group estimate",
     "Group: collecting food takes 1–2 min without a queue (serving ≈ 6 s + the rest); the queue adds up to ~15 min in the rush", "0"),
    ("sec", "Stage 3 · Eat (14–18 min)"),
    ("seats_A", "Seats: Central CT", A_.seats, "seats", "Measured", "CT manager", "#,##0"),
    ("seats_B", "Seats: Munch Mess", B_.seats, "seats", "Measured", "CT manager", "#,##0"),
    ("eat_lo", "Eating time: low", SIM.eat_min[0], "minutes", "Group estimate", "Group: 14–18 min", "0"),
    ("eat_hi", "Eating time: high", SIM.eat_min[1], "minutes", "Group estimate", "As above", "0"),
    ("changeover", "Seat changeover (next diner sits after the last leaves)", 0.2, "minutes", "Assumed",
     "Students clear their own plate; no table cleaning delays between diners as such. Used only in the seat-turnover formulas "
     "(a small safety margin); the simulation frees a seat as soon as the diner gets up", "0.0"),
    ("sec", "Stage 4 · Dispose of plate (1–2 min)"),
    ("disp_lo", "Disposal: low", SIM.dispose_min[0], "minutes", "Group estimate", "Group: 2 min at most", "0.0"),
    ("disp_hi", "Disposal: high", SIM.dispose_min[1], "minutes", "Group estimate", "As above", "0.0"),
    ("sec", "Load balancing (door screens)"),
    ("comply", "Share who follow a screen's advice", SIM.compliance, "share", "Assumed", "Imaginary adoption rate to measure impact; the pilot measures the real one", "0%"),
    ("walk", "Walk between the two mess doors", CFG.layout.switch_walk_s / 60, "minutes", "Timed", "30 s", "0.0"),
    ("min_save", "Minimum saving before a screen suggests switching", CFG.layout.min_saving_min, "minutes", "Rule-based routing", "Our design choice", "0.0"),
    ("freshers", "Freshers as a share of every department (for the fixed freshers-at-Munch rule)", 0.25, "share", "Assumed",
     "First year of a four-year course; the messes first split students this way", "0%"),
    ("sec", "Capacity planning"),
    ("rho_t", "Target utilisation for planning capacity", 0.85, "share", "Policy",
     "Above ~85% waits climb steeply (Variables, Q2); used to size stations for the peak", "0%"),
    ("sec", "Simulation"),
    ("seeds", "Simulated lunches averaged per scenario", D["seeds"], "lunches", "Design", "Seeds 0–19; the same students in every scenario", "0"),
    ("slot", "Time-slot length in the tables", 10, "minutes", "Design", "18 slots from 11:30", "0"),
]
REF = {}
NUM_INPUTS = []
r = 5
for row in ROWS:
    if row[0] == "sec":
        if r > 5:
            r += 1
        section(ws, f"A{r}", row[1])
        r += 1
        continue
    key, label, val, unit, status, src, fmt = row
    put(ws, f"A{r}", label)
    c = put(ws, f"B{r}", val, kind="input", fmt=fmt)
    NUM_INPUTS.append(f"B{r}")
    if status in ("Assumed", "Group estimate", "Calibrated"):
        c.fill = F_KEY
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", status, bold=status == "Measured").alignment = Alignment(horizontal="center", vertical="center")
    put(ws, f"E{r}", src, wrap=True, italic=True, color=MUTED)
    for col in "ACDE":
        ws[f"{col}{r}"].border = LINE
    REF[key] = f"{q(AS)}!$B${r}"
    r += 1
r += 2
section(ws, f"A{r}", "Department lunch breaks (they shape the surge; sizes are rough, scaled to the plates served)")
r += 1
heads(ws, r, 1, ["Department", "Students (scaled)", "Break starts", "Break ends", "Status"])
for name, n, a, b in LUNCH.cohorts():
    r += 1
    put(ws, f"A{r}", name)
    put(ws, f"B{r}", round(n), kind="input", fmt="#,##0")
    put(ws, f"C{r}", clock(a), kind="input")
    put(ws, f"D{r}", clock(b), kind="input")
    put(ws, f"E{r}", "Timetable from the group" + ("; timing assumed" if name == "MIRM" else "") +
        ("; MIT eats here on lab days (45% assumed)" if "lab" in name else ""), italic=True, color=MUTED)
    for col in "AE":
        ws[f"{col}{r}"].border = LINE
ws.freeze_panes = "A5"
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402
_dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=False, showErrorMessage=True,
                     errorTitle="Numbers only", error="Type one plain number, e.g. 12 (not \"12-15\" or \"12 min\"). Ranges have separate low and high rows.")
ws.add_data_validation(_dv)
for ref in NUM_INPUTS:
    _dv.add(ref)
AS_NUM = " ".join(NUM_INPUTS)

# =============================================================================
# Sim Data (long format)
# =============================================================================
SD = "Sim Data"
ws = sheet(SD, "Simulated data", f"Average of {D['seeds']} simulated lunches per 10-minute slot, mess, process and scenario. Simulated, not measured.",
           [24, 14, 16, 10, 14, 16, 18, 18, 18, 20, 18, 16], group="inputs")
heads(ws, 4, 1, ["Scenario", "Mess", "Process", "Slot", "λ arrivals (/min)", "Wq simulated (min)", "Stage time Ws simulated (min)",
                 "Lq simulated (avg waiting)", "Ls simulated (avg in service)", "Rule wait, each lunch then averaged (min)",
                 "Rule line at end, each lunch then averaged", "Food out in the slot (min, stations idle)"], 44)
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
                for j, k in enumerate(["lam", "wq_min", "ws_min", "lq", "ls", "rule_wq_min", "rule_line_end", "out_min"]):
                    put(ws, f"{L(5 + j)}{r}", round(x.get(k, 0.0), 4), kind="data", fmt="0.00")
                ROW[(w, m, st, b)] = r
                r += 1
SD_LAST = r - 1
ws.auto_filter.ref = f"A4:L{SD_LAST}"
ws.freeze_panes = "E5"
r += 1
section(ws, f"A{r}", "Per mess, whole lunch")
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


def wavg_expr(w, m, st, col):
    """λ-weighted average of a Sim Data column over the lunch."""
    lam = f"{q(SD)}!$E${ROW[(w, m, st, 0)]}:$E${ROW[(w, m, st, 17)]}"
    x = f"{q(SD)}!${col}${ROW[(w, m, st, 0)]}:${col}${ROW[(w, m, st, 17)]}"
    return f"SUMPRODUCT({lam},{x})/SUM({lam})"


# =============================================================================
# Variables: every symbol, defined, with its value in a worked example
# =============================================================================
VA = "Variables"
ws = sheet(VA, "Variables", "What every symbol means, how it is calculated, and its value in a real slot of the simulated lunch",
           [12, 34, 58, 32, 11, 14, 30], group="guide")


def var_block(top, heading, rows, intro):
    """rows: (symbol, name, meaning, formula text, Excel formula, unit, number format)"""
    section(ws, f"A{top}", heading)
    put(ws, f"A{top + 1}", intro, italic=True, color=MUTED)
    ws.merge_cells(f"A{top + 1}:G{top + 1}")
    heads(ws, top + 2, 1, ["Symbol", "Name", "What it means at the mess", "Formula", "Value", "Unit", "Reads as"])
    refs = {}
    for i, (sym, name, meaning, ftext, f, unit, fmt) in enumerate(rows):
        r_ = top + 3 + i
        refs[sym] = f"E{r_}"
        put(ws, f"A{r_}", sym, bold=True, color=NAVY).border = LINE
        put(ws, f"B{r_}", name).border = LINE
        put(ws, f"C{r_}", meaning, wrap=True).border = LINE
        put(ws, f"D{r_}", ftext, italic=True).border = LINE
        f = f.format(**refs) if isinstance(f, str) else f
        put(ws, f"E{r_}", f, kind="auto", fmt=fmt, fill=F_OUT, bold=True)
        put(ws, f"F{r_}", unit).border = LINE
        tf = fmt if fmt and fmt not in ("@",) else "0.00"
        put(ws, f"G{r_}", f'=A{r_}&" = "&IF(ISNUMBER(E{r_}),TEXT(E{r_},"{tf}"),E{r_})&IF(F{r_}="",""," "&F{r_})', kind="formula").border = LINE
    return top + 3 + len(rows)


ex1 = 4  # 12:10 slot (slot 0 = 11:30)
r = var_block(4, "1. Serving stations at Central, 12:10–12:20 today (M/M/c, stable)", [
    ("λ", "Arrival rate", "Students joining Central's serving line per minute in this slot", "counted in the simulation", f"={sd('today', 'A', 'station', ex1, 'E')}", "students/min", "0.0"),
    ("Ws", "Service time", "Average time one student spends being served at a station", "measured in the simulation", f"={sd('today', 'A', 'station', ex1, 'G')}", "min", "0.00"),
    ("μ", "Service rate per station", "Students one station can serve per minute", "μ = 1 ÷ Ws", "=1/{Ws}", "students/min", "0.0"),
    ("c", "Servers", "Serving stations at Central", "measured", f"={REF['c']}", "stations", "0"),
    ("a", "Offered load", "Work arriving, in 'stations' worth of serving", "a = λ ÷ μ", "={λ}/{μ}", "stations", "0.00"),
    ("ρ", "Utilisation", "Share of the time each station is busy", "ρ = λ ÷ (c·μ)", "={λ}/({c}*{μ})", "", "0%"),
    ("Stable?", "Stability test", "Can the stations keep up, so the line settles to a steady size?", "stable if ρ < 1", '=IF({ρ}<1,"yes","no")', "", "@"),
    ("P0", "Probability empty", "Chance nobody is waiting or being served", "[Σ aᵏ/k! (k < c) + aᶜ/(c!(1−ρ))]⁻¹",
     "=1/(SUMPRODUCT(--({{0,1,2,3,4,5,6,7,8,9}}<{c}),{a}^{{0,1,2,3,4,5,6,7,8,9}}/FACT({{0,1,2,3,4,5,6,7,8,9}}))+{a}^{c}/FACT({c})/(1-{ρ}))", "", "0.000"),
    ("C", "Probability of waiting (Erlang C)", "Chance an arriving student has to wait at all", "C = aᶜ/(c!(1−ρ)) × P0", "={a}^{c}/FACT({c})/(1-{ρ})*{P0}", "", "0%"),
    ("Wq", "Wait in the line", "Average minutes from joining the line to reaching a station", "Wq = C ÷ (c·μ − λ)", "={C}/({c}*{μ}-{λ})", "min", "0.00"),
    ("Wq cv", "Wait, corrected for regular serving", "Serving times vary less than M/M/c assumes (cv 0.6), so the real wait is shorter. "
     "Allen–Cunneen approximation for M/G/c (exact only for one server, where it is Pollaczek–Khinchine)", "Wq × (1 + cv²) ÷ 2",
     f"={{Wq}}*(1+{REF['cv']}^2)/2", "min", "0.00"),
    ("W", "Time at the stage", "Wait plus being served", "W = Wq + Ws", "={Wq}+{Ws}", "min", "0.00"),
    ("Lq", "Students in the line", "Average number standing in the line", "Lq = λ × Wq (Little's Law)", "={λ}*{Wq}", "students", "0.0"),
    ("Ls", "Students being served", "Average number at the stations", "Ls = λ × Ws", "={λ}*{Ws}", "students", "0.0"),
    ("L", "Students at the stage", "Everyone at the serving stage", "L = λ × W (Little's Law)", "={λ}*{W}", "students", "0.0"),
    ("Wq sim", "Simulated wait", "What the simulated students actually waited", "from the simulation", f"={sd('today', 'A', 'station', ex1, 'F')}", "min", "0.00"),
    ("Lq sim", "Simulated line length", "Average number the simulation had waiting", "from the simulation", f"={sd('today', 'A', 'station', ex1, 'H')}", "students", "0.0"),
    ("Little", "Little's Law check", "Simulated line length ÷ (λ × simulated wait). Close to 1 means steady", "Lq sim ÷ (λ × Wq sim)", "={Lq sim}/({λ}*{Wq sim})", "", "0.00"),
], "A worked example: every symbol below is calculated live from the simulated 12:10 slot, the first busy slot of the lunch.")
ex2 = 10  # 13:10
r = var_block(r + 1, "2. Serving stations at Central, 13:10–13:20 today (overloaded)", [
    ("λ", "Arrival rate", "Students joining Central's line per minute at the 13:10 surge", "counted in the simulation", f"={sd('today', 'A', 'station', ex2, 'E')}", "students/min", "0.0"),
    ("c·μ", "Capacity", "Most the two stations can serve per minute", "c × μ", f"={REF['c']}*{REF['mu']}", "students/min", "0.0"),
    ("ρ", "Utilisation", "Above 100% the stations cannot keep up", "ρ = λ ÷ (c·μ)", "={λ}/{c·μ}", "", "0%"),
    ("Growth", "Line growth", "Extra students added to the line during these 10 minutes", "(λ − c·μ) × 10", "=MAX(0,({λ}-{c·μ})*10)", "students", "0"),
    ("Wq", "Steady-state wait", "Not defined: with ρ ≥ 1 the line has no steady size", "only if ρ < 1", '=IF({ρ}<1,"defined","none (ρ ≥ 1)")', "", "@"),
    ("B start", "Line at the start", "Students still in line when the slot begins (carried in from 13:00–13:10)", "fluid queue, previous slot",
     f"={q('Q2 Serving stations')}!$P${28 + ex2}", "students", "0"),
    ("Out", "Minutes food was out", "Minutes in this slot the stations stood idle waiting for a refill (average lunch)", "from the simulation",
     f"={sd('today', 'A', 'station', ex2, 'L')}", "min", "0.0"),
    ("B end", "Line at the end", "Line at the start + arrivals − what the stations could serve while food was available (never below zero)",
     "B start + λ × 10 − c·μ × (10 − Out)", "=MAX(0,{B start}+{λ}*10-{c·μ}*(10-{Out}))", "students", "0"),
    ("W line", "Wait from the line", "Someone joining half-way through the slot meets the average line, cleared at c·μ a minute",
     "(B start + B end) ÷ 2 ÷ c·μ", "=({B start}+{B end})/2/{c·μ}", "min", "0.0"),
    ("Wq sim", "Simulated wait", "What the simulated students who joined in this slot actually waited", "from the simulation",
     f"={sd('today', 'A', 'station', ex2, 'F')}", "min", "0.0"),
], "When ρ ≥ 1 the textbook formulas stop applying: the line grows every minute until arrivals fall. Then the serving-capacity rule (a fluid "
   "queue) takes over: carry the line from slot to slot and divide it by what the stations serve per minute.")
ex3 = 10
r = var_block(r + 1, "3. Biometric scanner at Central, 13:10–13:20 today (M/M/1)", [
    ("λ", "Arrival rate", "Students reaching the face scanner per minute", "counted in the simulation", f"={sd('today', 'A', 'scanner', ex3, 'E')}", "students/min", "0.0"),
    ("μ", "Scan rate", "Students one scanner can handle per minute", "μ = 60 ÷ seconds per scan", f"=60/{REF['scan_s']}", "students/min", "0.0"),
    ("ρ", "Utilisation", "Share of the time the scanner is busy", "ρ = λ ÷ μ", "={λ}/{μ}", "", "0%"),
    ("Wq", "Wait (M/M/1)", "Textbook wait outside the door", "Wq = ρ ÷ (μ − λ)", '=IF({ρ}<1,{ρ}/({μ}-{λ}),"none (ρ ≥ 1)")', "min", "0.00"),
    ("cv", "Scan-time variability", "Real scans are regular, unlike the exponential times M/M/1 assumes", "assumed", 0.3, "", "0.0"),
    ("Wq M/G/1", "Corrected wait", "Pollaczek–Khinchine correction for regular service", "Wq × (1 + cv²) ÷ 2", '=IF(ISNUMBER({Wq}),{Wq}*(1+{cv}^2)/2,"none")', "min", "0.00"),
    ("Wq sim", "Simulated wait", "What the simulated students waited at the scanner", "from the simulation", f"={sd('today', 'A', 'scanner', ex3, 'F')}", "min", "0.00"),
], "One scanner per mess: the simplest queue, a single server.")
r = var_block(r + 1, "4. Seats at Munch Mess (capacity)", [
    ("N", "Seats", "Seats at Munch Mess", "measured", f"={REF['seats_B']}", "seats", "0"),
    ("T", "Seat turnover time", "Minutes one diner holds a seat, plus changeover", "eating time + changeover", f"=({REF['eat_lo']}+{REF['eat_hi']})/2+{REF['changeover']}", "min", "0.0"),
    ("Turns", "Turnover rate", "Diners one seat serves per hour", "60 ÷ T", "=60/{T}", "per hour", "0.0"),
    ("λmax", "Seating capacity", "Most students per minute the seats can take (Little's Law rearranged)", "λmax = N ÷ T", "={N}/{T}", "students/min", "0.0"),
], "Little's Law also measures capacity: the seats can absorb N ÷ T students a minute.")
r += 1
section(ws, f"A{r}", "Which model fits which process")
heads(ws, r + 1, 1, ["Process", "Model", "Why", "", "", "", "Tab"])
MAP = [
    ("Biometric scan", "M/M/1", "One scanner per mess; students queue outside the door. Scans are regular, so the M/G/1 correction is closer", "Q1 Scanner"),
    ("Serving stations", "M/M/c, c = 2", "Two stations fed from one line; this is where the queue forms", "Q2 Serving stations"),
    ("Seats", "M/G/c, c = seats", "Each seat is a server and a meal is its service; with 900 and 492 seats nobody waits", "Q3 Seats & disposal"),
    ("Disposal", "M/G/∞", "Several bins and no waiting, so only L = λ × W applies", "Q3 Seats & disposal"),
    ("Whole visit", "Little's Law", "People inside = arrivals per minute × minutes inside", "Littles Law"),
]
for i, (a_, b_, c_, t_) in enumerate(MAP):
    rr = r + 2 + i
    put(ws, f"A{rr}", a_, bold=True).border = LINE
    put(ws, f"B{rr}", b_).border = LINE
    put(ws, f"C{rr}", c_, wrap=True).border = LINE
    ws.merge_cells(f"C{rr}:F{rr}")
    c = put(ws, f"G{rr}", t_)
    c.hyperlink = f"#{q(t_)}!A1"
    c.font = Font(name=FONT, size=11, color=ACCENT, underline="single")


# =============================================================================
# Queue tabs
# =============================================================================
def queue_tab(name, title, stage, c_ref, model, summary_note):
    ws = sheet(name, title, f"{model}. Arrivals, waits and line lengths are simulated; utilisation, stability, the textbook waits and the line carried "
               "between slots (fluid queue) are formulas.",
               [24, 13, 8, 10, 11, 10, 7, 9, 22, 12, 13, 12, 11, 11, 13, 11, 11, 12, 12, 13, 40])
    # ---- summary (rows 4-9) and takeaway
    section(ws, "A4", "Summary")
    heads(ws, 5, 1, ["Scenario", "Mess", "Peak ρ", "Slots over", "Slots near", "Worst wait", "Avg wait (simulated)", "Avg: formula on the average day",
                     "Avg: rule lunch by lunch"])
    put(ws, "A10", "Slots over = ρ ≥ 100% · slots near = 85–100% · worst and average wait are simulated · formula on the average day = column S "
        "(line carried between slots + randomness) · rule lunch by lunch = the serving-capacity rule on each simulated lunch, then averaged "
        "(column T) · all λ-weighted, in minutes", italic=True, color=MUTED, size=10)
    top = 27
    cvname = "Wq M/G/1, Pollaczek–Khinchine (min)" if model.startswith("M/M/1") else "Wq M/G/c, Allen–Cunneen (min)"
    cols = ["Scenario", "Mess", "Slot", "λ (/min)", "Service time (min)", "μ (/min)", "c", "ρ", "Stable?", "Wq textbook (min)",
            cvname, "Wq simulated (min)", "Lq simulated", "λ × Wq simulated", "Little's Law: Lq ÷ λWq",
            "Line at start (carried in)", "Line at end = start + λ×10 − cμ×(10 − minutes food out)", "Wait from the line (min)", "Best estimate, average day (min)",
            "Rule, each lunch then averaged (min)", "What it means"]
    section(ws, f"A{top - 1}", "Slot by slot (filter by scenario or mess)")
    heads(ws, top, 1, cols)
    rows = []
    r = top + 1
    for w in WORLD:
        for m in MESS:
            for b in range(18):
                put(ws, f"A{r}", WORLD[w]).border = LINE
                put(ws, f"B{r}", MESS[m]).border = LINE
                put(ws, f"C{r}", clock(b * 10)).border = LINE
                put(ws, f"D{r}", f"={sd(w, m, stage, b, 'E')}", kind="link", fmt="0.0")
                put(ws, f"E{r}", f"={sd(w, m, stage, b, 'G')}", kind="link", fmt="0.000")
                put(ws, f"F{r}", f"=IF(E{r}>0,1/E{r},{DEFAULT_MU[stage]})", kind="formula", fmt="0.0")
                put(ws, f"G{r}", f"={c_ref(m)}", kind="link", fmt="0")
                put(ws, f"H{r}", f"=D{r}/(G{r}*F{r})", kind="formula", fmt="0%")
                put(ws, f"I{r}", f'=IF(D{r}=0,"no arrivals",IF(H{r}<0.85,"stable",IF(H{r}<1,"near capacity","over capacity")))', kind="formula")
                a = f"(D{r}/F{r})"
                K = "{0,1,2,3,4,5,6,7,8,9}"
                if model.startswith("M/M/1"):
                    wq = f"=IF(AND(D{r}>0,H{r}<1),H{r}/(F{r}-D{r}),\"—\")"
                else:
                    top_ = f"({a}^G{r}/FACT(G{r})/(1-H{r}))"
                    wq = (f"=IF(AND(D{r}>0,H{r}<1),{top_}/(SUMPRODUCT(--({K}<G{r}),{a}^{K}/FACT({K}))+{top_})/(G{r}*F{r}-D{r}),\"—\")")
                put(ws, f"J{r}", wq, kind="formula", fmt="0.00")
                put(ws, f"K{r}", f'=IF(ISNUMBER(J{r}),(1+{CV[stage]}^2)/2*J{r},"—")', kind="formula", fmt="0.00")
                put(ws, f"L{r}", f"={sd(w, m, stage, b, 'F')}", kind="link", fmt="0.00")
                put(ws, f"M{r}", f"={sd(w, m, stage, b, 'H')}", kind="link", fmt="0.0")
                put(ws, f"N{r}", f"=D{r}*L{r}", kind="formula", fmt="0.0")
                put(ws, f"O{r}", f'=IF(MAX(M{r},N{r})<0.5,"both ≈ 0",IF(N{r}=0,"no new arrivals",M{r}/N{r}))', kind="formula", fmt="0.00")
                # Fluid queue (the serving-capacity rule): the line is carried from one slot to the next.
                put(ws, f"P{r}", "=0" if b == 0 else f"=Q{r - 1}", kind="formula", fmt="0")
                # capacity this slot = stations × rate × minutes the food was available (effective capacity)
                put(ws, f"Q{r}", f"=MAX(0,P{r}+D{r}*{REF['slot']}-G{r}*F{r}*({REF['slot']}-{sd(w, m, stage, b, 'L')}))", kind="formula", fmt="0")
                put(ws, f"R{r}", f"=(P{r}+Q{r})/2/(G{r}*F{r})", kind="formula", fmt="0.00")
                # Best estimate = wait from the line + the random part (textbook wait with ρ capped at 95%, corrected for cv).
                lc = f"MIN(D{r},0.95*G{r}*F{r})"
                if model.startswith("M/M/1"):
                    rnd = f"({lc}/F{r})/(F{r}-{lc})"
                else:
                    ac = f"({lc}/F{r})"
                    tc = f"({ac}^G{r}/FACT(G{r})/(1-{lc}/(G{r}*F{r})))"
                    rnd = f"{tc}/(SUMPRODUCT(--({K}<G{r}),{ac}^{K}/FACT({K}))+{tc})/(G{r}*F{r}-{lc})"
                put(ws, f"S{r}", f"=IF(D{r}>0,R{r}+(1+{CV[stage]}^2)/2*{rnd},0)", kind="formula", fmt="0.00")
                put(ws, f"T{r}", f"={sd(w, m, stage, b, 'J')}", kind="link", fmt="0.00")
                put(ws, f"U{r}", f'=IF(D{r}=0,IF(P{r}>0,"No new arrivals: the line left from earlier drains",""),IF(H{r}>=1,"Over capacity: the line grows by about "&TEXT((D{r}-G{r}*F{r})*10,"0")&" in 10 min (to "&TEXT(Q{r},"0")&")",'
                                 f'IF(P{r}>=1,"Under capacity, but "&TEXT(P{r},"0")&" were already in line: it drains to "&TEXT(Q{r},"0"),IF(ISNUMBER(O{r}),IF(ABS(O{r}-1)<=0.2,"Steady: Little\'s Law holds",'
                                 f'IF(O{r}>1,"Draining a line left from earlier","Line still building")),"Hardly any line"))))',
                    kind="formula")
                for col in "CDEFGHIJKLMNOPQRST":
                    ws[f"{col}{r}"].alignment = Alignment(horizontal="center", vertical="center")
                rows.append((w, m, b, r))
                r += 1
    last = r - 1
    ws.auto_filter.ref = f"A{top}:U{last}"
    ws.freeze_panes = f"D{top + 1}"
    ws.conditional_formatting.add(f"H{top + 1}:I{last}", FormulaRule(formula=[f"$H{top + 1}>=1"], fill=F_BAD, font=Font(name=FONT, color="9C0006", bold=True)))
    ws.conditional_formatting.add(f"H{top + 1}:I{last}", FormulaRule(formula=[f"AND($H{top + 1}>=0.85,$H{top + 1}<1)"], fill=F_WARN))
    rng = lambda col: f"${col}${top + 1}:${col}${last}"  # noqa: E731
    for k, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
        rr = 6 + k
        crit = f'{rng("A")},"{WORLD[w]}",{rng("B")},"{MESS[m]}"'
        put(ws, f"A{rr}", WORLD[w]).border = LINE
        put(ws, f"B{rr}", MESS[m]).border = LINE
        put(ws, f"C{rr}", f"=_xlfn.MAXIFS({rng('H')},{crit})", kind="formula", fmt="0%", fill=F_OUT, bold=True)
        put(ws, f"D{rr}", f'=COUNTIFS({crit},{rng("H")},">=1")', kind="formula", fmt="0", fill=F_OUT, bold=True)
        put(ws, f"E{rr}", f'=COUNTIFS({crit},{rng("H")},">=0.85",{rng("H")},"<1")', kind="formula", fmt="0")
        put(ws, f"F{rr}", f"=_xlfn.MAXIFS({rng('L')},{crit})", kind="formula", fmt="0.00")
        put(ws, f"G{rr}", f"=SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('L')}*{rng('D')})/"
                          f"SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('D')})", kind="formula", fmt="0.00")
        put(ws, f"H{rr}", f"=SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('S')}*{rng('D')})/"
                          f"SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('D')})", kind="formula", fmt="0.00", fill=F_OUT, bold=True)
        put(ws, f"I{rr}", f"=SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('T')}*{rng('D')})/"
                          f"SUMPRODUCT(({rng('A')}=\"{WORLD[w]}\")*({rng('B')}=\"{MESS[m]}\")*{rng('D')})", kind="formula", fmt="0.00", fill=F_OUT, bold=True)
        for col in "CDEFGHI":
            ws[f"{col}{rr}"].alignment = Alignment(horizontal="center", vertical="center")
    note(ws, "A12", summary_note, "G18")
    put(ws, "A20", "In the table below: red = over capacity (the line keeps growing), amber = near capacity (waits rise steeply).", italic=True, color=MUTED, size=10)
    # ---- chart data (below the table) and chart (beside the summary)
    cr = last + 3
    section(ws, f"A{cr}", "Utilisation by slot (chart data)")
    heads(ws, cr + 1, 1, ["Slot"] + [f"{MESS[m]}, {'today' if w == 'today' else 'with screens'}" for w in WORLD for m in MESS] + ["Capacity (ρ = 100%)"])
    for b in range(18):
        rr = cr + 2 + b
        put(ws, f"A{rr}", clock(b * 10)).border = LINE
        for j, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
            src = next(rw for ww, mm, bb, rw in rows if ww == w and mm == m and bb == b)
            put(ws, f"{L(2 + j)}{rr}", f"=H{src}", kind="formula", fmt="0%")
        put(ws, f"F{rr}", 1, fmt="0%").border = LINE
    ch = LineChart()
    ch.add_data(Reference(ws, min_col=2, max_col=6, min_row=cr + 1, max_row=cr + 19), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=cr + 2, max_row=cr + 19))
    ch.y_axis.number_format = "0%"
    ch.height, ch.width = 9.5, 19
    style_chart(ch, f"{title.split(':')[0]}: utilisation per 10-minute slot", "Utilisation ρ",
                colors=["C55A11", "F4B183", ACCENT, "9DC3E6", "7F7F7F"])
    ch.series[-1].graphicalProperties.line.dashStyle = "dash"
    ws.add_chart(ch, "I4")
    return ws, rows, top, last


DEFAULT_MU = {"scanner": f"60/{REF['scan_s']}", "station": REF["mu"]}
CV = {"scanner": "0.3", "station": REF["cv"]}
def _peak_rho(w, m, stage, c):
    return max(x["lam"] * x["ws_min"] / c for x in D["worlds"][w][m][stage])


_sA = _peak_rho("today", "A", "scanner", 1)
Q1, Q1_ROWS, Q1_TOP, Q1_LAST = queue_tab(
    "Q1 Scanner", "Biometric scan: M/M/1", "scanner", lambda m: REF["scanners"], "M/M/1, one face scanner per mess",
    f"One scanner per mess handles about 30 students a minute. It keeps up all lunch, though Central's scanner gets close (about {_sA:.0%} busy) "
    "in the 13:10 surge. The textbook M/M/1 wait assumes the surge lasts long enough for the queue to settle; a 10-minute surge never gets "
    "there, so the formula overstates the wait (about 1.2 min corrected vs 0.3 min simulated at 13:10). Anyone queueing here is still outside "
    "the door, so the live system cannot see them.")
_pA, _pAs, _pBs = _peak_rho("today", "A", "station", 2), _peak_rho("screens", "A", "station", 2), _peak_rho("screens", "B", "station", 2)
Q2, Q2_ROWS, Q2_TOP, Q2_LAST = queue_tab(
    "Q2 Serving stations", "Serving stations: M/M/c", "station", lambda m: REF["c"], "M/M/c, two serving stations per mess",
    f"This is the bottleneck. Two stations serve 20 students a minute. Today Central runs at up to {_pA:.0%} in the 13:10 surge, so the line "
    f"grows every minute and there is no steady state until the surge passes. With the screens Central peaks at {_pAs:.0%} for a short while "
    f"and Munch takes the overflow (peak {_pBs:.0%}). The screens only ask students to walk when it saves at least 2 minutes, and only 60% follow. "
    "Per-slot textbook waits miss the line carried over from an overloaded slot (after 13:30 Central is under 100% again but ~200 are still "
    "waiting), so the best-estimate column adds the line from the serving-capacity rule: line ÷ 20 per minute.")


# =============================================================================
# Q3 Seats & disposal
# =============================================================================
Q3 = "Q3 Seats & disposal"
ws = sheet(Q3, "Seats and disposal", "Each seat is a server and one meal is its service (M/G/c with c = seats); disposal never queues (M/G/∞).",
           [24, 13, 8, 12, 12, 9, 11, 22, 13, 13, 13, 18])
section(ws, "A4", "Summary")
heads(ws, 5, 1, ["Scenario", "Mess", "Peak seat ρ", "Peak seats in use", "Seats", "Average eating time (min)"])
TOP3 = 20
section(ws, f"A{TOP3 - 1}", "Slot by slot")
heads(ws, TOP3, 1, ["Scenario", "Mess", "Slot", "λ sitting down (/min)", "Eating time W (min)", "Seats c", "ρ = λW ÷ c", "Stable?",
                    "Seats in use (simulated)", "Seats in use (λ × W)", "Little's Law ratio", "People at the bins (λ × W)"])
r = TOP3 + 1
for w in WORLD:
    for m in MESS:
        seats = REF["seats_A"] if m == "A" else REF["seats_B"]
        for b in range(18):
            put(ws, f"A{r}", WORLD[w]).border = LINE
            put(ws, f"B{r}", MESS[m]).border = LINE
            put(ws, f"C{r}", clock(b * 10)).border = LINE
            put(ws, f"D{r}", f"={sd(w, m, 'seat', b, 'E')}", kind="link", fmt="0.0")
            put(ws, f"E{r}", f"=IF({sd(w, m, 'seat', b, 'G')}>0,{sd(w, m, 'seat', b, 'G')},({REF['eat_lo']}+{REF['eat_hi']})/2)", kind="link", fmt="0.0")
            put(ws, f"F{r}", f"={seats}", kind="link", fmt="#,##0")
            put(ws, f"G{r}", f"=D{r}*E{r}/F{r}", kind="formula", fmt="0%")
            put(ws, f"H{r}", f'=IF(D{r}=0,"no arrivals",IF(G{r}<1,"stable: seats free","over capacity"))', kind="formula")
            put(ws, f"I{r}", f"={sd(w, m, 'seat', b, 'I')}", kind="link", fmt="0")
            put(ws, f"J{r}", f"=D{r}*E{r}", kind="formula", fmt="0")
            put(ws, f"K{r}", f'=IF(MAX(I{r},J{r})<5,"≈ 0",IF(J{r}=0,"no new diners",I{r}/J{r}))', kind="formula", fmt="0.00")
            put(ws, f"L{r}", f"={sd(w, m, 'disposal', b, 'E')}*{sd(w, m, 'disposal', b, 'G')}", kind="link", fmt="0.0")
            for col in "CDEFGHIJKL":
                ws[f"{col}{r}"].alignment = Alignment(horizontal="center", vertical="center")
            r += 1
Q3_LAST = r - 1
ws.auto_filter.ref = f"A{TOP3}:L{Q3_LAST}"
ws.freeze_panes = f"D{TOP3 + 1}"
rg = lambda col: f"${col}${TOP3 + 1}:${col}${Q3_LAST}"  # noqa: E731
for k, (w, m) in enumerate([(w, m) for w in WORLD for m in MESS]):
    rr = 6 + k
    crit = f'{rg("A")},"{WORLD[w]}",{rg("B")},"{MESS[m]}"'
    put(ws, f"A{rr}", WORLD[w]).border = LINE
    put(ws, f"B{rr}", MESS[m]).border = LINE
    put(ws, f"C{rr}", f"=_xlfn.MAXIFS({rg('G')},{crit})", kind="formula", fmt="0%", fill=F_OUT, bold=True)
    put(ws, f"D{rr}", f"={q(SD)}!$D${TOT[(w, m)]}", kind="link", fmt="#,##0")
    put(ws, f"E{rr}", f"={REF['seats_A'] if m == 'A' else REF['seats_B']}", kind="link", fmt="#,##0")
    put(ws, f"F{rr}", f"={wavg_expr(w, m, 'seat', 'G')}", kind="link", fmt="0.0")
    for col in "CDEF":
        ws[f"{col}{rr}"].alignment = Alignment(horizontal="center", vertical="center")
note(ws, "A11", "Seats are never the constraint. Even in the surge, arrivals × eating time stays far below the 900 seats at Central and 492 at "
     "Munch, so nobody waits for a seat. Little's Law fits well in the middle of the lunch; at the edges it drifts because a meal (about "
     f"{EAT_MEAN:.0f} minutes) is longer than a 10-minute slot. Disposal never queues.", "F16")

# =============================================================================
# Little's Law on the whole visit
# =============================================================================
LL = "Littles Law"
ws = sheet(LL, "Little's Law on the whole visit", "L = λ × W: people inside equal arrivals per minute times minutes inside, whenever the mess is steady.",
           [24, 13, 8, 12, 12, 13, 11, 10, 44])
note(ws, "A4", "Slot by slot the mess is never perfectly steady, because arrivals follow the department lunch breaks. When L ÷ λW is well below 1 "
     "the mess is filling (the 12:00 and 13:00 surges); above 1, people from a busy slot are still inside while arrivals have dropped. Over the "
     "whole lunch the two sides agree (Checks). The queue tabs apply the same test to each process: where ρ ≥ 1 the line keeps growing and "
     "no steady state exists.", "I7")
TOPL = 10
section(ws, f"A{TOPL - 1}", "Slot by slot")
heads(ws, TOPL, 1, ["Scenario", "Mess", "Slot", "λ arriving (/min)", "Visit time W (min)", "People inside (simulated L)", "λ × W", "L ÷ λW", "What it means"])
r = TOPL + 1
LLROW = {}
for w in WORLD:
    for m in MESS:
        for b in range(18):
            put(ws, f"A{r}", WORLD[w]).border = LINE
            put(ws, f"B{r}", MESS[m]).border = LINE
            put(ws, f"C{r}", clock(b * 10)).border = LINE
            put(ws, f"D{r}", f"={sd(w, m, 'visit', b, 'E')}", kind="link", fmt="0.0")
            put(ws, f"E{r}", f"={sd(w, m, 'visit', b, 'G')}", kind="link", fmt="0.0")
            put(ws, f"F{r}", f"={sd(w, m, 'visit', b, 'I')}", kind="link", fmt="0")
            put(ws, f"G{r}", f"=D{r}*E{r}", kind="formula", fmt="0")
            put(ws, f"H{r}", f'=IF(MAX(F{r},G{r})<10,"≈ 0",IF(G{r}=0,"no new arrivals",F{r}/G{r}))', kind="formula", fmt="0.00")
            put(ws, f"I{r}", f'=IF(D{r}=0,"",IF(ISNUMBER(H{r}),IF(ABS(H{r}-1)<=0.15,"Steady: L = λW holds",IF(H{r}<1,"Filling up: arrivals outpace people leaving","Emptying: people from earlier slots still inside")),IF(G{r}=0,"Emptying: no new arrivals","Almost empty")))', kind="formula")
            for col in "CDEFGH":
                ws[f"{col}{r}"].alignment = Alignment(horizontal="center", vertical="center")
            LLROW[(w, m, b)] = r
            r += 1
LL_LAST = r - 1
ws.auto_filter.ref = f"A{TOPL}:I{LL_LAST}"
ws.freeze_panes = f"D{TOPL + 1}"
ws.conditional_formatting.add(f"I{TOPL + 1}:I{LL_LAST}", FormulaRule(formula=[f'LEFT($I{TOPL + 1},6)="Steady"'], font=Font(name=FONT, color="2E6B30", bold=True)))
cr = LL_LAST + 3
section(ws, f"A{cr}", "Central CT today: people inside vs λ × W (chart data)")
heads(ws, cr + 1, 1, ["Slot", "People inside (simulated)", "λ × W"])
for b in range(18):
    rr = cr + 2 + b
    src = LLROW[("today", "A", b)]
    put(ws, f"A{rr}", clock(b * 10)).border = LINE
    put(ws, f"B{rr}", f"=F{src}", kind="formula", fmt="0")
    put(ws, f"C{rr}", f"=G{src}", kind="formula", fmt="0")
ch = LineChart()
ch.add_data(Reference(ws, min_col=2, max_col=3, min_row=cr + 1, max_row=cr + 19), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=cr + 2, max_row=cr + 19))
ch.height, ch.width = 9, 17
style_chart(ch, "Central CT today: L (simulated) vs λW", "Students", colors=[ACCENT, "C55A11"])
ws.add_chart(ch, f"K{TOPL}")

# =============================================================================
# Capacity
# =============================================================================
CP = "Capacity"
ws = sheet(CP, "Capacity", "Seat turnover, the capacity of each stage, and the bottleneck. Times are simulated averages for today (no screens).",
           [58, 17, 17, 50], group="capacity")
heads(ws, 4, 1, ["Measure", "Central CT", "Munch Mess", "How it is calculated"])


def wavg(w, m, st, col):
    """λ-weighted average of a Sim Data column over the lunch."""
    lam = f"{q(SD)}!$E${ROW[(w, m, st, 0)]}:$E${ROW[(w, m, st, 17)]}"
    x = f"{q(SD)}!${col}${ROW[(w, m, st, 0)]}:${col}${ROW[(w, m, st, 17)]}"
    return f"SUMPRODUCT({lam},{x})/SUM({lam})"


# Each formula is fn(m, X): m = mess id, X(key) = this column's cell for another row.
CAP = [
    ("sec", "1. Time at each stage, per student (simulated, today)"),
    ("st1", "Stage 1 · Scan & collect plate (minutes)",
     lambda m, X: f"={wavg('today', m, 'scanner', 'F')}+{wavg('today', m, 'scanner', 'G')}+{REF['plate']}/60", "0.00", "Group: 30–45 s, plus any queue at the scanner"),
    ("st2", "Stage 2 · Collect food (minutes)",
     lambda m, X: f"={wavg('today', m, 'station', 'F')}+{wavg('today', m, 'station', 'G')}+{REF['line']}/60", "0.00", "Group: 1–2 min, plus the queue (up to ~15 min in the rush)"),
    ("st3", "Stage 3 · Eat (minutes)", lambda m, X: f"={wavg('today', m, 'seat', 'F')}+{wavg('today', m, 'seat', 'G')}", "0.0", "Group: 14–18 min"),
    ("st4", "Stage 4 · Dispose of plate (minutes)", lambda m, X: f"={wavg('today', m, 'disposal', 'G')}", "0.0", "Group: 1–2 min"),
    ("visit", "Total time in the mess, door to leaving (minutes)", lambda m, X: f"={wavg('today', m, 'visit', 'G')}", "0.0", "Group: 17–35 min"),
    ("sec", "Detail: queues and service times"),
    ("scan", "Average scan time (seconds)", lambda m, X: f"={wavg('today', m, 'scanner', 'G')}*60", "0.0", "Mean time at the face scanner, excluding the queue"),
    ("scanq", "Average wait for the scanner (minutes)", lambda m, X: f"={wavg('today', m, 'scanner', 'F')}", "0.00", "Queue"),
    ("stq", "Average wait at the serving station (minutes)", lambda m, X: f"={wavg('today', m, 'station', 'F')}", "0.00", "Queue for the 2 stations"),
    ("sts", "Average serving time (minutes)", lambda m, X: f"={wavg('today', m, 'station', 'G')}", "0.00", "At the station"),
    ("stt", "Average time at the kitchen / serving station (wait + serving, minutes)", lambda m, X: f"={X('stq')}+{X('sts')}", "0.00", "Queue + service"),
    ("eat", "Average lunch (eating) time at the table (minutes)", lambda m, X: f"={wavg('today', m, 'seat', 'G')}", "0.0", "Seat held from sitting down to getting up"),
    ("sec", "2. Seat turnover"),
    ("seats", "Seats", lambda m, X: f"={REF['seats_A'] if m == 'A' else REF['seats_B']}", "#,##0", "Measured (Munch recounted: 492)"),
    ("turn", "Seat turnover time T (minutes per diner)", lambda m, X: f"={X('eat')}+{REF['changeover']}", "0.0", "Eating time + changeover (0.2 min)"),
    ("turns_h", "Seat turnover rate (diners per seat per hour)", lambda m, X: f"=60/{X('turn')}", "0.00", "60 ÷ T"),
    ("seatcap", "Seating capacity (students per minute)", lambda m, X: f"={X('seats')}/{X('turn')}", "0.0", "Seats ÷ T (Little's Law: λmax = L ÷ W)"),
    ("seatcap_l", "Seating capacity over the lunch window (students)", lambda m, X: f"={X('seats')}*{REF['window']}/{X('turn')}", "#,##0", "Seats × 180 ÷ T"),
    ("served", "Students served this lunch (simulated)", lambda m, X: f"={q(SD)}!$C${TOT[('today', m)]}", "#,##0", "Sim Data"),
    ("turns", "Actual turns per seat this lunch", lambda m, X: f"={X('served')}/{X('seats')}", "0.00", "Students served ÷ seats"),
    ("peak", "Peak seats in use (simulated)", lambda m, X: f"={q(SD)}!$D${TOT[('today', m)]}", "#,##0", "Sim Data"),
    ("peakutil", "Peak seat utilisation", lambda m, X: f"={X('peak')}/{X('seats')}", "0%", "Peak in use ÷ seats"),
    ("sec", "3. Capacity of each stage (students per minute) and the bottleneck"),
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
    ("cushion", "Capacity cushion = 1 − utilisation", lambda m, X: f"=1-{X('util')}", "0%",
     "Spare capacity over the whole lunch. Averages hide the peak: see section 4"),
    ("sec", "4. The peak decides: capacity needed in the busiest 10 minutes (serving stations)"),
    ("peak_arr", "Peak 10-min arrival rate at the serving stations, today (/min)",
     lambda m, X: f"=MAX({q(SD)}!$E${ROW[('today', m, 'station', 0)]}:$E${ROW[('today', m, 'station', 17)]})", "0.0", "Sim Data"),
    ("peak_ratio", "Peak load today: arrivals ÷ serving capacity", lambda m, X: f"={X('peak_arr')}/{X('cap_st')}", "0%", "Above 100% the line grows"),
    ("peak_arr_s", "Peak 10-min arrival rate with the screens (/min)",
     lambda m, X: f"=MAX({q(SD)}!$E${ROW[('screens', m, 'station', 0)]}:$E${ROW[('screens', m, 'station', 17)]})", "0.0", "Sim Data"),
    ("peak_ratio_s", "Peak load with the screens", lambda m, X: f"={X('peak_arr_s')}/{X('cap_st')}", "0%", "Load balancing moves part of Central's peak to Munch"),
    ("st_have", "Serving stations available", lambda m, X: f"={REF['c']}", "0", "Measured"),
    ("st_need", "Stations needed today to keep the peak at or below the target utilisation",
     lambda m, X: f"=ROUNDUP({X('peak_arr')}/({REF['mu']}*{REF['rho_t']}),0)", "0", "ROUNDUP(peak λ ÷ (μ × target)); target on Assumptions"),
    ("st_need_s", "Stations needed with the screens", lambda m, X: f"=ROUNDUP({X('peak_arr_s')}/({REF['mu']}*{REF['rho_t']}),0)", "0",
     "Same rule, after load balancing"),
]
CROW = {}
r = 5
for row in CAP:
    if row[0] == "sec":
        if r > 5:
            r += 1
        section(ws, f"A{r}", row[1])
    else:
        CROW[row[0]] = r
    r += 1
CAP_LAST = r - 1
for row in CAP:
    if row[0] == "sec":
        continue
    key, label, fn, fmt, how = row
    rr = CROW[key]
    hl = key in ("turn", "turns_h", "seatcap", "bottle", "peakutil", "util", "st1", "st2", "st3", "st4", "visit", "peak_ratio", "peak_ratio_s", "st_need", "st_need_s")
    put(ws, f"A{rr}", label, bold=hl).border = LINE
    for m, col in (("A", "B"), ("B", "C")):
        c = put(ws, f"{col}{rr}", fn(m, lambda k, col=col: f"{col}{CROW[k]}"), kind="auto", fmt=fmt, fill=F_OUT if hl else None, bold=hl)
        c.alignment = Alignment(horizontal="center", vertical="center")
    put(ws, f"D{rr}", how, wrap=True, italic=True, color=MUTED).border = LINE
note(ws, f"A{CAP_LAST + 2}", f"A seat turns over about every {TURN_T:.1f} minutes, roughly {60 / TURN_T:.1f} diners an hour, so the seats could take "
     f"about {A_.seats / TURN_T:.0f} students a minute at Central and {B_.seats / TURN_T:.0f} at Munch. The serving stations (20 a minute per mess) are the bottleneck at both messes, below the scanner (30) "
     "and the seats. Total capacity is not the problem: at the peak Central gets far more than its 20 a minute while Munch runs well under, "
     "so the answer is balancing the load, not adding seats. Averages hide this: over the whole lunch Central's stations look only about two-thirds used, "
     "yet in the busiest 10 minutes they are far over capacity. Sizing for the peak at the target utilisation, Central alone would need more stations "
     "today; with the screens the peak is shared, so it needs fewer. Seats can never fill: the stations let at most 20 students a minute through, "
     "and 20 × ~16 min of eating ≈ 320 seats, well under 900 and 492.", f"D{CAP_LAST + 7}")
bc = BarChart()
bc.add_data(Reference(ws, min_col=2, max_col=3, min_row=CROW["cap_scan"], max_row=CROW["cap_seat"]), titles_from_data=False)
bc.set_categories(Reference(ws, min_col=1, min_row=CROW["cap_scan"], max_row=CROW["cap_seat"]))
from openpyxl.chart.series import SeriesLabel  # noqa: E402
bc.series[0].tx = SeriesLabel(v="Central CT")
bc.series[1].tx = SeriesLabel(v="Munch Mess")
bc.height, bc.width = 9, 16
style_chart(bc, "Capacity of each stage (students per minute)", "Students / min", colors=[ACCENT, "C55A11"])
ws.add_chart(bc, "F4")

# =============================================================================
# Load Balancing
# =============================================================================
LB = "Load Balancing"
SHORT = {"Today": "Today", "freshers": "Freshers rule", "fixed 40% to": "Fixed 40% (forced)", "50/50": "Fixed 50/50 (forced)",
         "60% obey": "Fixed 40%, 60% obey", "TAPMI": "TAPMI + DOC rule", "MIT to Munch": "MIT rule", "60% follow": "Screens (60%)",
         "everyone follows": "Screens (100%)"}
ws = sheet(LB, "Load balancing", "How Smart Scan decides when to send a student to the other mess, and why a fixed 'department X eats at mess Y' rule does not work.",
           [54, 14, 14, 14, 14, 14, 14, 13, 13], group="balance")
section(ws, "A4", "1. How the routing works (every 5 seconds)")
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
    put(ws, f"A{5 + i}", f"{i + 1}.  {t}", wrap=True)
    ws.merge_cells(f"A{5 + i}:I{5 + i}")
r = 14
section(ws, f"A{r}", "2. Try the rule (change the blue cells)")
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
section(ws, f"A{r}", "3. What the screens decided at moments of one simulated lunch (seed 0, with screens)")
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
section(ws, f"A{r}", "4. When routing happens: students asked to switch per 10-min slot (with screens; simulated average)")
heads(ws, r + 1, 1, ["Slot", "Students deciding", "Asked to switch", "Actually switched", "Share asked", "Departments on lunch break", "", "", ""])
ws.merge_cells(f"F{r + 1}:I{r + 1}")
ADV0 = r + 2
for b, (n_, asked, moved) in enumerate(D["worlds"]["screens"]["advice"]):
    rr = ADV0 + b
    put(ws, f"A{rr}", clock(b * 10))
    put(ws, f"B{rr}", round(n_, 1), kind="data", fmt="0")
    put(ws, f"C{rr}", round(asked, 1), kind="data", fmt="0")
    put(ws, f"D{rr}", round(moved, 1), kind="data", fmt="0")
    put(ws, f"E{rr}", f"=IF(B{rr}>0,C{rr}/B{rr},0)", kind="formula", fmt="0%")
    put(ws, f"F{rr}", ", ".join(LUNCH.on_break(b * 10, b * 10 + 10)), size=10, color=MUTED)
    ws.merge_cells(f"F{rr}:I{rr}")
    for col in "BCDE":
        ws[f"{col}{rr}"].alignment = Alignment(horizontal="center", vertical="center")
ADV1 = ADV0 + 17
put(ws, f"A{ADV1 + 1}", "Total")
for col in "BCD":
    put(ws, f"{col}{ADV1 + 1}", f"=SUM({col}{ADV0}:{col}{ADV1})", kind="formula", fmt="#,##0", bold=True)
note(ws, f"A{ADV1 + 3}", "The screens stay quiet while both messes are quick and only ask students to walk when Central's predicted wait beats "
     "Munch's by more than the minimum saving, which happens mostly in the 13:10–13:30 surge. Nobody is assigned; each student sees advice "
     "based on the queue at that moment.", f"I{ADV1 + 4}")

r = ADV1 + 7
section(ws, f"A{r}", "5. Static rules vs dynamic routing (average day, simulated)")
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
put(ws, f"J{P0 - 1}", "Short name", kind="head")
for i, p in enumerate(pol_names):
    put(ws, f"J{P0 + i}", next(v for k, v in SHORT.items() if k in p), size=10, color=MUTED)
bc = BarChart()
bc.type = "bar"
bc.add_data(Reference(ws, min_col=2, min_row=P0 - 1, max_row=P1), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=10, min_row=P0, max_row=P1))
bc.legend = None
bc.height, bc.width = 10, 18
style_chart(bc, "Average wait by rule (minutes)", None, colors=[ACCENT])
ws.add_chart(bc, f"L{P0 - 1}")

r = P1 + 3
section(ws, f"A{r}", "6. Does the rule hold on other kinds of day? Average wait (min)")
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
put(ws, f"J{R0 - 1}", "Short name", kind="head")
for i, p in enumerate(D["robust"]):
    put(ws, f"J{R0 + i}", next(v for k, v in SHORT.items() if k in p), size=10, color=MUTED)
ws.column_dimensions["J"].width = 18
put(ws, f"A{rr}", "Lowest wait on this kind of day", bold=True)
for j in range(len(variants)):
    col = L(2 + j)
    put(ws, f"{col}{rr}", f"=INDEX($J${R0}:$J${R1},MATCH(MIN({col}{R0}:{col}{R1}),{col}{R0}:{col}{R1},0))", kind="formula", fill=F_OUT, wrap=True, bold=True)
    ws[f"{col}{rr}"].alignment = CENTER
rr += 1
put(ws, f"A{rr}", "Minutes saved by the screens over a fixed 40% share, at the same 60% compliance", bold=True, wrap=True)
dyn = next(R0 + i for i, p in enumerate(D["robust"]) if p.startswith("Dynamic: Smart Scan screens (60%"))
st60 = next(R0 + i for i, p in enumerate(D["robust"]) if "60% obey" in p)
for j in range(len(variants)):
    col = L(2 + j)
    put(ws, f"{col}{rr}", f"={col}{st60}-{col}{dyn}", kind="formula", fmt="+0.00;-0.00", fill=F_OUT, bold=True).alignment = CENTER
COMP_ROW = rr
for rr_ in list(range(P0, P1 + 1)) + list(range(R0, R1 + 1)):
    ws[f"A{rr_}"].border = LINE
    for col in "BCDEFGHI":
        ws[f"{col}{rr_}"].alignment = Alignment(horizontal="center", vertical="center")

r = rr + 2
section(ws, f"A{r}", "7. Why 'department / year X eats at mess Y' does not work, and why the routing must be dynamic")
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
    put(ws, f"A{r + 1 + i}", f"{i + 1}.  {t}", wrap=True)
    ws.merge_cells(f"A{r + 1 + i}:I{r + 1 + i}")
LB_LAST = r + len(WHY)

# per-slot comparison chart data
r = LB_LAST + 3
section(ws, f"A{r}", "8. Average wait by 10-min slot (both messes, weighted by students): today vs static rules vs dynamic")
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
ch.add_data(Reference(ws, min_col=2, max_col=1 + len(pick), min_row=r + 1, max_row=r + 19), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=r + 2, max_row=r + 19))
ch.height, ch.width = 10, 24
style_chart(ch, "Average wait by 10-minute slot (minutes)", "Minutes", colors=["7F7F7F", "F4B183", "C55A11", "9DC3E6", ACCENT])
ws.add_chart(ch, f"A{r + 21}")

# ---- 9. utilisation balance per slot (the load-balancing objective)
q2r = lambda w, m, b: Q2_TOP + 1 + (list(WORLD).index(w) * 2 + list(MESS).index(m)) * 18 + b  # noqa: E731
Q2N = q(Q2.title)
r = LB_LAST + 3 + 48
section(ws, f"A{r}", "9. Load balance: utilisation ρ of the serving stations at each mess, slot by slot")
put(ws, f"A{r + 1}", "Load balancing aims for equal utilisation: ρ at Central ≈ ρ at Munch ≈ the pooled level (all arrivals ÷ all capacity). "
    "The gap between the two messes is the imbalance the screens remove.", italic=True, color=MUTED, wrap=True)
ws.merge_cells(f"A{r + 1}:I{r + 1}")
heads(ws, r + 2, 1, ["Slot", "Today: ρ Central", "Today: ρ Munch", "Today: gap", "Screens: ρ Central", "Screens: ρ Munch", "Screens: gap",
                     "Balanced level (pooled ρ)", "Pooled stations needed at target"], 44)
BAL0 = r + 3
for b in range(18):
    rr = BAL0 + b
    put(ws, f"A{rr}", clock(b * 10))
    a_t, b_t, a_s, b_s = q2r("today", "A", b), q2r("today", "B", b), q2r("screens", "A", b), q2r("screens", "B", b)
    put(ws, f"B{rr}", f"={Q2N}!H{a_t}", kind="link", fmt="0%")
    put(ws, f"C{rr}", f"={Q2N}!H{b_t}", kind="link", fmt="0%")
    put(ws, f"D{rr}", f"=ABS(B{rr}-C{rr})", kind="formula", fmt="0%")
    put(ws, f"E{rr}", f"={Q2N}!H{a_s}", kind="link", fmt="0%")
    put(ws, f"F{rr}", f"={Q2N}!H{b_s}", kind="link", fmt="0%")
    put(ws, f"G{rr}", f"=ABS(E{rr}-F{rr})", kind="formula", fmt="0%")
    put(ws, f"H{rr}", f"=({Q2N}!D{a_t}+{Q2N}!D{b_t})/({Q2N}!G{a_t}*{Q2N}!F{a_t}+{Q2N}!G{b_t}*{Q2N}!F{b_t})", kind="formula", fmt="0%")
    put(ws, f"I{rr}", f"=ROUNDUP(({Q2N}!D{a_t}+{Q2N}!D{b_t})/({REF['mu']}*{REF['rho_t']}),0)", kind="formula", fmt="0")
    for col in "BCDEFGHI":
        ws[f"{col}{rr}"].alignment = Alignment(horizontal="center", vertical="center")
BAL1 = BAL0 + 17
ws.conditional_formatting.add(f"B{BAL0}:C{BAL1}", FormulaRule(formula=[f"B{BAL0}>=1"], fill=F_BAD))
ws.conditional_formatting.add(f"E{BAL0}:F{BAL1}", FormulaRule(formula=[f"E{BAL0}>=1"], fill=F_BAD))
_busy = max(range(18), key=lambda b: D["worlds"]["today"]["A"]["station"][b]["lam"])
rr = BAL1 + 2
put(ws, f"A{rr}", f"At the busiest 10 minutes ({clock(_busy * 10)}–{clock(_busy * 10 + 10)}, Central today)", bold=True)
heads(ws, rr + 1, 1, ["Mess", "Today", "With the screens", "Balanced level"])
BUSY0 = rr + 2
for i, (mname, ct, cs) in enumerate([("Central CT", "B", "E"), ("Munch Mess", "C", "F")]):
    put(ws, f"A{BUSY0 + i}", mname)
    put(ws, f"B{BUSY0 + i}", f"={ct}{BAL0 + _busy}", kind="formula", fmt="0%", fill=F_OUT, bold=True)
    put(ws, f"C{BUSY0 + i}", f"={cs}{BAL0 + _busy}", kind="formula", fmt="0%", fill=F_OUT, bold=True)
    put(ws, f"D{BUSY0 + i}", f"=H{BAL0 + _busy}", kind="formula", fmt="0%")
put(ws, f"A{BUSY0 + 2}", "Gap between the messes")
put(ws, f"B{BUSY0 + 2}", f"=ABS(B{BUSY0}-B{BUSY0 + 1})", kind="formula", fmt="0%", bold=True)
put(ws, f"C{BUSY0 + 2}", f"=ABS(C{BUSY0}-C{BUSY0 + 1})", kind="formula", fmt="0%", bold=True)
put(ws, f"A{BUSY0 + 3}", "Pooled stations needed at the target (both messes; 4 available)")
put(ws, f"B{BUSY0 + 3}", f"=I{BAL0 + _busy}", kind="formula", fmt="0", bold=True)
note(ws, f"A{BUSY0 + 5}", "Today the load is badly unbalanced: Central's stations are far over capacity while Munch's are mostly idle. The screens move "
     "both towards the balanced level without adding a station. They stop short of it because only 60% of students follow and the screens only "
     "speak up when switching saves at least 2 minutes. In the busiest minutes even perfect balancing leaves both messes near the steep part of the "
     "waiting curve: the balanced level is above 90%, so at the 85% planning target both messes together would need a fifth station for those "
     "10 minutes. That is why the stagger options on the decision workbook (moving one department's lunch break) still matter.", f"I{BUSY0 + 8}")
bc2 = BarChart()
bc2.add_data(Reference(ws, min_col=2, max_col=3, min_row=BUSY0 - 1, max_row=BUSY0 + 1), titles_from_data=True)
bc2.set_categories(Reference(ws, min_col=1, min_row=BUSY0, max_row=BUSY0 + 1))
bc2.y_axis.number_format = "0%"
bc2.height, bc2.width = 9, 14
style_chart(bc2, "Busiest 10 minutes: utilisation ρ by mess", "Utilisation ρ", colors=["C55A11", ACCENT])
ws.add_chart(bc2, f"K{BUSY0 - 2}")
lc2 = LineChart()
lc2.add_data(Reference(ws, min_col=2, max_col=3, min_row=r + 2, max_row=BAL1), titles_from_data=True)
lc2.add_data(Reference(ws, min_col=5, max_col=6, min_row=r + 2, max_row=BAL1), titles_from_data=True)
lc2.add_data(Reference(ws, min_col=8, max_col=8, min_row=r + 2, max_row=BAL1), titles_from_data=True)
lc2.set_categories(Reference(ws, min_col=1, min_row=BAL0, max_row=BAL1))
lc2.y_axis.number_format = "0%"
lc2.height, lc2.width = 10, 22
style_chart(lc2, "Utilisation ρ by slot: today vs with the screens", "Utilisation ρ", colors=["C55A11", "F4B183", ACCENT, "9DC3E6", "7F7F7F"])
lc2.series[-1].graphicalProperties.line.dashStyle = "dash"
ws.add_chart(lc2, f"K{BAL0}")

# =============================================================================
# Checks
# =============================================================================
CK = "Checks"
ws = sheet(CK, "Checks", "Each check should read OK. Recalculate after changing an input.", [74, 14, 12], group="checks")
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
    ("The serving-capacity rule explains the queue: the rule applied to each lunch ÷ the simulated wait, Central today (within 25%)",
     f"={q(Q2.title)}!I6/{q(Q2.title)}!G6", "=IF(ABS(B13-1)<=0.25,\"OK\",\"CHECK\")", "0.00"),
    ("Load balancing narrows the gap between the messes at the busiest 10 minutes",
     f"={q(LB)}!B{BUSY0 + 2}-{q(LB)}!C{BUSY0 + 2}", "=IF(B14>0,\"OK\",\"CHECK\")", "0%"),
]
checks += [
    ("Every input on the Assumptions tab is a number (text such as '12-15' breaks the formulas)",
     f"=SUMPRODUCT(--ISNUMBER({q(AS)}!$B$5:$B${NUM_INPUTS[-1][1:]}))", f'=IF(B{5 + len(checks)}={len(NUM_INPUTS)},"OK","CHECK: fix the yellow/blue inputs")', "0"),
    ("No formula errors in Variables", f"=SUMPRODUCT(--ISERROR({q(VA)}!$A$4:$G$80))", f'=IF(B{6 + len(checks)}=0,"OK","CHECK")', "0"),
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
ws = sheet(ST, "Smart Mess: queues, capacity and load balancing", "Central CT and Munch Mess · lunch 11:30–14:30 · MDS project, Group WGB3",
           [3, 44, 72, 26], group="guide")
put(ws, "B4", "What this workbook shows", bold=True, size=13, color=NAVY)
put(ws, "B5", "Where the lunch queue forms, how much each part of the mess can handle, and how Smart Scan spreads students between the two "
    "messes. Three questions, one tab each, all built on the same simulated lunches.", wrap=True)
ws.merge_cells("B5:D5")
put(ws, "B6", f"All figures are simulated: {D['seeds']} simulated lunches per scenario from the Smart Mess model, using the inputs on the "
    "Assumptions tab. They show how the system behaves under those assumptions; they are not measurements.", wrap=True, italic=True, color=MUTED)
ws.merge_cells("B6:D6")

put(ws, "B8", "How to walk through it", bold=True, size=13, color=NAVY)
heads(ws, 9, 2, ["Tab", "What it answers", "Concept"])
GUIDE = [
    (AS, "What we assumed: students, timings, seats, stations, compliance", "Inputs"),
    (VA, "What each symbol means, with its value in a real slot (λ = …, ρ = …)", "Notation"),
    (Q1.title, "Can one face scanner keep up?", "1 · Queue management (M/M/1)"),
    (Q2.title, "Where does the line form, and when is it unstable?", "1 · Queue management (M/M/c)"),
    (Q3, "Do the seats or the bins ever hold students up?", "1 · Queue management (M/G/c)"),
    (LL, "When is the mess steady, filling or emptying?", "1 · Little's Law"),
    (CP, "Seat turnover, capacity of each stage, the bottleneck", "2 · Capacity management"),
    (LB, "When we send students to the other mess, and why a fixed rule fails", "3 · Load balancing"),
    (SD, "The simulated numbers every tab reads from", "Data"),
    (CK, "Do the numbers add up?", "Validation"),
]
for i, (t, d, c_) in enumerate(GUIDE):
    rr = 10 + i
    c = put(ws, f"B{rr}", t, bold=True)
    c.hyperlink = f"#{q(t)}!A1"
    c.font = Font(name=FONT, size=11, bold=True, color=ACCENT, underline="single")
    c.border = LINE
    put(ws, f"C{rr}", d, wrap=True).border = LINE
    put(ws, f"D{rr}", c_, italic=True, color=MUTED).border = LINE
r = 11 + len(GUIDE)

put(ws, f"B{r}", "Headline results", bold=True, size=13, color=NAVY)
KEY = [
    ("Bottleneck at both messes", f"={q(CP)}!B{CROW['bottle']}", None),
    ("Central's serving stations at the 13:10 surge (today)", f"=TEXT({q(Q2.title)}!C6,\"0%\")&\" busy: over capacity\"", None),
    ("Slots over capacity at Central: today → with screens", f"={q(Q2.title)}!D6&\" → \"&{q(Q2.title)}!D8", None),
    ("Seat turnover at Central", f"=TEXT({q(CP)}!B{CROW['turn']},\"0.0\")&\" min per diner · \"&TEXT({q(CP)}!B{CROW['turns_h']},\"0.0\")&\" diners per seat per hour\"", None),
    ("Peak seats in use: Central / Munch", f"=TEXT({q(CP)}!B{CROW['peakutil']},\"0%\")&\" of 900 / \"&TEXT({q(CP)}!C{CROW['peakutil']},\"0%\")&\" of 492\"", None),
    ("Average wait: today → freshers-at-Munch rule → Smart Scan",
     f"=TEXT({q(LB)}!B{P0},\"0.0\")&\" → \"&TEXT({q(LB)}!B{P0 + 1},\"0.0\")&\" → \"&TEXT({q(LB)}!B{P0 + pol_names.index('Dynamic: Smart Scan screens (60% follow)')},\"0.0\")&\" min\"", None),
    ("Load balance at the busiest 10 minutes: Central / Munch ρ, today → with screens",
     f"=TEXT({q(LB)}!B{BUSY0},\"0%\")&\" / \"&TEXT({q(LB)}!B{BUSY0 + 1},\"0%\")&\" → \"&TEXT({q(LB)}!C{BUSY0},\"0%\")&\" / \"&TEXT({q(LB)}!C{BUSY0 + 1},\"0%\")&\" (balanced \"&TEXT({q(LB)}!D{BUSY0},\"0%\")&\")\"", None),
    ("Stations needed at Central for its peak (target ρ): today → with screens",
     f"={q(CP)}!B{CROW['st_need']}&\" → \"&{q(CP)}!B{CROW['st_need_s']}&\" (2 available)\"", None),
    ("All checks", f"={q(CK)}!C{CK_LAST + 2}", None),
]
for i, (a, f, fmt) in enumerate(KEY):
    rr = r + 1 + i
    put(ws, f"B{rr}", a, wrap=True).border = LINE
    c = put(ws, f"C{rr}", f, kind="link", fmt=fmt, fill=F_OUT, bold=True)
    ws.merge_cells(f"C{rr}:D{rr}")
r = r + 2 + len(KEY)

put(ws, f"B{r}", "Colour key", bold=True, size=13, color=NAVY)
KEYS = [("12", "Blue text", "an input you can change", {"color": BLUE}), ("12", "Shaded yellow", "an assumption not yet measured", {"fill": F_KEY}),
        ("12", "Shaded grey", "simulated data", {"fill": F_DATA, "color": BLUE}), ("12", "Green text", "a value pulled from another tab", {"color": GREEN}),
        ("12", "Shaded green", "a key result", {"fill": F_OUT}), ("12", "Red / amber rows", "over capacity / near capacity", {"fill": F_BAD})]
for i, (_v, a, b, st) in enumerate(KEYS):
    rr = r + 1 + i
    c = put(ws, f"B{rr}", a, bold=True, color=st.get("color"), fill=st.get("fill"))
    c.border = LINE
    put(ws, f"C{rr}", b).border = LINE
r = r + 2 + len(KEYS)
put(ws, f"B{r}", "To refresh the data: python tools/queue_capacity_data.py, then python tools/build_queue_capacity_workbook.py", italic=True, color=MUTED)
ws.merge_cells(f"B{r}:D{r}")

ORDER = [ST, AS, VA, Q1.title, Q2.title, Q3, LL, CP, LB, SD, CK]
wb._sheets = [wb[n] for n in ORDER]
wb.active = 0
for wsx in wb.worksheets:
    fit_rows(wsx)
    wsx.sheet_view.tabSelected = wsx.title == ST

for wsx in wb.worksheets:
    for row in wsx.iter_rows():
        for c in row:
            if c.value is not None and (c.font is None or c.font.name != FONT):
                c.font = Font(name=FONT, size=c.font.size or 11, bold=c.font.bold, italic=c.font.italic, color=c.font.color,
                              underline=c.font.underline)
wb.calculation.fullCalcOnLoad = True  # no cached values from openpyxl: make Excel compute every formula on open
wb.save(OUT)
print("saved", OUT)
