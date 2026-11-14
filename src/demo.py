"""Processing behind the live demo (app.py). No UI code here, so it can be tested on its own.

It runs the existing pipeline (run.run_pipeline) on uploaded ledger rows, with the masked train ledger
as context so the ML fallback and the duplicate check work exactly as in run.py, and returns only the
uploaded rows (set = "demo"). No classification or emission logic lives here.

Draft mode: lines the pipeline holds for review (method "review") are returned and listed, instead of
stopping the run as run.py does before writing official outputs.
"""
import io
import json
import time

import pandas as pd

from run import AUDIT_COLS, run_pipeline
from src.load import load_factors, load_ledgers, normalise

REQUIRED = ["line_id", "posting_date", "doc_no", "counterparty", "description", "gl_account",
            "cost_center", "quantity", "unit", "amount_kzt_gross", "vat_kzt"]
ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")


class UploadError(ValueError):
    """A problem with the uploaded file, shown to the user as a message."""


# ----------------------------------------------------------------------------- reading
def read_upload(data: bytes) -> pd.DataFrame:
    """CSV bytes -> DataFrame of strings. Accepts , or ; and UTF-8, UTF-8 with BOM, or cp1251."""
    for encoding in ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UploadError("Could not read the file: save it as UTF-8 or Windows-1251 (cp1251).")
    if not text.strip():
        raise UploadError("The file is empty.")
    header = text.lstrip("﻿").splitlines()[0]
    sep = ";" if header.count(";") > header.count(",") else ","
    try:
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    except Exception as exc:  # malformed CSV: report, never crash
        raise UploadError(f"Could not parse the CSV ({type(exc).__name__}): {exc}") from None
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]
    if df.empty:
        return df
    # rows with nothing in any column (often left at the end of an Excel export) are dropped
    return df[df.astype(str).apply(lambda col: col.str.strip()).ne("").any(axis=1)].reset_index(drop=True)


def missing_columns(df: pd.DataFrame) -> list:
    return [c for c in REQUIRED if c not in df.columns]


def validate(df: pd.DataFrame) -> list:
    """Problems that stop processing, as messages for the user (empty list = OK)."""
    missing = missing_columns(df)
    if missing:
        return [f"Missing columns: {', '.join(missing)}. Expected: {', '.join(REQUIRED)}."]
    problems = []
    if df.empty:
        problems.append("The file has a header but no ledger lines.")
    ids = df["line_id"].str.strip()
    if (ids == "").any():
        problems.append(f"{int((ids == '').sum())} lines have no line_id.")
    if ids[ids != ""].duplicated().any():
        problems.append(f"Repeated line_id values: {', '.join(sorted(set(ids[ids.duplicated()])))[:200]}.")
    return problems


# ----------------------------------------------------------------------------- processing
def process(df: pd.DataFrame) -> dict:
    """Run the pipeline on the uploaded rows. Returns tables and numbers for the page."""
    problems = validate(df)
    if problems:
        raise UploadError(" ".join(problems))
    start = time.perf_counter()
    upload = df[REQUIRED].copy()
    upload["line_id"] = upload["line_id"].str.strip()
    train = load_ledgers().query("set == 'train'")
    renamed = bool(set(upload["line_id"]) & set(train["line_id"]))
    if renamed:  # keep uploaded lines apart from the train lines they would otherwise collide with
        upload["line_id"] = "DEMO-" + upload["line_id"]
    demo = normalise(upload)
    demo["set"] = "demo"
    _, audit = run_pipeline(pd.concat([train, demo], ignore_index=True))
    audit = audit[audit["set"] == "demo"].reset_index(drop=True)

    factors = load_factors()
    shown = upload[["line_id", "description", "quantity", "unit"]].merge(
        demo[["line_id", "injection"]], on="line_id").merge(audit, on="line_id")
    shown["status"] = shown.apply(status, axis=1)
    shown["factor"] = shown["ef_id"].map(lambda e: factors[e]["value"] if e in factors else None)
    shown["converted"] = shown.apply(
        lambda r: _qty(r["activity_qty"], r["activity_unit"]) if r["method"] in ("activity", "spend") else "",
        axis=1)
    shown["conversion"] = shown.apply(conversion, axis=1)
    shown["calculation"] = shown.apply(lambda r: calculation(r, factors), axis=1)
    seconds = time.perf_counter() - start

    counted = shown[shown["method"].isin(["activity", "spend"])]
    activity_t = counted.loc[counted["method"] == "activity", "tco2e"].sum()
    spend_t = counted.loc[counted["method"] == "spend", "tco2e"].sum()
    scoped = counted.assign(scope=counted["category"].str[:2])
    return {
        "rows": shown,
        "audit": audit[AUDIT_COLS],
        "results": audit[["line_id", "category", "tco2e"]],
        "review": shown[shown["method"] == "review"],
        "injection": shown[shown["injection"]],
        "by_scope": scoped.groupby("scope")["tco2e"].sum().reindex(["S1", "S2", "S3"], fill_value=0.0),
        "by_category": counted.groupby("category")["tco2e"].sum().sort_values(ascending=False),
        "stats": {
            "lines": len(shown), "total_t": float(counted["tco2e"].sum()),
            "calculated": len(counted), "review": int((shown["method"] == "review").sum()),
            "excluded": int((shown["method"] == "excluded").sum()),
            "activity_share": activity_t / (activity_t + spend_t) if activity_t + spend_t else 0.0,
            "seconds": seconds, "renamed": renamed,
        },
    }


# ----------------------------------------------------------------------------- explaining a line
def status(r) -> str:
    if r["method"] == "review":
        return "needs review"
    if r["method"] == "excluded":
        return "duplicate" if r["rule_id"] == "DUPLICATE" else "excluded"
    return "ML fallback" if r["rule_id"] == "ML_FALLBACK" else "rule"


def _num(x) -> str:
    return f"{x:,.4f}".rstrip("0").rstrip(".").replace(",", " ")


def _qty(q, unit) -> str:
    unit = "thousand KZT net" if unit == "1000 KZT net" else unit
    return "" if pd.isna(q) else f"{_num(q)} {unit}".strip()


def conversion(r) -> str:
    """Ledger quantity -> quantity in the factor's unit."""
    if r["method"] not in ("activity", "spend"):
        return ""
    if r["method"] == "spend":
        return f"(gross − VAT) / 1000 = {_num(r['activity_qty'])} thousand KZT net"
    if r["rule_id"] == "TRAVEL_FLIGHT":
        return f"great-circle km per leg × tickets = {_num(r['activity_qty'])} pkm"
    if r["unit"] == "усл" or "taken from the description" in str(r["reason"]):
        return f"{_num(r['activity_qty'])} {r['activity_unit']} read from the description (ledger: {r['quantity']} {r['unit']})"
    try:
        ledger = float(str(r["quantity"]).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        ledger = None
    if ledger:
        return f"{r['quantity']} {r['unit']} × {_num(r['activity_qty'] / ledger)} = {_num(r['activity_qty'])} {r['activity_unit']}"
    return _qty(r["activity_qty"], r["activity_unit"])


def calculation(r, factors) -> str:
    """The emission arithmetic written out, e.g. '22.5 kg × 3943 / 1000 = 88.7175 tCO2e'."""
    if r["method"] == "excluded":
        return f"Not counted: {r['reason']}"
    if r["method"] == "review":
        return f"Not calculated: {r['reason']}"
    if r["rule_id"] == "TRAVEL_FLIGHT" and "Leg calculations: " in str(r["reason"]):
        legs = json.loads(str(r["reason"]).split("Leg calculations: ")[1])
        parts = [f"{l['from']}-{l['to']}: {_num(l['km'])} km × {_num(l['tickets'])} × {l['kgCO2e_per_pkm']} / 1000"
                 f" = {l['tco2e']:.4f}" for l in legs]
        return "; ".join(parts) + f"  →  total {r['tco2e']:.4f} tCO2e"
    f = factors.get(r["ef_id"])
    if f is None:
        return ""
    unit = "thousand KZT" if r["method"] == "spend" else r["activity_unit"]
    return (f"{_num(r['activity_qty'])} {unit} × {_num(f['value'])} kgCO2e/{f['unit']} / 1000"
            f" = {r['tco2e']:.4f} tCO2e")
