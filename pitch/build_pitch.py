"""Numbers and charts for the pitch:  python pitch/build_pitch.py

Reads outputs/audit.csv (run run.py first), the masked ledgers and emission_factors.csv, and writes
pitch/pitch_numbers.md, pitch/pitch_numbers.json and PNG charts. Every number is computed here; the
only typed-in values are the assumptions in the block below and the data-pack figures it cites.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.load import load_factors, load_ledgers  # noqa: E402

# ============================== ASSUMPTIONS (all typed-in inputs live here) ==============================
PRODUCT_T = 105_000              # DATA PACK (brief): tonnes of finished product per year
DENSITY_KG_PER_L = 1.03          # DATA PACK (factor-file note on EF_MILK_KG); per-litre = average product
GAS_NCV_MJ_PER_M3 = 34.0         # DATA PACK (factor-file note on EF_NG_M3)
BOILER_EFFICIENCY = 0.90         # ASSUMPTION: gas steam boiler, net
SHARE_OF_GAS_HEAT_TO_HP = 0.40   # ASSUMPTION: low-temperature share of boiler heat that heat pumps can take
COPS = [2.5, 3.0, 3.5, 4.0, 5.0] # ASSUMPTION: seasonal COPs to compare
SOLAR_YIELD_KWH_PER_KWP = 1300   # ASSUMPTION: annual yield per kWp in southern Kazakhstan
SOLAR_MWP = 1.0                  # ASSUMPTION: unit size for "tCO2e saved per MWp"
HIGHLIGHT_LINE = "L00131"        # the refrigerant refill hidden in a service act
# ==========================================================================================================

OUT = ROOT / "pitch"
GROUPS = [  # purchase group, rule_id prefixes (first match wins)
    ("raw milk", ("RAW_MILK",)), ("electricity", ("ELECTRICITY",)), ("natural gas", ("FUEL_NATURAL_GAS",)),
    ("district heat", ("DISTRICT_HEAT",)), ("refrigerants", ("REFRIGERANT",)),
    ("own-fleet fuel", ("FUEL_DIESEL_L", "FUEL_DIESEL_T", "FUEL_PETROL", "FUEL_LPG")),
    ("packaging", ("PACK_",)), ("capital goods", ("CAPEX_",)),
    ("services", ("SP_PROF", "SP_IT", "SP_TELECOM", "SP_CLEANING", "SP_CATERING", "SP_FINANCIAL", "SP_RENT",
                  "SP_OFFICE", "SP_MAINTENANCE", "ML_FALLBACK")),
]
ENERGY = ("electricity", "natural gas", "district heat")


def group_of(rule_id: str) -> str:
    for name, prefixes in GROUPS:
        if rule_id.startswith(prefixes):
            return name
    return "other"


# ----------------------------------------------------------------------------- data
def load():
    """Audit rows joined with ledger net spend and injection flags; factors."""
    audit = pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")
    ledger = load_ledgers()[["line_id", "net_kzt", "injection", "unit_code"]]
    return audit.merge(ledger, on="line_id", how="left"), load_factors()


# ----------------------------------------------------------------------------- numbers
def inventory(a):
    counted = a[a["method"].isin(["activity", "spend"])]
    total = counted["tco2e"].sum()
    scope = counted.assign(scope=counted["category"].str[:2]).groupby("scope")["tco2e"].sum()
    activity = counted.loc[counted["method"] == "activity", "tco2e"].sum()
    return {
        "total_tco2e": total,
        "test_only_tco2e": counted.loc[counted["set"] == "test", "tco2e"].sum(),
        "by_scope_tco2e": scope.to_dict(),
        "by_category_tco2e": counted.groupby("category")["tco2e"].sum().sort_values(ascending=False).to_dict(),
        "activity_share": activity / total, "spend_share": 1 - activity / total,
        "lines": len(a), "lines_flagged": int(a["review_flag"].fillna("").ne("").sum()),
    }


def product_footprint(total_t):
    per_kg = total_t / PRODUCT_T  # tCO2e per t = kg CO2e per kg
    return {"kgco2e_per_kg": per_kg, "kgco2e_per_l": per_kg * DENSITY_KG_PER_L,
            "note": f"average across all products ({PRODUCT_T:,} t); per litre at {DENSITY_KG_PER_L} kg/l"}


def purchase_groups(a):
    counted = a[a["method"].isin(["activity", "spend"])].assign(group=lambda d: d["rule_id"].map(group_of))
    g = counted.groupby("group").agg(net_kzt=("net_kzt", "sum"), tco2e=("tco2e", "sum"))
    g["share_of_spend"] = g["net_kzt"] / g["net_kzt"].sum()
    g["share_of_emissions"] = g["tco2e"] / g["tco2e"].sum()
    g["tco2e_per_mkzt"] = g["tco2e"] / (g["net_kzt"] / 1e6)
    order = [n for n, _ in GROUPS] + ["other"]
    return g.reindex([o for o in order if o in g.index])


def green_loan(gas_m3, grid_kwh, ef_grid, ef_gas, cop, share=SHARE_OF_GAS_HEAT_TO_HP,
               efficiency=BOILER_EFFICIENCY, ncv=GAS_NCV_MJ_PER_M3, solar_mwp=0.0, solar_yield=SOLAR_YIELD_KWH_PER_KWP):
    """Change in tCO2e/yr when `share` of boiler heat moves to heat pumps (and optional solar)."""
    heat_per_m3 = ncv / 3.6 * efficiency                       # useful kWh of heat per m3 of gas
    gas_saved = gas_m3 * share
    heat_kwh = gas_saved * heat_per_m3
    hp_kwh = heat_kwh / cop
    solar_kwh = solar_mwp * 1000 * solar_yield
    change_hp = (hp_kwh * ef_grid - gas_saved * ef_gas) / 1000
    change_solar = -solar_kwh * ef_grid / 1000
    return {"break_even_cop": heat_per_m3 * ef_grid / ef_gas, "gas_saved_m3": gas_saved, "heat_kwh": heat_kwh,
            "heat_pump_kwh": hp_kwh, "change_heat_pumps_t": change_hp, "solar_kwh": solar_kwh,
            "change_solar_t": change_solar, "change_total_t": change_hp + change_solar}


def loan_numbers(a, factors):
    gas = a[a["rule_id"] == "FUEL_NATURAL_GAS"]
    grid = a[a["rule_id"] == "ELECTRICITY"]
    ef_grid, ef_gas = factors["EF_GRID_KZ_KWH"]["value"], factors["EF_NG_M3"]["value"]
    gas_m3, grid_kwh = gas["activity_qty"].sum(), grid["activity_qty"].sum()
    s12 = a.loc[a["category"].str.startswith(("S1", "S2")), "tco2e"].sum()
    table = []
    for cop in COPS:
        r = green_loan(gas_m3, grid_kwh, ef_grid, ef_gas, cop)
        table.append({"cop": cop, "change_t": r["change_heat_pumps_t"], "change_pct_scope12": r["change_heat_pumps_t"] / s12})
    solar = green_loan(gas_m3, grid_kwh, ef_grid, ef_gas, 3.0, share=0, solar_mwp=SOLAR_MWP)
    return {
        "natural_gas_m3": gas_m3, "natural_gas_tco2e": gas["tco2e"].sum(),
        "grid_electricity_mwh": grid_kwh / 1000, "grid_electricity_tco2e": grid["tco2e"].sum(),
        "scope12_tco2e": s12, "grid_factor": ef_grid, "gas_factor": ef_gas,
        "break_even_cop": solar["break_even_cop"],  # depends only on NCV, efficiency and the two factors
        "share_of_gas_heat_to_heat_pumps": SHARE_OF_GAS_HEAT_TO_HP, "cop_table": table,
        "solar_tco2e_saved_per_mwp": -solar["change_solar_t"], "solar_yield_kwh_per_kwp": SOLAR_YIELD_KWH_PER_KWP,
        "note": "High-temperature steam (pasteurisation, UHT) cannot fully move to heat pumps; the best use is "
                "low-temperature heat (CIP, hot water, pre-heating) and heat recovery from refrigeration.",
    }


def mistakes(a):
    ref = a[a["rule_id"] == "REFRIGERANT"]
    hl = a.set_index("line_id").loc[HIGHLIGHT_LINE] if HIGHLIGHT_LINE in set(a["line_id"]) else None
    gwp = {"EF_R404A_KG": 3943, "EF_R134A_KG": 1300, "EF_R410A_KG": 1924, "EF_R744_KG": 1}
    flights = a[a["rule_id"] == "TRAVEL_FLIGHT"]
    round_trips, extra_t = 0, 0.0
    for reason, t in zip(flights["reason"], flights["tco2e"]):
        legs = json.loads(reason.split("Leg calculations: ")[1])
        if len(legs) >= 2 and legs[0]["from"] == legs[-1]["to"]:
            round_trips += 1
            extra_t += t - legs[0]["tco2e"]  # what counting only the outbound leg would have missed
    out = {"refrigerant_lines": len(ref), "refrigerant_tco2e": ref["tco2e"].sum(),
           "refrigerant_hidden_in_service_lines": int(ref["unit_code"].eq("усл").sum()),
           "refrigerant_hidden_tco2e": ref.loc[ref["unit_code"].eq("усл"), "tco2e"].sum(),
           "flight_lines": len(flights), "round_trip_lines": round_trips, "round_trip_return_legs_tco2e": extra_t}
    if hl is not None:
        out["highlight"] = {"line_id": HIGHLIGHT_LINE, "kg": hl["activity_qty"], "ef_id": hl["ef_id"],
                            "tco2e": hl["tco2e"],
                            "calculation": f"{hl['activity_qty']:g} kg x {gwp.get(hl['ef_id'], '?')} / 1000 = {hl['tco2e']:.4f} tCO2e"}
    return out


def robustness(a, run_stress=True):
    test = a[a["set"] == "test"]
    inj = test[test["injection"].fillna(False).astype(bool)]
    ignored = inj["review_flag"].fillna("").str.contains("instruction-like text ignored") & inj["category"].ne("EXCLUDE")
    out = {"injection_lines_test": len(inj), "injection_lines_ignored": int(ignored.sum())}
    if run_stress:
        import stress_test
        results = stress_test.run_all()
        out["stress_checks"] = len(results)
        out["stress_passed"] = sum(ok for *_, ok, _ in results)
    return out


def compute(run_stress=True):
    a, factors = load()
    inv = inventory(a)
    groups = purchase_groups(a)
    energy = groups.loc[[g for g in ENERGY if g in groups.index]]
    return {
        "inventory": inv,
        "product": product_footprint(inv["total_tco2e"]),
        "purchase_groups": groups.reset_index().to_dict(orient="records"),
        "energy_headline": {"share_of_spend": energy["share_of_spend"].sum(),
                            "share_of_emissions": energy["share_of_emissions"].sum()},
        "hotspots": groups["share_of_emissions"].sort_values(ascending=False).head(5).to_dict(),
        "green_loan": loan_numbers(a, factors),
        "mistakes_caught": mistakes(a),
        "robustness": robustness(a, run_stress),
    }


# ----------------------------------------------------------------------------- charts
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#5f5e58", "#e3e2dd", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1-2, validated (dataviz validate_palette.js)


def _axes(title, subtitle=""):
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 16})
    fig, ax = plt.subplots(figsize=(13.33, 7.5), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    fig.suptitle(title, x=0.06, y=0.95, ha="left", fontsize=28, fontweight="bold", color=INK)
    if subtitle:
        fig.text(0.06, 0.875, subtitle, ha="left", fontsize=16, color=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=16, length=0)
    return fig, ax


def _save(fig, name):
    fig.subplots_adjust(left=0.2, right=0.95, top=0.8, bottom=0.12)
    fig.savefig(OUT / name, facecolor=SURFACE)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return name


def chart_scopes(n):
    inv = n["inventory"]
    scopes = ["S1", "S2", "S3"]
    vals = [inv["by_scope_tco2e"].get(s, 0) for s in scopes]
    labels = ["Scope 1\nown fuel, refrigerants", "Scope 2\nelectricity, heat", "Scope 3\npurchases"]
    s3 = vals[2] / sum(vals)
    fig, ax = _axes(f"Scope 3 is {s3:.0%} of the {inv['total_tco2e']:,.0f} tCO2e inventory",
                    "2025, train + test lines, tCO2e")
    ax.barh(labels[::-1], vals[::-1], color=BLUE, height=0.5)
    for y, v in enumerate(vals[::-1]):
        ax.text(v + max(vals) * 0.01, y, f"{v:,.0f}  ({v / sum(vals):.0%})", va="center", fontsize=18, color=INK)
    ax.set_xlim(0, max(vals) * 1.25)
    ax.xaxis.set_visible(False)
    return _save(fig, "chart_scopes.png")


def _pct(x):
    return "<1%" if 0 < x < 0.005 else f"{x:.0%}"


def chart_spend_vs_emissions(n):
    g = pd.DataFrame(n["purchase_groups"]).set_index("group")
    e = n["energy_headline"]
    fig, ax = _axes(f"Energy is {e['share_of_spend']:.0%} of spend but {e['share_of_emissions']:.0%} of emissions",
                    "Share of net spend vs share of tCO2e by purchase group")
    idx = list(range(len(g)))[::-1]
    h = 0.38
    ax.barh([i + h / 2 for i in idx], g["share_of_spend"], height=h, color=BLUE, label="share of net spend")
    ax.barh([i - h / 2 for i in idx], g["share_of_emissions"], height=h, color=ORANGE, label="share of tCO2e")
    ax.set_yticks(idx, g.index)
    for i, (s, em) in zip(idx, zip(g["share_of_spend"], g["share_of_emissions"])):
        ax.text(s + 0.005, i + h / 2, _pct(s), va="center", fontsize=13, color=INK)
        ax.text(em + 0.005, i - h / 2, _pct(em), va="center", fontsize=13, color=INK)
    ax.xaxis.set_visible(False)
    ax.legend(loc="lower right", frameon=False, fontsize=16)
    return _save(fig, "chart_spend_vs_emissions.png")


def chart_hotspots(n):
    hs = n["hotspots"]
    names, shares = list(hs)[::-1], list(hs.values())[::-1]
    top = list(hs)[0]
    fig, ax = _axes(f"{top.capitalize()} is {hs[top]:.0%} of the footprint", "Top 5 sources, share of total tCO2e")
    ax.barh(names, shares, color=BLUE, height=0.5)
    for y, s in enumerate(shares):
        ax.text(s + 0.008, y, f"{s:.1%}", va="center", fontsize=18, color=INK)
    ax.set_xlim(0, max(shares) * 1.18)
    ax.xaxis.set_visible(False)
    return _save(fig, "chart_hotspots.png")


def chart_heat_pumps(n):
    gl = n["green_loan"]
    gas_m3 = gl["natural_gas_m3"]
    cops = [2.0 + i * 0.05 for i in range(81)]
    change = [green_loan(gas_m3, 0, gl["grid_factor"], gl["gas_factor"], c)["change_heat_pumps_t"] for c in cops]
    be = gl["break_even_cop"]
    fig, ax = _axes(f"Heat pumps cut emissions only above COP {be:.2f}",
                    f"Change in tCO2e/yr if {SHARE_OF_GAS_HEAT_TO_HP:.0%} of boiler heat moves to heat pumps "
                    f"(grid {gl['grid_factor']} kg/kWh)")
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.axvline(be, color=MUTED, linewidth=1.5, linestyle="--")
    ax.plot(cops, change, color=BLUE, linewidth=2.5)
    ax.scatter([r["cop"] for r in gl["cop_table"]], [r["change_t"] for r in gl["cop_table"]], color=BLUE, s=70, zorder=3)
    for r in gl["cop_table"]:
        near_line = abs(r["cop"] - be) < 0.2  # keep the label off the break-even line
        ax.annotate(f"{r['change_t']:+,.0f} t", (r["cop"], r["change_t"]), textcoords="offset points",
                    xytext=(-62 if near_line else 8, 10), fontsize=14, color=INK)
    ax.text(be + 0.05, ax.get_ylim()[1] * 0.85, f"break-even COP {be:.2f}", fontsize=15, color=INK)
    ax.set_xlabel("seasonal COP", fontsize=16, color=MUTED)
    ax.set_ylabel("change in tCO2e per year", fontsize=16, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    return _save(fig, "chart_heat_pumps.png")


# ----------------------------------------------------------------------------- report
def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if hasattr(x, "item"):
        x = x.item()
    return round(x, 6) if isinstance(x, float) else x


def markdown(n, charts):
    inv, p, gl, m, r = n["inventory"], n["product"], n["green_loan"], n["mistakes_caught"], n["robustness"]
    lines = ["# Pitch numbers (computed by pitch/build_pitch.py from outputs/audit.csv)", "",
             "## Inventory 2025 (train + test)",
             f"- Total: **{inv['total_tco2e']:,.1f} tCO2e**; test lines only: {inv['test_only_tco2e']:,.1f} tCO2e",
             "- By scope: " + ", ".join(f"{s} {v:,.1f} t ({v / inv['total_tco2e']:.1%})" for s, v in sorted(inv["by_scope_tco2e"].items())),
             f"- Activity-based {inv['activity_share']:.1%} / spend-based {inv['spend_share']:.1%}",
             f"- Lines: {inv['lines']:,}; flagged for review: {inv['lines_flagged']:,}", "",
             "| Category | tCO2e |", "|---|---|"] + [f"| {k} | {v:,.1f} |" for k, v in inv["by_category_tco2e"].items()] + [
             "", "## Footprint per product",
             f"- **{p['kgco2e_per_kg']:.3f} kg CO2e per kg**, {p['kgco2e_per_l']:.3f} kg CO2e per litre — {p['note']}", "",
             "## Carbon per tenge",
             f"- Energy (electricity, gas, heat): **{n['energy_headline']['share_of_spend']:.1%} of spend, "
             f"{n['energy_headline']['share_of_emissions']:.1%} of emissions**", "",
             "| Group | Net spend, m KZT | Share of spend | tCO2e | Share of tCO2e | tCO2e per m KZT |", "|---|---|---|---|---|---|"]
    for g in n["purchase_groups"]:
        lines.append(f"| {g['group']} | {g['net_kzt'] / 1e6:,.1f} | {g['share_of_spend']:.1%} | {g['tco2e']:,.1f} | "
                     f"{g['share_of_emissions']:.1%} | {g['tco2e_per_mkzt']:,.2f} |")
    lines += ["", "## Hotspots (top 5)"] + [f"- {k}: {v:.1%}" for k, v in n["hotspots"].items()]
    lines += ["", "## Green loan",
              f"- Natural gas: {gl['natural_gas_m3']:,.0f} m3 = {gl['natural_gas_tco2e']:,.1f} tCO2e; "
              f"grid electricity: {gl['grid_electricity_mwh']:,.0f} MWh = {gl['grid_electricity_tco2e']:,.1f} tCO2e",
              f"- **Break-even COP {gl['break_even_cop']:.2f}** (gas {GAS_NCV_MJ_PER_M3} MJ/m3, boiler {BOILER_EFFICIENCY:.0%}, "
              f"grid {gl['grid_factor']} kg/kWh, gas {gl['gas_factor']} kg/m3)",
              f"- If {gl['share_of_gas_heat_to_heat_pumps']:.0%} of boiler heat moves to heat pumps:", "",
              "| COP | Change tCO2e/yr | vs Scope 1+2 |", "|---|---|---|"]
    lines += [f"| {t['cop']} | {t['change_t']:+,.0f} | {t['change_pct_scope12']:+.1%} |" for t in gl["cop_table"]]
    lines += ["", f"- Solar: **{gl['solar_tco2e_saved_per_mwp']:,.0f} tCO2e saved per MWp** per year "
                  f"({gl['solar_yield_kwh_per_kwp']:,} kWh/kWp)", f"- {gl['note']}", "",
              "## Last year's mistakes caught",
              f"- Refrigerant refills = leaks: {m['refrigerant_lines']} lines, **{m['refrigerant_tco2e']:,.1f} tCO2e**; "
              f"{m['refrigerant_hidden_in_service_lines']} of them hidden in service acts (unit усл): "
              f"{m['refrigerant_hidden_tco2e']:,.1f} tCO2e"]
    if "highlight" in m:
        h = m["highlight"]
        lines.append(f"- {h['line_id']}: refill hidden in a service act — {h['calculation']}")
    lines += [f"- Flights: {m['flight_lines']} tickets, {m['round_trip_lines']} round trips counted with both legs "
              f"(+{m['round_trip_return_legs_tco2e']:,.2f} tCO2e that one-way counting would miss)", "",
              "## Robustness",
              f"- Injection lines in the test set: {r['injection_lines_test']}, ignored: {r['injection_lines_ignored']}"]
    if "stress_checks" in r:
        lines.append(f"- Stress test: {r['stress_passed']}/{r['stress_checks']} checks pass")
    lines += ["", "Charts: " + ", ".join(charts)]
    return "\n".join(lines) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    numbers = compute(run_stress="--no-stress" not in sys.argv)
    charts = [chart_scopes(numbers), chart_spend_vs_emissions(numbers), chart_hotspots(numbers), chart_heat_pumps(numbers)]
    (OUT / "pitch_numbers.json").write_text(json.dumps(_clean(numbers), indent=2, ensure_ascii=False), encoding="utf-8")
    md = markdown(numbers, charts)
    (OUT / "pitch_numbers.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
