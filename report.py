"""One spreadsheet with the whole result:  python report.py  -> outputs/carbon_report.xlsx

Run after run.py. Sheets:
  Read me, Summary, Audit (every line with its factor and a recomputation), Review queue,
  Loan scenarios, Product footprint, Cost model, Injection lines, Factors.

Inputs (blue): per-line results from outputs/audit.csv, emission_factors.csv, scenarios.yaml.
Everything derived is an Excel formula, so changing an assumption cell recalculates the sheet.
Nothing here changes predictions.csv, audit.csv or summary.csv.
"""

import re
import sys
from collections import defaultdict

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from analysis import load, stage_of
from run import BASIS
from src.load import ROOT, load_factors, load_ledgers, read_csv, strip_injection
from src.memo import memo_items

OUT = ROOT / "outputs" / "carbon_report.xlsx"

FONT = "Arial"
BLUE = Font(name=FONT, color="0000FF")  # hardcoded input
GREEN = Font(name=FONT, color="008000")  # link to another sheet
BLACK = Font(name=FONT)
BOLD = Font(name=FONT, bold=True)
TITLE = Font(name=FONT, bold=True, size=14)
HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
KEY_FILL = PatternFill("solid", fgColor="FFFF00")  # key assumption the reader may change
WRAP = Alignment(wrap_text=True, vertical="top")

T = "#,##0.0;(#,##0.0);-"  # tonnes
T4 = "0.0000;-0.0000;-"  # tonnes, 4 decimals
N0 = "#,##0;(#,##0);-"  # kWh, m3, KZT, counts
N2 = "#,##0.00"
PCT = "0.0%;(0.0%);-"
KG = "0.000"


def put(ws, cell, value, font=BLACK, fmt=None, fill=None, bold=False):
    """Write a value with font, number format and fill into one cell."""
    c = ws[cell]
    c.value = value
    c.font = Font(name=FONT, bold=True, color=font.color) if bold else font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    return c


def data_cell(ws, row, col, value, font=BLUE):
    """A value copied from the ledger or a CSV. Text that starts like a formula ("=", "+", "-", "@")
    is stored as plain text: ledger text is data, never something Excel should execute."""
    c = ws.cell(row=row, column=col, value=None if pd.isna(value) else value)
    if isinstance(c.value, str) and c.value[:1] in ("=", "+", "-", "@"):
        c.data_type = "s"
    c.font = font
    return c


def header(ws, row, labels, widths=None):
    """Bold header row with optional column widths."""
    for i, label in enumerate(labels, 1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill, c.alignment = BOLD, HEADER_FILL, WRAP
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def yaml_sources():
    """key -> source comment ("ASSUMPTION: ..." / "DATA PACK: ...") from scenarios.yaml."""
    out = {}
    for line in (ROOT / "scenarios.yaml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([a-z0-9_]+):\s*[^#]*#\s*(.+)", line)
        if m:
            out[m[1]] = m[2].strip()
    return defaultdict(str, out)


# ----------------------------------------------------------------------------- data
def gather():
    """Audit joined with masked ledger fields, factors, scenarios and categories."""
    audit, ef, cfg = load()  # exits if run.py left unresolved review rows
    ledger = load_ledgers()[["line_id", "description", "gl", "quantity", "unit", "injection"]]
    a = audit.merge(ledger, on="line_id", how="left")
    a["stage"] = a["rule_id"].map(stage_of)
    factors = read_csv("emission_factors.csv")
    categories = list(read_csv("categories.csv")["category"])
    return a, factors, cfg, categories


# ----------------------------------------------------------------------------- sheets
def sheet_audit(wb, a, flast):
    """Audit sheet: every line with its factor and a recomputation formula."""
    ws = wb.create_sheet("Audit")
    cols = [
        "line_id",
        "set",
        "description (masked)",
        "GL",
        "ledger qty",
        "ledger unit",
        "category",
        "ef_id",
        "activity_qty",
        "activity_unit",
        "method",
        "factor (kgCO2e/unit)",
        "tCO2e recomputed",
        "tCO2e (pipeline)",
        "stage",
        "rule_id",
        "reason",
        "confidence",
        "review_flag",
        "recomputed − pipeline",
    ]
    header(ws, 1, cols, [9, 6, 44, 6, 12, 8, 16, 20, 14, 12, 9, 12, 12, 12, 18, 20, 50, 9, 40, 12])
    for r, x in enumerate(a.itertuples(index=False), 2):
        values = [
            x.line_id,
            x.set,
            x.description,
            x.gl,
            x.quantity,
            x.unit,
            x.category,
            x.ef_id,
            x.activity_qty,
            x.activity_unit,
            x.method,
        ]
        for col, v in enumerate(values, 1):
            data_cell(ws, r, col, v)
        ws.cell(
            row=r, column=12, value=f"=IFERROR(INDEX(Factors!$D$2:$D${flast},MATCH(H{r},Factors!$A$2:$A${flast},0)),0)"
        ).font = GREEN
        ws.cell(row=r, column=13, value=f'=IF(K{r}="excluded",0,IFERROR(ROUND(I{r}*L{r}/1000,4),""))')
        ws.cell(row=r, column=14, value=float(x.tco2e)).font = BLUE
        for col, v in zip(range(15, 20), [x.stage, x.rule_id, x.reason, x.confidence, x.review_flag], strict=False):
            data_cell(ws, r, col, v)
        # Excel's ROUND rounds halves up, pandas to even: up to 0.0001 t per line is rounding, not an error.
        ws.cell(row=r, column=20, value=f'=IF(M{r}="","",M{r}-N{r})').number_format = "0.0000;-0.0000;-"
        ws.cell(row=r, column=9).number_format = "#,##0.0000"
        ws.cell(row=r, column=12).number_format = "0.000"
        ws.cell(row=r, column=13).number_format = T4
        ws.cell(row=r, column=14).number_format = T4
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:T{len(a) + 1}"
    return len(a) + 1  # last data row


def sheet_summary(wb, last, categories, flast, memo):
    """Summary sheet: SUMIFS totals over Audit, checks and memo items."""
    ws = wb.create_sheet("Summary", 1)
    put(ws, "A1", "GHG inventory 2025 — Dala Foods LLP (train + test lines)", TITLE)
    put(ws, "A2", "Totals are formulas over the Audit sheet. Scope 2 is location-based; see Read me.")
    header(
        ws,
        4,
        [
            "Scope",
            "Category",
            "Lines",
            "tCO2e",
            "Activity-based tCO2e",
            "Spend-based tCO2e",
            "Share of total",
            "tCO2e per t product",
            "Basis",
        ],
        [9, 18, 8, 14, 14, 14, 10, 12, 60],
    )

    def rng(col):
        return f"Audit!${col}$2:${col}${last}"

    first = 5
    for i, cat in enumerate(categories):
        r = first + i
        scope = cat[:2] if cat.startswith("S") else "EXCLUDE"
        put(ws, f"A{r}", scope)
        put(ws, f"B{r}", cat)
        put(ws, f"C{r}", f"=COUNTIFS({rng('G')},B{r})", fmt=N0)
        put(ws, f"D{r}", f"=SUMIFS({rng('N')},{rng('G')},B{r})", fmt=T)
        put(ws, f"E{r}", f'=SUMIFS({rng("N")},{rng("G")},B{r},{rng("K")},"activity")', fmt=T)
        put(ws, f"F{r}", f'=SUMIFS({rng("N")},{rng("G")},B{r},{rng("K")},"spend")', fmt=T)
        put(ws, f"I{r}", BASIS.get(cat, ""))
    tot = first + len(categories)
    for i in range(len(categories)):
        r = first + i
        put(ws, f"G{r}", f"=IF($D${tot}=0,0,D{r}/$D${tot})", fmt=PCT)
        put(ws, f"H{r}", f"=D{r}/'Product footprint'!$B$4", fmt=KG)
    put(ws, f"A{tot}", "TOTAL", bold=True)
    for col, fmt in [("C", N0), ("D", T), ("E", T), ("F", T)]:
        put(ws, f"{col}{tot}", f"=SUM({col}{first}:{col}{tot - 1})", fmt=fmt, bold=True)
    put(ws, f"G{tot}", f"=IF(D{tot}=0,0,1)", fmt=PCT, bold=True)
    put(ws, f"H{tot}", f"=D{tot}/'Product footprint'!$B$4", fmt=KG, bold=True)
    put(ws, f"A{tot + 1}", "Activity share")
    put(ws, f"D{tot + 1}", f"=IF(D{tot}=0,0,E{tot}/D{tot})", fmt=PCT)
    put(ws, f"A{tot + 2}", "Check: lines where factor x activity differs from the pipeline by > 0.0001 t (should be 0)")
    put(ws, f"D{tot + 2}", f'=COUNTIFS({rng("T")},">0.00011")+COUNTIFS({rng("T")},"<-0.00011")', fmt="0")

    # Memo items: shown next to the inventory, NOT included in the totals above (see src/memo.py).
    m = tot + 4
    header(ws, m, ["Memo", "Item (not in totals)", "", "tCO2e", "", "", "Share of total", "", "Basis"])
    s2 = f'=SUMIF(A{first}:A{tot - 1},"S2",D{first}:D{tot - 1})'
    fac = f'INDEX(Factors!$D$2:$D${flast},MATCH("EF_WASTE_LANDFILL_T",Factors!$A$2:$A${flast},0))'
    cat12 = f'=SUMIFS({rng("I")},{rng("O")},"packaging")/1000*{fac}/1000'
    live = {"Scope 2 market-based": s2, "Scope 3 Cat 12 end of life of sold packaging (indicative)": cat12}
    for i, x in enumerate(memo.itertuples(index=False), m + 1):
        put(ws, f"A{i}", "MEMO")
        put(ws, f"B{i}", x.category)
        if x.category in live:
            put(ws, f"D{i}", live[x.category], GREEN, T)
        elif pd.notna(x.tco2e):
            put(ws, f"D{i}", float(x.tco2e), BLUE, T)
        else:
            put(ws, f"D{i}", "not estimated")
        if pd.notna(x.tco2e):
            put(ws, f"G{i}", f"=D{i}/$D${tot}", fmt=PCT)
        put(ws, f"I{i}", x.basis)
    ws.freeze_panes = "A5"


def sheet_review(wb, a):
    """Review queue sheet: flagged lines by |tCO2e|."""
    ws = wb.create_sheet("Review queue")
    put(ws, "A1", "Lines with a review flag, largest |tCO2e| first (snapshot of the last run.py)", BOLD)
    header(
        ws,
        3,
        ["line_id", "set", "description (masked)", "category", "tCO2e", "review_flag", "reason"],
        [9, 6, 50, 16, 12, 60, 60],
    )
    q = a[a["review_flag"].fillna("") != ""].copy()
    q = q.iloc[q["tco2e"].abs().argsort()[::-1]]
    for r, x in enumerate(q.itertuples(index=False), 4):
        for col, v in enumerate(
            [x.line_id, x.set, x.description, x.category, float(x.tco2e), x.review_flag, x.reason], 1
        ):
            data_cell(ws, r, col, v)
        ws.cell(row=r, column=5).number_format = T4
    put(ws, "H3", "Lines in queue", BOLD)
    put(ws, "H4", len(q), BLUE)
    ws.freeze_panes = "A4"


def sheet_factors(wb, factors):
    """Factors sheet: emission_factors.csv as given."""
    ws = wb.create_sheet("Factors")
    header(ws, 1, list(factors.columns), [22, 44, 14, 14, 26, 50])
    for r, row in enumerate(factors.itertuples(index=False), 2):
        for col, v in enumerate(row, 1):
            data_cell(ws, r, col, v)
    put(ws, f"A{len(factors) + 3}", "Source: emission_factors.csv (case data pack), used as given.")


def input_row(ws, r, label, value, unit, source, fmt=N0, key=False):
    """One labelled input cell with unit and source."""
    put(ws, f"A{r}", label)
    put(ws, f"B{r}", value, BLUE, fmt, KEY_FILL if key else None)
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", source)


def calc_row(ws, r, label, formula, unit, fmt=N0, font=BLACK, note=""):
    """One labelled formula cell with unit and note."""
    put(ws, f"A{r}", label)
    put(ws, f"B{r}", formula, font, fmt)
    put(ws, f"C{r}", unit)
    put(ws, f"D{r}", note)


def sheet_loan(wb, cfg, last, src, flast):
    """Loan scenarios sheet: editable assumptions and formula-driven scenarios."""
    ws = wb.create_sheet("Loan scenarios")
    sol, hp, loan = cfg["solar"], cfg["heat_pump"], cfg["loan"]
    for col, w in zip("ABCDEFGHIJK", [40, 16, 14, 50, 12, 12, 12, 12, 12, 11, 11], strict=False):
        ws.column_dimensions[col].width = w
    put(ws, "A1", "Bank: green loan scenarios, Scope 1+2 (location-based, case factors)", TITLE)
    put(ws, "A2", "Change the yellow cells; every result below recalculates.")
    header(ws, 3, ["Input", "Value", "Unit", "Source"])
    input_row(ws, 4, "Solar capacity", sol["capacity_kwp"], "kWp", src["capacity_kwp"], key=True)
    input_row(
        ws,
        5,
        "Solar specific yield",
        sol["specific_yield_kwh_per_kwp"],
        "kWh/kWp/yr",
        src["specific_yield_kwh_per_kwp"],
        key=True,
    )
    input_row(ws, 6, "Solar capex", sol["capex_kzt_per_kwp"], "KZT/kWp", src["capex_kzt_per_kwp"])
    input_row(
        ws,
        7,
        "Share of boiler heat moved to heat pumps",
        hp["share_of_boiler_heat"],
        "fraction",
        src["share_of_boiler_heat"],
        PCT,
        key=True,
    )
    input_row(ws, 8, "Boiler efficiency", hp["boiler_efficiency"], "fraction", src["boiler_efficiency"], PCT)
    input_row(ws, 9, "Gas heating value (NCV)", hp["gas_ncv_mj_per_m3"], "MJ/m3", src["gas_ncv_mj_per_m3"])
    input_row(ws, 10, "Heat-pump full-load hours", hp["full_load_hours"], "h/yr", src["full_load_hours"])
    input_row(ws, 11, "Heat-pump capex", hp["capex_kzt_per_kwth"], "KZT/kWth", src["capex_kzt_per_kwth"])
    input_row(ws, 12, "Green loan", loan["amount_kzt"], "KZT", src["amount_kzt"])
    input_row(ws, 13, "Heat-pump seasonal COP (base case)", hp["cop_base"], "-", src["cop_base"], "0.0", key=True)
    calc_row(
        ws,
        14,
        "Grid factor",
        f'=INDEX(Factors!$D$2:$D${flast},MATCH("EF_GRID_KZ_KWH",Factors!$A$2:$A${flast},0))',
        "kg/kWh",
        "0.000",
        GREEN,
        "Factors sheet",
    )
    calc_row(
        ws,
        15,
        "Natural gas factor",
        f'=INDEX(Factors!$D$2:$D${flast},MATCH("EF_NG_M3",Factors!$A$2:$A${flast},0))',
        "kg/m3",
        "0.000",
        GREEN,
        "Factors sheet",
    )

    header(ws, 17, ["2025 inventory (from Audit)", "Value", "Unit", ""])

    def aud(col):
        return f"Audit!${col}$2:${col}${last}"

    calc_row(ws, 18, "Grid electricity", f'=SUMIFS({aud("I")},{aud("P")},"ELECTRICITY")', "kWh", font=GREEN)
    calc_row(ws, 19, "Natural gas", f'=SUMIFS({aud("I")},{aud("P")},"FUEL_NATURAL_GAS")', "m3", font=GREEN)
    calc_row(ws, 20, "Scope 1", f'=SUMIFS({aud("N")},{aud("G")},"S1*")', "tCO2e", T, GREEN)
    calc_row(ws, 21, "Scope 2", f'=SUMIFS({aud("N")},{aud("G")},"S2*")', "tCO2e", T, GREEN)
    calc_row(ws, 22, "Total inventory", f"=SUM({aud('N')})", "tCO2e", T, GREEN)

    header(ws, 24, ["Derived", "Value", "Unit", "Formula"])
    calc_row(ws, 25, "Solar generation", "=B4*B5", "kWh/yr", note="capacity x yield")
    calc_row(ws, 26, "Useful heat per m3 of gas", "=B9/3.6*B8", "kWh/m3", N2, note="NCV / 3.6 x boiler efficiency")
    calc_row(ws, 27, "Gas replaced by heat pumps", "=B19*B7", "m3/yr")
    calc_row(ws, 28, "Heat replaced", "=B27*B26", "kWh/yr")
    calc_row(
        ws,
        29,
        "Break-even COP (heat pump vs gas boiler)",
        "=B26*B14/B15",
        "-",
        N2,
        note="below this COP heat pumps raise emissions",
    )
    calc_row(ws, 30, "Heat-pump size", "=B28/B10", "kWth")
    calc_row(ws, 31, "Capex solar", "=B4*B6", "KZT")
    calc_row(ws, 32, "Capex heat pumps", "=B30*B11", "KZT")
    calc_row(ws, 33, "Capex total", "=B31+B32", "KZT")
    calc_row(ws, 34, "Capex as share of loan", "=IF(B12=0,0,B33/B12)", "", PCT)

    header(
        ws,
        36,
        [
            "Scenario",
            "Solar (1 = yes)",
            "Heat-pump COP (blank = none)",
            "Solar kWh",
            "Heat-pump kWh",
            "Gas saved m3",
            "Scope 1 t",
            "Scope 2 t",
            "Change t/yr",
            "vs Scope 1+2",
            "vs total",
        ],
    )
    scenarios = [("Baseline 2025", 0, None), ("Solar only", 1, None), ("Heat pumps only (base COP)", 0, "=B13")]
    scenarios += [(f"Solar + heat pumps (COP {c})", 1, c) for c in hp["cop_range"]]
    for i, (name, solar, cop) in enumerate(scenarios):
        r = 37 + i
        put(ws, f"A{r}", name)
        put(ws, f"B{r}", solar, BLUE, "0")
        if cop is not None:
            put(ws, f"C{r}", cop, BLACK if isinstance(cop, str) else BLUE, "0.0")
        put(ws, f"D{r}", f"=B{r}*$B$25", fmt=N0)
        put(ws, f"E{r}", f'=IF(C{r}="",0,$B$28/C{r})', fmt=N0)
        put(ws, f"F{r}", f'=IF(C{r}="",0,$B$27)', fmt=N0)
        put(ws, f"G{r}", f"=$B$20-F{r}*$B$15/1000", fmt=T)
        put(ws, f"H{r}", f"=$B$21+(E{r}-D{r})*$B$14/1000", fmt=T)
        put(ws, f"I{r}", f"=(G{r}-$B$20)+(H{r}-$B$21)", fmt=T)
        put(ws, f"J{r}", f"=I{r}/($B$20+$B$21)", fmt=PCT)
        put(ws, f"K{r}", f"=I{r}/$B$22", fmt=PCT)


def sheet_product(wb, a, cfg, last, src):
    """Product footprint sheet: stages as SUMIFS over Audit."""
    ws = wb.create_sheet("Product footprint")
    p = cfg["product"]
    for col, w in zip("ABCDEF", [40, 14, 16, 14, 14, 14], strict=False):
        ws.column_dimensions[col].width = w
    put(ws, "A1", "Retailer: product footprint, cradle-to-gate plant average", TITLE)
    header(ws, 3, ["Input", "Value", "Unit", "Source"])
    input_row(ws, 4, "Finished product", p["finished_product_t"], "t", src["finished_product_t"], key=True)
    input_row(ws, 5, "Density (for per-litre figures)", p["density_kg_per_l"], "kg/l", src["density_kg_per_l"], "0.00")
    header(ws, 7, ["Stage", "tCO2e", "In product footprint", "kg CO2e per kg", "kg CO2e per l", "Share"])
    stages = a[a["tco2e"] != 0].groupby("stage")["tco2e"].sum().sort_values(ascending=False).index
    first, last_stage = 8, 8 + len(stages) - 1

    def aud(col):
        return f"Audit!${col}$2:${col}${last}"

    tot = last_stage + 1
    for i, stage in enumerate(stages):
        r = first + i
        put(ws, f"A{r}", stage)
        put(ws, f"B{r}", f"=SUMIFS({aud('N')},{aud('O')},A{r})", GREEN, T)
        put(ws, f"C{r}", "No" if stage in p["exclude_stages"] else "Yes", BLUE)
        put(ws, f"D{r}", f"=B{r}/$B$4", fmt=KG)
        put(ws, f"E{r}", f"=D{r}*$B$5", fmt=KG)
        put(ws, f"F{r}", f'=IF(C{r}="Yes",B{r}/$B${tot},0)', fmt=PCT)
    put(ws, f"A{tot}", "Product footprint (cradle-to-gate)", bold=True)
    put(ws, f"B{tot}", f'=SUMIFS(B{first}:B{last_stage},C{first}:C{last_stage},"Yes")', fmt=T, bold=True)
    put(ws, f"D{tot}", f"=B{tot}/$B$4", fmt=KG, bold=True)
    put(ws, f"E{tot}", f"=D{tot}*$B$5", fmt=KG, bold=True)
    put(ws, f"F{tot}", f"=SUM(F{first}:F{last_stage})", fmt=PCT, bold=True)
    put(ws, f"A{tot + 1}", "Corporate intensity (all scopes)")
    put(ws, f"B{tot + 1}", f"=SUM(B{first}:B{last_stage})", fmt=T)
    put(ws, f"D{tot + 1}", f"=B{tot + 1}/$B$4", fmt=KG)
    put(ws, f"E{tot + 1}", f"=D{tot + 1}*$B$5", fmt=KG)
    notes = [
        'Plant average over all products. Capital goods and business travel are left out ("No").',
        "Company transport is included: the ledger does not say whether a trip is milk collection or delivery.",
        "A label per product needs output volumes per product and a fat/protein (IDF) allocation of raw milk.",
    ]
    for i, n in enumerate(notes):
        put(ws, f"A{tot + 3 + i}", n)


def sheet_cost(wb, cfg, src):
    """Cost model sheet: days x rates against the budget."""
    ws = wb.create_sheet("Cost model")
    c = cfg["cost_model"]
    for col, w in zip("ABCD", [70, 10, 16, 16], strict=False):
        ws.column_dimensions[col].width = w
    put(ws, "A1", "CFO: annual running cost of the tool", TITLE)
    put(ws, "A2", "All days and day rates are assumptions; replace with Dala Foods' own rates.")
    header(ws, 4, ["Item", "Days", "Day rate KZT", "KZT per year"])
    first = 5
    for i, item in enumerate(c["items"]):
        r = first + i
        put(ws, f"A{r}", item["item"])
        put(ws, f"B{r}", item["days"], BLUE, N0, KEY_FILL)
        put(ws, f"C{r}", item["day_rate_kzt"], BLUE, N0, KEY_FILL)
        put(ws, f"D{r}", f"=B{r}*C{r}", fmt=N0)
    sub = first + len(c["items"])
    put(ws, f"A{sub}", "Subtotal")
    put(ws, f"D{sub}", f"=SUM(D{first}:D{sub - 1})", fmt=N0)
    put(ws, f"A{sub + 1}", "Contingency share")
    put(ws, f"C{sub + 1}", c["contingency_share"], BLUE, PCT)
    put(ws, f"D{sub + 1}", f"=D{sub}*C{sub + 1}", fmt=N0)
    put(ws, f"A{sub + 2}", "TOTAL per year", bold=True)
    put(ws, f"D{sub + 2}", f"=D{sub}+D{sub + 1}", fmt=N0, bold=True)
    put(ws, f"A{sub + 3}", "CFO budget")
    put(ws, f"D{sub + 3}", c["budget_kzt"], BLUE, N0)
    put(ws, f"B{sub + 3}", src["budget_kzt"])
    put(ws, f"A{sub + 4}", "Share of budget")
    put(ws, f"D{sub + 4}", f"=IF(D{sub + 3}=0,0,D{sub + 2}/D{sub + 3})", fmt=PCT)
    put(ws, f"A{sub + 5}", "Within budget?")
    put(ws, f"D{sub + 5}", f'=IF(D{sub + 2}<=D{sub + 3},"Yes","No")')


def sheet_injection(wb, a):
    """Injection lines sheet: original text next to the text used."""
    ws = wb.create_sheet("Injection lines")
    put(ws, "A1", "Lines with instruction-like text: it is stripped before classification, never obeyed", BOLD)
    header(
        ws,
        3,
        [
            "line_id",
            "set",
            "description in the ledger (masked)",
            "text used for classification",
            "category",
            "ef_id",
            "tCO2e",
            "rule_id",
            "review_flag",
        ],
        [9, 6, 60, 36, 16, 20, 10, 14, 50],
    )
    for r, x in enumerate(a[a["injection"].fillna(False).astype(bool)].itertuples(index=False), 4):
        for col, v in enumerate(
            [
                x.line_id,
                x.set,
                x.description,
                strip_injection(x.description)[0],
                x.category,
                x.ef_id,
                float(x.tco2e),
                x.rule_id,
                x.review_flag,
            ],
            1,
        ):
            data_cell(ws, r, col, v).alignment = WRAP
        ws.cell(row=r, column=7).number_format = T4


def sheet_readme(wb):
    """Read me sheet: contents, colour legend and basis."""
    ws = wb.active
    ws.title = "Read me"
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 100
    put(ws, "A1", "Dala Foods — Carbon Copilot report", TITLE)
    rows = [
        ("How to rebuild", "python run.py, then python report.py (writes outputs/carbon_report.xlsx)"),
        ("Summary", "Totals by scope and category, activity vs spend share, tCO2e per tonne of product"),
        (
            "Audit",
            "Every train + test line: masked description, factor, recomputed and pipeline tCO2e, rule, reason, flags",
        ),
        ("Review queue", "Flagged lines sorted by |tCO2e| (snapshot of the last run)"),
        ("Loan scenarios", "Bank: solar and heat-pump scenarios; change the yellow cells to test other assumptions"),
        ("Product footprint", "Retailer: kg CO2e per kg and per litre by life-cycle stage"),
        ("Cost model", "CFO: annual running cost against the KZT 15 m budget"),
        ("Injection lines", "Descriptions with planted AI instructions and the text actually used"),
        ("Factors", "emission_factors.csv as given in the case"),
        ("", ""),
        (
            "Colour legend",
            "Blue text = input (pipeline result, factor file or scenarios.yaml); black = formula; "
            "green = formula pulling from another sheet; yellow fill = key assumption you may change",
        ),
        (
            "Basis",
            "GHG Protocol, operational control, calendar year 2025; Scope 2 location-based; "
            "fuel factors CO2 only (IPCC 2006 Tier 1); refrigerant GWPs from IPCC AR5. See README.md",
        ),
        ("Privacy", "Counterparties and employees appear only as VENDOR_xxx / EMP_xx codes"),
    ]
    for i, (k, v) in enumerate(rows, 3):
        put(ws, f"A{i}", k, BOLD)
        c = put(ws, f"B{i}", v)
        c.alignment = WRAP


def build(path=OUT):
    """Build the workbook and save it."""
    a, factors, cfg, categories = gather()
    src = yaml_sources()
    wb = Workbook()
    sheet_readme(wb)
    flast = len(factors) + 1  # last row of the Factors table
    last = sheet_audit(wb, a, flast)
    sheet_summary(wb, last, categories, flast, memo_items(a, load_factors()))
    sheet_review(wb, a)
    sheet_loan(wb, cfg, last, src, flast)
    sheet_product(wb, a, cfg, last, src)
    sheet_cost(wb, cfg, src)
    sheet_injection(wb, a)
    sheet_factors(wb, factors)
    wb.move_sheet("Audit", offset=2 - wb.sheetnames.index("Audit"))  # right after Summary
    path.parent.mkdir(exist_ok=True)
    wb.save(path)
    return path


def main():
    """Write outputs/carbon_report.xlsx."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Wrote {build().relative_to(ROOT)}")


if __name__ == "__main__":
    main()
