"""Local demo page:  streamlit run app.py

Two tabs. "Live run": upload a ledger CSV and run the pipeline on it (processing in src/demo.py).
"Pitch": the computed pitch numbers and charts (pitch/build_pitch.py) and a live green-loan
calculator. UI only, no classification logic here. Runs locally with no network calls
(.streamlit/config.toml switches off usage statistics and binds to localhost).
"""

import json

import pandas as pd
import streamlit as st

from pitch.build_pitch import BOILER_EFFICIENCY, SHARE_OF_GAS_HEAT_TO_HP, SOLAR_YIELD_KWH_PER_KWP, compute, green_loan
from src.demo import REQUIRED, UploadError, process, read_upload, validate
from src.load import ROOT

COLOURS = {
    "rule": "#d9f2d9",
    "ML fallback": "#fff4c2",
    "needs review": "#f8d0d0",
    "excluded": "#e6e6e6",
    "duplicate": "#e6e6e6",
}
TABLE = [
    "line_id",
    "description",
    "quantity",
    "unit",
    "category",
    "ef_id",
    "converted",
    "method",
    "tco2e",
    "review_flag",
    "status",
]
PITCH = ROOT / "pitch"


@st.cache_data(show_spinner="Running the pipeline...")
def run(data: bytes) -> dict:
    """Run the pipeline on uploaded bytes (cached per file)."""
    return process(read_upload(data))


@st.cache_data(show_spinner="Computing pitch numbers...")
def pitch_numbers() -> dict:
    """Pitch numbers computed live; the stress-test result is read from pitch_numbers.json."""
    numbers = compute(run_stress=False)  # the stress test takes ~20 s; its result is read from the JSON
    saved = PITCH / "pitch_numbers.json"
    if saved.exists():
        numbers["robustness"].update(
            {
                k: v
                for k, v in json.loads(saved.read_text(encoding="utf-8"))["robustness"].items()
                if k.startswith("stress")
            }
        )
    return numbers


# ----------------------------------------------------------------------------- live run
def live_tab():
    """Upload a ledger file and show the results, review queue and line details."""
    st.caption(
        "Runs on this laptop: rules + a local ML fallback, no cloud calls. Draft mode: lines that "
        "cannot be measured are listed under Needs review instead of stopping the run."
    )
    upload = st.file_uploader("Ledger CSV (comma or semicolon; UTF-8 or Windows-1251)", type=["csv", "txt"])
    if upload is None:
        st.info("Upload a ledger file with these columns: " + ", ".join(REQUIRED))
        return
    try:
        problems = validate(read_upload(upload.getvalue()))
        if problems:
            for p in problems:
                st.error(p)
            return
        res = run(upload.getvalue())
    except UploadError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # never show a traceback to the jury
        st.error(f"Could not process the file ({type(exc).__name__}): {exc}")
        return
    stats, rows = res["stats"], res["rows"]

    st.subheader(f"{upload.name} · {stats['lines']} lines · {stats['seconds']:.1f} s")
    if stats["renamed"]:
        st.warning("Some line_id values already exist in the train ledger; uploaded lines are shown as DEMO-<line_id>.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tCO2e", f"{stats['total_t']:,.2f}")
    c2.metric("Lines calculated", f"{stats['calculated']} of {stats['lines']}")
    c3.metric("Flagged for review", stats["review"])
    c4.metric("Activity-based / spend-based", f"{stats['activity_share']:.0%} / {1 - stats['activity_share']:.0%}")

    left, right = st.columns(2)
    for col, title, series in [
        (left, "By scope (tCO2e)", res["by_scope"]),
        (right, "By category (tCO2e)", res["by_category"]),
    ]:
        with col:
            st.markdown(f"**{title}**")
            frame = series.rename("tCO2e").to_frame()
            st.dataframe(frame.style.format("{:,.4f}"), width="stretch")
            st.bar_chart(frame)

    st.markdown("### Lines")
    st.caption("Green = rule · Yellow = ML fallback · Red = needs review · Grey = excluded / duplicate")
    table = rows[TABLE].rename(columns={"converted": "converted quantity", "tco2e": "tCO2e"})
    styled = (
        table.style
        # dark text on the pale row colours stays readable in Streamlit's light and dark themes
        .apply(lambda r: [f"background-color: {COLOURS.get(r['status'], '')}; color: #1a1a1a"] * len(r), axis=1).format(
            {"tCO2e": lambda v: "" if pd.isna(v) else f"{v:,.4f}"}
        )
    )
    st.dataframe(styled, width="stretch", hide_index=True)

    st.markdown("### Needs review")
    if res["review"].empty:
        st.success("No line needs review.")
    else:
        st.dataframe(
            res["review"][["line_id", "description", "quantity", "unit", "category", "reason", "review_flag"]],
            width="stretch",
            hide_index=True,
        )
    if not res["injection"].empty:
        st.markdown("### Instruction in text ignored")
        for r in res["injection"].itertuples(index=False):
            t = "" if pd.isna(r.tco2e) else f", {r.tco2e:,.4f} tCO2e"
            st.warning(
                f"**{r.line_id}**: instruction in the description was ignored. "
                f"Final category **{r.category}** ({r.ef_id}{t})."
            )

    st.markdown("### Line detail")
    line = rows.set_index("line_id").loc[st.selectbox("line_id", rows["line_id"].tolist())]
    d1, d2 = st.columns([1, 2])
    with d1:
        st.markdown(
            f"**Status:** {line['status']}  \n**Rule:** `{line['rule_id']}`  \n"
            f"**Category:** {line['category']}  \n**Factor:** `{line['ef_id'] or '-'}`"
            + (f" = {line['factor']} kgCO2e per unit" if pd.notna(line["factor"]) else "")
            + f"  \n**Method:** {line['method']}  \n**Confidence:** {line['confidence']}"
        )
    with d2:
        st.markdown(f"**Ledger:** {line['description']}  \n**Quantity:** {line['quantity']} {line['unit']}")
        if line["conversion"]:
            st.markdown(f"**Conversion:** {line['conversion']}")
        st.code(line["calculation"], language=None)
        st.markdown(f"**Reason:** {line['reason']}")
        if isinstance(line["review_flag"], str) and line["review_flag"]:
            st.markdown(f"**Review flag:** {line['review_flag']}")

    st.markdown("### Download")
    stem = upload.name.rsplit(".", 1)[0]
    b1, b2 = st.columns(2)
    b1.download_button(
        "Results CSV (line_id, category, tCO2e)",
        res["results"].to_csv(index=False).encode("utf-8-sig"),
        f"{stem}_results.csv",
        "text/csv",
    )
    b2.download_button(
        "Audit CSV (full trail)", res["audit"].to_csv(index=False).encode("utf-8-sig"), f"{stem}_audit.csv", "text/csv"
    )


# ----------------------------------------------------------------------------- pitch
def pitch_tab():
    """Pitch numbers, charts and the live green-loan calculator."""
    n = pitch_numbers()
    inv, prod, gl, m, rob = n["inventory"], n["product"], n["green_loan"], n["mistakes_caught"], n["robustness"]
    st.caption(
        "Every number is computed from outputs/audit.csv, the masked ledgers and emission_factors.csv "
        "(pitch/build_pitch.py)."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inventory 2025", f"{inv['total_tco2e']:,.0f} tCO2e")
    c2.metric(
        "Per kg of product (average)",
        f"{prod['kgco2e_per_kg']:.3f} kg CO2e",
        f"{prod['kgco2e_per_l']:.3f} per litre",
        delta_color="off",
    )
    c3.metric("Raw milk share", f"{n['hotspots'].get('raw milk', 0):.0%}")
    e = n["energy_headline"]
    c4.metric("Energy: spend vs emissions", f"{e['share_of_spend']:.1%} → {e['share_of_emissions']:.1%}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric(
        "Refrigerant leaks found",
        f"{m['refrigerant_tco2e']:,.0f} tCO2e",
        f"{m['refrigerant_lines']} lines",
        delta_color="off",
    )
    c6.metric(
        "Round trips with both legs",
        m["round_trip_lines"],
        f"+{m['round_trip_return_legs_tco2e']:.1f} tCO2e",
        delta_color="off",
    )
    c7.metric("Injections ignored (test set)", f"{rob['injection_lines_ignored']} / {rob['injection_lines_test']}")
    if "stress_checks" in rob:
        c8.metric("Stress test", f"{rob['stress_passed']} / {rob['stress_checks']}")
    if "highlight" in m:
        st.info(
            f"{m['highlight']['line_id']}: refrigerant refill hidden in a service act — {m['highlight']['calculation']}"
        )

    charts = [
        p
        for p in ("chart_scopes.png", "chart_hotspots.png", "chart_spend_vs_emissions.png", "chart_heat_pumps.png")
        if (PITCH / p).exists()
    ]
    if charts:
        cols = st.columns(2)
        for i, name in enumerate(charts):
            cols[i % 2].image(str(PITCH / name), width="stretch")
    else:
        st.info("Run `python pitch/build_pitch.py` to draw the charts.")

    st.markdown("### Green loan: try the assumptions")
    s1, s2, s3, s4 = st.columns(4)
    cop = s1.slider("Heat-pump seasonal COP", 2.0, 6.0, 3.0, 0.1)
    share = s2.slider("Share of boiler heat moved to heat pumps", 0, 100, int(SHARE_OF_GAS_HEAT_TO_HP * 100), 5) / 100
    mwp = s3.slider("Solar, MWp", 0.0, 10.0, 1.0, 0.5)
    eff = s4.slider("Boiler efficiency", 0.70, 0.98, BOILER_EFFICIENCY, 0.01)
    r = green_loan(
        gl["natural_gas_m3"],
        gl["grid_electricity_mwh"] * 1000,
        gl["grid_factor"],
        gl["gas_factor"],
        cop,
        share=share,
        efficiency=eff,
        solar_mwp=mwp,
        solar_yield=SOLAR_YIELD_KWH_PER_KWP,
    )
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Break-even COP", f"{r['break_even_cop']:.2f}")
    g2.metric("Heat pumps", f"{r['change_heat_pumps_t']:+,.0f} tCO2e/yr")
    g3.metric("Solar", f"{r['change_solar_t']:+,.0f} tCO2e/yr")
    g4.metric(
        "Total vs Scope 1+2",
        f"{r['change_total_t']:+,.0f} t",
        f"{r['change_total_t'] / gl['scope12_tco2e']:+.1%}",
        delta_color="inverse",
    )
    st.caption(
        f"Gas {gl['natural_gas_m3']:,.0f} m3 and grid {gl['grid_electricity_mwh']:,.0f} MWh from the 2025 audit; "
        f"factors {gl['grid_factor']} kg/kWh and {gl['gas_factor']} kg/m3 from emission_factors.csv; "
        f"solar yield {SOLAR_YIELD_KWH_PER_KWP:,} kWh/kWp. {gl['note']}"
    )


st.set_page_config(page_title="Carbon Copilot", layout="wide")
st.title("Dala Foods Carbon Copilot")
live, pitch = st.tabs(["Live run", "Pitch"])
with live:
    live_tab()
with pitch:
    pitch_tab()
