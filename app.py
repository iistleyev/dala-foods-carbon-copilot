"""Live demo: run the Carbon Copilot pipeline on a new ledger file.   streamlit run app.py

UI only. All processing is src/demo.py, which calls the existing run_pipeline. Runs locally:
no network calls (Streamlit usage statistics are switched off in .streamlit/config.toml).
"""
import pandas as pd
import streamlit as st

from src.demo import REQUIRED, UploadError, process, read_upload, validate

COLOURS = {"rule": "#d9f2d9", "ML fallback": "#fff4c2", "needs review": "#f8d0d0",
           "excluded": "#e6e6e6", "duplicate": "#e6e6e6"}
TABLE = ["line_id", "description", "quantity", "unit", "category", "ef_id", "converted", "method",
         "tco2e", "review_flag", "status"]

st.set_page_config(page_title="Carbon Copilot: live run", layout="wide")
st.title("Dala Foods Carbon Copilot: live run on new data")
st.caption("Runs on this laptop: rules + a local ML fallback, no cloud calls. Draft mode: lines that "
           "cannot be measured are listed under Needs review instead of stopping the run.")


@st.cache_data(show_spinner="Running the pipeline...")
def run(data: bytes) -> dict:
    return process(read_upload(data))


upload = st.file_uploader("Ledger CSV (comma or semicolon; UTF-8 or Windows-1251)", type=["csv", "txt"])
if upload is None:
    st.info("Upload a ledger file with these columns: " + ", ".join(REQUIRED))
    st.stop()

try:
    frame = read_upload(upload.getvalue())
    problems = validate(frame)
    if problems:
        for p in problems:
            st.error(p)
        st.stop()
    res = run(upload.getvalue())
except UploadError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # never show a traceback to the jury
    st.error(f"Could not process the file ({type(exc).__name__}): {exc}")
    st.stop()

stats, rows = res["stats"], res["rows"]

# ----------------------------------------------------------------------------- header + numbers
st.subheader(f"{upload.name} · {stats['lines']} lines · {stats['seconds']:.1f} s")
if stats["renamed"]:
    st.warning("Some line_id values already exist in the train ledger; uploaded lines are shown as DEMO-<line_id>.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total tCO2e", f"{stats['total_t']:,.2f}")
c2.metric("Lines calculated", f"{stats['calculated']} of {stats['lines']}")
c3.metric("Flagged for review", stats["review"])
c4.metric("Activity-based / spend-based", f"{stats['activity_share']:.0%} / {1 - stats['activity_share']:.0%}")

# ----------------------------------------------------------------------------- totals
left, right = st.columns(2)
with left:
    st.markdown("**By scope (tCO2e)**")
    scope = res["by_scope"].rename("tCO2e").to_frame()
    st.dataframe(scope.style.format("{:,.4f}"), width="stretch")
    st.bar_chart(scope)
with right:
    st.markdown("**By category (tCO2e)**")
    cat = res["by_category"].rename("tCO2e").to_frame()
    st.dataframe(cat.style.format("{:,.4f}"), width="stretch")
    st.bar_chart(cat)

# ----------------------------------------------------------------------------- main table
st.markdown("### Lines")
st.caption("Green = rule · Yellow = ML fallback · Red = needs review · Grey = excluded / duplicate")
table = rows[TABLE].rename(columns={"converted": "converted quantity", "tco2e": "tCO2e"})
styled = (table.style
          # dark text on the pale row colours stays readable in Streamlit's light and dark themes
          .apply(lambda r: [f"background-color: {COLOURS.get(r['status'], '')}; color: #1a1a1a"] * len(r), axis=1)
          .format({"tCO2e": lambda v: "" if pd.isna(v) else f"{v:,.4f}"}))
st.dataframe(styled, width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- review + injections
st.markdown("### Needs review")
if res["review"].empty:
    st.success("No line needs review.")
else:
    st.dataframe(res["review"][["line_id", "description", "quantity", "unit", "category", "reason", "review_flag"]],
                 width="stretch", hide_index=True)

if not res["injection"].empty:
    st.markdown("### Instruction in text ignored")
    for r in res["injection"].itertuples(index=False):
        t = "" if pd.isna(r.tco2e) else f", {r.tco2e:,.4f} tCO2e"
        st.warning(f"**{r.line_id}**: instruction in the description was ignored. "
                   f"Final category **{r.category}** ({r.ef_id}{t}).")

# ----------------------------------------------------------------------------- line detail
st.markdown("### Line detail")
pick = st.selectbox("line_id", rows["line_id"].tolist())
line = rows.set_index("line_id").loc[pick]
d1, d2 = st.columns([1, 2])
with d1:
    st.markdown(f"**Status:** {line['status']}  \n**Rule:** `{line['rule_id']}`  \n"
                f"**Category:** {line['category']}  \n**Factor:** `{line['ef_id'] or '-'}`"
                + (f" = {line['factor']} kgCO2e per unit" if pd.notna(line["factor"]) else "")
                + f"  \n**Method:** {line['method']}  \n**Confidence:** {line['confidence']}")
with d2:
    st.markdown(f"**Ledger:** {line['description']}  \n**Quantity:** {line['quantity']} {line['unit']}")
    if line["conversion"]:
        st.markdown(f"**Conversion:** {line['conversion']}")
    st.code(line["calculation"], language=None)
    st.markdown(f"**Reason:** {line['reason']}")
    if isinstance(line["review_flag"], str) and line["review_flag"]:
        st.markdown(f"**Review flag:** {line['review_flag']}")

# ----------------------------------------------------------------------------- downloads
st.markdown("### Download")
stem = upload.name.rsplit(".", 1)[0]
b1, b2 = st.columns(2)
b1.download_button("Results CSV (line_id, category, tCO2e)", res["results"].to_csv(index=False).encode("utf-8-sig"),
                   f"{stem}_results.csv", "text/csv")
b2.download_button("Audit CSV (full trail)", res["audit"].to_csv(index=False).encode("utf-8-sig"),
                   f"{stem}_audit.csv", "text/csv")
