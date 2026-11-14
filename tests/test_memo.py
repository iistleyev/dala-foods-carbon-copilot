"""Memo items: shown next to the inventory, never added to its totals or to predictions.csv."""
import pandas as pd
import pytest

from run import summarise
from src.load import ROOT, load_factors
from src.memo import memo_items, non_co2_tco2e


@pytest.fixture(scope="module")
def audit():
    return pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")


def memo(audit):
    return memo_items(audit, load_factors()).set_index("category")["tco2e"]


def test_market_based_scope2_equals_location_based(audit):
    s2 = audit.loc[audit["category"].str.startswith("S2"), "tco2e"].sum()
    assert memo(audit)["Scope 2 market-based"] == pytest.approx(s2)


def test_cat12_is_packaging_mass_times_case_landfill_factor(audit):
    pack_t = audit.loc[audit["rule_id"].str.startswith("PACK_"), "activity_qty"].sum() / 1000
    assert memo(audit)["Scope 3 Cat 12 end of life of sold packaging (indicative)"] == pytest.approx(pack_t * 0.580)


def test_non_co2_by_hand_for_1000_litres_of_diesel():
    one = pd.DataFrame({"rule_id": ["FUEL_DIESEL_L"], "activity_qty": [1000.0]})
    tj = 1000 * 0.84 * 43.0 / 1e6                        # density x NCV
    expected = tj * (3.9 * 28 + 3.9 * 265) / 1000         # IPCC Table 3.2.2 x GWP AR5, kg -> t
    assert non_co2_tco2e(one)["Scope 1"] == pytest.approx(expected)


def test_cat3_is_disclosed_not_estimated(audit):
    assert pd.isna(memo(audit)["Scope 3 Cat 3 fuel- and energy-related activities"])


def test_memo_rows_are_not_in_the_total(audit):
    s = summarise(audit)
    assert s.loc[s["scope"] == "TOTAL", "tco2e"].item() == pytest.approx(audit["tco2e"].sum(), abs=1e-3)
    assert (s["scope"] == "MEMO").sum() == 5
    assert s.index[s["scope"] == "TOTAL"].item() < s.index[s["scope"] == "MEMO"].min()   # memo below TOTAL
    assert not s["basis"].fillna("").str.startswith(("=", "+", "@")).any()                # safe in Excel
