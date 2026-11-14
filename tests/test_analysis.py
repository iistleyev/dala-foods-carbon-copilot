"""Checks for analysis.py (bank, retailer, CFO answers). Reads outputs/audit.csv from the last run.py."""
import hashlib

import pytest

import analysis
from analysis import cost_model, load, loan_scenarios, product_footprint
from src.load import ROOT


@pytest.fixture(scope="module")
def inputs():
    return load()  # audit, factors, scenarios


def scenario(df, name):
    return df.set_index("scenario").loc[name]


def test_solar_cuts_scope2_by_generation_times_grid_factor(inputs):
    loan, facts = loan_scenarios(*inputs)
    assert facts["solar generation, kWh/yr"] == 4_050_000                       # 3,000 kWp x 1,350 kWh/kWp
    assert scenario(loan, "solar only")["change_t"] == pytest.approx(-4_050_000 * 0.8 / 1000)


def test_break_even_cop(inputs):
    _, facts = loan_scenarios(*inputs)
    assert facts["break-even COP (heat pump vs gas boiler)"] == pytest.approx(34 / 3.6 * 0.9 * 0.8 / 1.91)
    assert round(facts["break-even COP (heat pump vs gas boiler)"], 2) == 3.56


def test_heat_pumps_alone_raise_emissions_below_break_even(inputs):
    loan, _ = loan_scenarios(*inputs)
    assert scenario(loan, "heat pumps only (COP 3.0)")["change_t"] > 0             # coal-heavy grid
    assert scenario(loan, "solar + heat pumps (COP 3.0)")["change_t"] < 0


def test_product_stages_sum_to_total_minus_capital_goods_and_travel(inputs):
    audit, _, cfg = inputs
    fp = product_footprint(audit, cfg).set_index("stage")
    stages = fp.drop(index=["PRODUCT FOOTPRINT (cradle-to-gate)", "CORPORATE INTENSITY (all scopes)"])
    expected = audit["tco2e"].sum() - stages.loc[["capital goods", "business travel"], "tco2e"].sum()
    assert stages.loc[stages["in_product_footprint"].astype(bool), "tco2e"].sum() == pytest.approx(expected)
    assert fp.loc["PRODUCT FOOTPRINT (cradle-to-gate)", "tco2e"] == pytest.approx(expected)


def test_cost_model_within_budget(inputs):
    costs = cost_model(inputs[2]).set_index("item")["kzt_per_year"]
    assert costs["TOTAL per year"] <= costs["CFO budget"]


def test_analysis_does_not_change_predictions():
    path = ROOT / "outputs" / "predictions.csv"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    analysis.main()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
