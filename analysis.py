"""Answers for the three Inbox requests, built on the pipeline's audit trail.

Run after run.py:   python analysis.py   -> outputs/loan_scenarios.csv
                                            outputs/product_footprint.csv
                                            outputs/cost_model.csv

It never changes predictions.csv or audit.csv. All activity data come from outputs/audit.csv,
all factors from emission_factors.csv, all other inputs from scenarios.yaml (assumptions labelled).
"""
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"

# rule_id prefix -> life-cycle stage, used for the product footprint breakdown.
STAGES = [
    ("RAW_MILK", "raw milk"),
    ("PACK_", "packaging"),
    ("ING_", "ingredients"), ("SP_INGREDIENTS", "ingredients"),
    ("CHEM_", "cleaning chemicals"),
    ("ELECTRICITY", "energy: electricity"),
    ("FUEL_NATURAL_GAS", "energy: natural gas"),
    ("DISTRICT_HEAT", "energy: district heat"),
    ("REFRIGERANT", "refrigerant leaks"),
    ("FUEL_DIESEL_HIRED", "transport"), ("FREIGHT_", "transport"),
    ("FUEL_", "own fleet fuel"),
    ("WATER_", "water and waste"), ("WASTE", "water and waste"),
    ("CAPEX_", "capital goods"),
    ("TRAVEL_", "business travel"),
    ("SP_", "services"), ("ML_FALLBACK", "services"),
]


def stage_of(rule_id: str) -> str:
    for prefix, stage in STAGES:
        if rule_id.startswith(prefix):
            return stage
    return "excluded"


def load():
    audit = pd.read_csv(OUT / "audit.csv", encoding="utf-8-sig")
    if audit["method"].eq("review").any() or audit["tco2e"].isna().any():
        sys.exit("audit.csv has unresolved rows: run run.py and clear the review queue first.")
    ef = pd.read_csv(ROOT / "emission_factors.csv", encoding="utf-8-sig").set_index("ef_id")["kgCO2e_per_unit"]
    with open(ROOT / "scenarios.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return audit, ef, cfg


# ------------------------------------------------------------------------------------- 1. Bank
def loan_scenarios(audit, ef, cfg):
    """Scope 1+2 after rooftop solar and heat pumps, location-based, using the case factors."""
    grid_kwh = audit.loc[audit["rule_id"] == "ELECTRICITY", "activity_qty"].sum()
    gas_m3 = audit.loc[audit["rule_id"] == "FUEL_NATURAL_GAS", "activity_qty"].sum()
    s1 = audit.loc[audit["category"].str.startswith("S1"), "tco2e"].sum()
    s2 = audit.loc[audit["category"].str.startswith("S2"), "tco2e"].sum()
    total = audit["tco2e"].sum()
    ef_grid, ef_gas = ef["EF_GRID_KZ_KWH"], ef["EF_NG_M3"]

    sol, hp = cfg["solar"], cfg["heat_pump"]
    pv_kwh = sol["capacity_kwp"] * sol["specific_yield_kwh_per_kwp"]
    heat_per_m3_kwh = hp["gas_ncv_mj_per_m3"] / 3.6 * hp["boiler_efficiency"]  # useful heat per m3 of gas
    gas_replaced_m3 = gas_m3 * hp["share_of_boiler_heat"]
    heat_replaced_kwh = gas_replaced_m3 * heat_per_m3_kwh
    breakeven_cop = heat_per_m3_kwh * ef_grid / ef_gas
    hp_kwth = heat_replaced_kwh / hp["full_load_hours"]
    capex_pv = sol["capacity_kwp"] * sol["capex_kzt_per_kwp"]
    capex_hp = hp_kwth * hp["capex_kzt_per_kwth"]

    def row(name, solar_on, cop):
        hp_kwh = heat_replaced_kwh / cop if cop else 0.0
        gas_cut = gas_replaced_m3 if cop else 0.0
        pv = pv_kwh if solar_on else 0.0
        d_s2 = (hp_kwh - pv) * ef_grid / 1000
        d_s1 = -gas_cut * ef_gas / 1000
        delta = d_s1 + d_s2
        capex = (capex_pv if solar_on else 0) + (capex_hp if cop else 0)
        return {
            "scenario": name, "solar_kwh": pv, "heat_pump_cop": cop or "",
            "gas_saved_m3": gas_cut, "heat_pump_kwh": hp_kwh,
            "scope1_t": s1 + d_s1, "scope2_t": s2 + d_s2, "change_t": delta,
            "change_pct_scope12": delta / (s1 + s2), "change_pct_total": delta / total,
            "capex_kzt_estimate": capex,
            "kzt_per_t_avoided_per_year": capex / -delta if delta < 0 else "",
        }

    rows = [row("baseline 2025", False, None), row("solar only", True, None),
            row(f"heat pumps only (COP {hp['cop_base']})", False, hp["cop_base"])]
    rows += [row(f"solar + heat pumps (COP {c})", True, c) for c in hp["cop_range"]]
    out = pd.DataFrame(rows)
    facts = {
        "grid electricity 2025, kWh": grid_kwh, "natural gas 2025, m3": gas_m3,
        "solar generation, kWh/yr": pv_kwh, "gas replaced by heat pumps, m3/yr": gas_replaced_m3,
        "heat pump size, kWth": hp_kwth, "break-even COP (heat pump vs gas boiler)": breakeven_cop,
        "capex estimate, KZT": capex_pv + capex_hp, "loan, KZT": cfg["loan"]["amount_kzt"],
    }
    return out, facts


# ------------------------------------------------------------------------------------ 2. Retailer
def product_footprint(audit, cfg):
    p = cfg["product"]
    a = audit[audit["tco2e"] != 0].assign(stage=lambda d: d["rule_id"].map(stage_of))
    by_stage = a.groupby("stage")["tco2e"].sum().sort_values(ascending=False)
    kg_product = p["finished_product_t"] * 1000
    out = pd.DataFrame({"stage": by_stage.index, "tco2e": by_stage.values})
    out["in_product_footprint"] = ~out["stage"].isin(p["exclude_stages"])
    out["kgco2e_per_kg"] = out["tco2e"] * 1000 / kg_product
    out["kgco2e_per_l"] = out["kgco2e_per_kg"] * p["density_kg_per_l"]
    out["share_of_product_footprint"] = (out["tco2e"] / out.loc[out["in_product_footprint"], "tco2e"].sum()
                                         ).where(out["in_product_footprint"], 0.0)
    prod = out[out["in_product_footprint"]]
    totals = pd.DataFrame([
        {"stage": "PRODUCT FOOTPRINT (cradle-to-gate)", "tco2e": prod["tco2e"].sum(),
         "in_product_footprint": True, "kgco2e_per_kg": prod["kgco2e_per_kg"].sum(),
         "kgco2e_per_l": prod["kgco2e_per_l"].sum(), "share_of_product_footprint": 1.0},
        {"stage": "CORPORATE INTENSITY (all scopes)", "tco2e": out["tco2e"].sum(),
         "in_product_footprint": False, "kgco2e_per_kg": out["kgco2e_per_kg"].sum(),
         "kgco2e_per_l": out["kgco2e_per_l"].sum(), "share_of_product_footprint": ""},
    ])
    return pd.concat([out, totals], ignore_index=True)


# ------------------------------------------------------------------------------------------ 3. CFO
def cost_model(cfg):
    c = cfg["cost_model"]
    rows = [{"item": i["item"], "days": i["days"], "day_rate_kzt": i["day_rate_kzt"],
             "kzt_per_year": i["days"] * i["day_rate_kzt"]} for i in c["items"]]
    out = pd.DataFrame(rows)
    sub = out["kzt_per_year"].sum()
    out = pd.concat([out, pd.DataFrame([
        {"item": f"Contingency {c['contingency_share']:.0%}", "kzt_per_year": sub * c["contingency_share"]},
        {"item": "TOTAL per year", "kzt_per_year": sub * (1 + c["contingency_share"])},
        {"item": "CFO budget", "kzt_per_year": c["budget_kzt"]},
    ])], ignore_index=True)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    audit, ef, cfg = load()
    loan, facts = loan_scenarios(audit, ef, cfg)
    footprint = product_footprint(audit, cfg)
    costs = cost_model(cfg)
    loan.round(4).to_csv(OUT / "loan_scenarios.csv", index=False, encoding="utf-8-sig")
    footprint.round(4).to_csv(OUT / "product_footprint.csv", index=False, encoding="utf-8-sig")
    costs.round(0).to_csv(OUT / "cost_model.csv", index=False, encoding="utf-8-sig")

    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.float_format", "{:,.3f}".format):
        print("=== Bank: green loan scenarios (location-based, case factors) ===")
        for k, v in facts.items():
            print(f"  {k}: {v:,.2f}")
        print(loan[["scenario", "scope1_t", "scope2_t", "change_t", "change_pct_scope12",
                    "change_pct_total", "kzt_per_t_avoided_per_year"]].to_string(index=False))
        print("\n=== Retailer: product footprint per kg / per litre ===")
        print(footprint[["stage", "tco2e", "kgco2e_per_kg", "kgco2e_per_l", "share_of_product_footprint"]]
              .to_string(index=False))
        print("\n=== CFO: annual running cost ===")
        print(costs.to_string(index=False))
    print("\nWrote outputs/loan_scenarios.csv, outputs/product_footprint.csv, outputs/cost_model.csv")


if __name__ == "__main__":
    main()
