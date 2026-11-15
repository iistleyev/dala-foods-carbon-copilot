"""Memo items reported NEXT TO the inventory, never added to it or to predictions.csv.

They answer what the GHG Protocol / Scope 2 and Scope 3 guidance ask us to show beyond the case's
11 categories, using only the case factor file plus IPCC defaults from the protocols folder:
  1. Scope 2 market-based. Dala buys no energy certificates and has no supplier-specific factor, and no
     residual mix is published for Kazakhstan, so the Scope 2 Guidance hierarchy falls back to the grid
     average: market-based = location-based.
  2. Scope 3 Cat 12 (end of life of sold packaging), indicative: packaging bought in 2025 is taken as
     packaging sold, all of it to landfill, at the case's own landfill factor.
  3. CH4 and N2O from fuel combustion: the case fuel factors are CO2 only (hard rule 2 keeps them as
     given), so the size of the missing gases is shown here with IPCC 2006 Tier 1 defaults.
  4. Scope 3 Cat 3 (well-to-tank of fuels, grid losses): not estimated, no factor in the case.
"""

import pandas as pd

GWP_AR5 = {"CH4": 28, "N2O": 265}  # 100-year, IPCC AR5: the GWP set the case uses for refrigerants

# Energy per activity unit, TJ: density (factor-file notes) x net calorific value (IPCC Vol. 2 Ch. 1, Table 1.2).
# CH4 and N2O, kg per TJ: IPCC Vol. 2 Table 3.2.2 (road transport) and Table 2.3 (manufacturing boilers).
# fmt: off
FUELS = {
    #  rule_id               TJ per unit             CH4   N2O   scope
    "FUEL_DIESEL_L":     (0.84 * 43.0 / 1e6,     3.9,  3.9, "Scope 1"),
    "FUEL_DIESEL_T":     (43.0 / 1e3,            3.9,  3.9, "Scope 1"),
    "FUEL_PETROL":       (0.745 * 44.3 / 1e6,   33.0,  3.2, "Scope 1"),
    "FUEL_LPG":          (47.3 / 1e6,           62.0,  0.2, "Scope 1"),
    "FUEL_NATURAL_GAS":  (34 / 1e6,              1.0,  0.1, "Scope 1"),
    "FUEL_DIESEL_HIRED": (0.84 * 43.0 / 1e6,     3.9,  3.9, "Scope 3 Cat 4"),
}
# fmt: on


def non_co2_tco2e(audit: pd.DataFrame) -> dict:
    """{scope: tCO2e of CH4 + N2O} from the fuel quantities in the audit (activity_qty in l, t, kg or m3)."""
    out = {}
    for rule_id, (tj_per_unit, ch4, n2o, scope) in FUELS.items():
        tj = audit.loc[audit["rule_id"] == rule_id, "activity_qty"].sum() * tj_per_unit
        out[scope] = out.get(scope, 0.0) + tj * (ch4 * GWP_AR5["CH4"] + n2o * GWP_AR5["N2O"]) / 1000
    return out


def memo_items(audit: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Memo rows: market-based Scope 2, Cat 12 estimate, CH4/N2O, Cat 3 note."""
    s2 = audit.loc[audit["category"].str.startswith("S2"), "tco2e"].sum()
    pack_t = audit.loc[audit["rule_id"].str.startswith("PACK_"), "activity_qty"].sum() / 1000
    landfill = factors["EF_WASTE_LANDFILL_T"]["value"]  # kg CO2e per t
    gas = non_co2_tco2e(audit)
    total = audit["tco2e"].sum()
    rows = [
        (
            "Scope 2 market-based",
            s2,
            "Equal to location-based: no certificates, no supplier factor, no residual mix for Kazakhstan "
            "(Scope 2 Guidance)",
        ),
        (
            "Scope 3 Cat 12 end of life of sold packaging (indicative)",
            pack_t * landfill / 1000,
            f"{pack_t:,.0f} t packaging bought = sold, all to landfill x EF_WASTE_LANDFILL_T",
        ),
        (
            "CH4 + N2O from fuel combustion, Scope 1",
            gas.get("Scope 1", 0.0),
            "not in the CO2-only case factors; IPCC 2006 Tables 3.2.2 / 2.3, GWP AR5",
        ),
        ("CH4 + N2O from fuel combustion, Scope 3 Cat 4 (hired carrier)", gas.get("Scope 3 Cat 4", 0.0), "as above"),
        (
            "Scope 3 Cat 3 fuel- and energy-related activities",
            None,
            "not estimated: no well-to-tank or grid-loss factor in the case files",
        ),
    ]
    out = pd.DataFrame(rows, columns=["category", "tco2e", "basis"])
    out["share_of_total"] = out["tco2e"] / total
    out.insert(0, "scope", "MEMO")
    return out
