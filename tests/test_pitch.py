"""Pitch numbers (pitch/build_pitch.py) are computed from the outputs, and the loan maths is right."""

import pandas as pd
import pytest

from pitch.build_pitch import compute, green_loan
from src.load import ROOT


@pytest.fixture(scope="module")
def numbers():
    return compute(run_stress=False)


def test_inventory_matches_the_audit(numbers):
    audit = pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")
    assert numbers["inventory"]["total_tco2e"] == pytest.approx(audit["tco2e"].sum())
    assert numbers["product"]["kgco2e_per_kg"] == pytest.approx(audit["tco2e"].sum() / 105_000)


def test_purchase_group_shares_add_up(numbers):
    groups = pd.DataFrame(numbers["purchase_groups"])
    assert groups["share_of_spend"].sum() == pytest.approx(1) and groups["share_of_emissions"].sum() == pytest.approx(1)
    assert list(numbers["hotspots"])[0] == "raw milk"


def test_break_even_cop_and_solar():
    r = green_loan(1_000_000, 0, 0.8, 1.91, cop=4.0, share=0.4, efficiency=0.9, ncv=34, solar_mwp=1, solar_yield=1300)
    assert r["break_even_cop"] == pytest.approx(34 / 3.6 * 0.9 * 0.8 / 1.91)
    assert r["change_heat_pumps_t"] < 0  # COP 4 is above break-even
    assert r["change_solar_t"] == pytest.approx(-1300 * 1000 * 0.8 / 1000)


def test_highlighted_refrigerant_line(numbers):
    h = numbers["mistakes_caught"]["highlight"]
    assert h["line_id"] == "L00131" and h["tco2e"] == pytest.approx(22.5 * 3943 / 1000)
