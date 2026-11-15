"""Checks for report.py (the spreadsheet). Formula values are computed by Excel on opening; here we
check the structure: sheets, one Audit row per line, formulas where results should be live."""

import hashlib

import pandas as pd
import pytest
from openpyxl import load_workbook

import report
from src.load import ROOT


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    path = tmp_path_factory.mktemp("report") / "carbon_report.xlsx"
    pred = ROOT / "outputs" / "predictions.csv"
    before = hashlib.sha256(pred.read_bytes()).hexdigest()
    report.build(path)
    assert hashlib.sha256(pred.read_bytes()).hexdigest() == before  # never touches predictions
    return load_workbook(path)


def test_all_sheets_present(workbook):
    assert workbook.sheetnames == [
        "Read me",
        "Summary",
        "Audit",
        "Review queue",
        "Loan scenarios",
        "Product footprint",
        "Cost model",
        "Injection lines",
        "Factors",
    ]


def test_one_audit_row_per_line_with_live_recomputation(workbook):
    audit = pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")
    ws = workbook["Audit"]
    assert ws.max_row - 1 == len(audit)
    assert ws["L2"].value.startswith("=IFERROR(INDEX(Factors!") and ws["M2"].value.startswith("=IF(")
    assert {ws.cell(r, 1).value for r in range(2, ws.max_row + 1)} == set(audit["line_id"])


def test_summary_totals_are_formulas_over_audit(workbook):
    ws = workbook["Summary"]
    total = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "TOTAL")
    rows = [r for r in range(5, total) if ws.cell(r, 2).value]
    assert len(rows) == 11  # all categories
    assert all(str(ws.cell(r, 4).value).startswith("=SUMIFS(Audit!") for r in rows)


def test_loan_inputs_come_from_scenarios_yaml_and_results_are_formulas(workbook):
    ws = workbook["Loan scenarios"]
    assert ws["B4"].value == 3000 and "ASSUMPTION" in ws["D4"].value
    assert ws["B29"].value == "=B26*B14/B15"  # break-even COP
    assert all(str(ws.cell(r, 9).value).startswith("=") for r in range(37, 45))


def test_cost_model_and_product_footprint_are_live(workbook):
    assert workbook["Cost model"]["D5"].value == "=B5*C5"
    ws = workbook["Product footprint"]
    assert ws["B8"].value.startswith("=SUMIFS(Audit!") and ws["B4"].value == 105_000


def test_injection_sheet_lists_the_planted_lines(workbook):
    ws = workbook["Injection lines"]
    assert ws.max_row - 3 >= 5
    assert all("instruction-like text ignored" in ws.cell(r, 9).value for r in range(4, ws.max_row + 1))


def test_summary_memo_block_below_total(workbook):
    ws = workbook["Summary"]
    memo = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "MEMO"]
    total = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "TOTAL")
    assert len(memo) == 5 and min(memo) > total
    assert ws.cell(memo[0], 4).value.startswith("=SUMIF(A")  # market-based follows Scope 2
    assert ws.cell(memo[-1], 4).value == "not estimated"  # Cat 3


def test_ledger_text_that_looks_like_a_formula_stays_text(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    for i, text in enumerate(['=HYPERLINK("http://x","click")', "+1+1", "-2", "@SUM(A1)"], 1):
        report.data_cell(wb.active, i, 1, text)
    wb.save(tmp_path / "t.xlsx")
    ws = load_workbook(tmp_path / "t.xlsx").active
    assert [ws.cell(i, 1).data_type for i in range(1, 5)] == ["s"] * 4
