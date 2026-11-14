"""Dala Foods carbon pipeline. One command:  python run.py  -> outputs/

Order per line (first match wins): duplicates -> rules.yaml (GL excludes, GL-routed, refrigerants,
energy, fuels, raw milk, materials, waste/water, spend keywords) -> ML fallback for spend lines."""
import sys

import pandas as pd
import yaml

from src.duplicates import (FREIGHT_OVERLAP_FLAG, FUEL_OVERLAP_FLAG, find_carrier_overlap,
                            find_duplicates)
from src.fallback import LOW_CONFIDENCE, SpendFallback, possible_typo
from src.load import ROOT, load_airports, load_factors, load_ledgers, load_packaging
from src.memo import memo_items
from src.rules import (QTY_FLAG, UNIT_GAP_FLAG, classify, load_rules, result,
                       spend_result)
from src.score import confusion, score, worst_lines

OUT = ROOT / "outputs"
# Calculation basis per category, written into summary.csv (GHG Protocol / IFRS S2 disclosure).
BASIS = {
    "S1_STATIONARY": "IPCC 2006 Tier 1 default; CO2 only",
    "S1_MOBILE": "IPCC 2006 Tier 1 default; CO2 only",
    "S1_FUGITIVE": "refill = leak; GWP-100 from IPCC AR5",
    "S2_ELECTRICITY": "location-based (Kazakhstan grid average); market-based equal (memo row)",
    "S2_HEAT": "location-based (Almaty district heating factor)",
    "S3_C4_TRANSPORT": "fuel-, distance- and spend-based; see Cat 4 overlap flags in audit.csv",
}
AUDIT_COLS = ["line_id", "set", "category", "ef_id", "activity_qty", "activity_unit", "method",
              "tco2e", "rule_id", "reason", "confidence", "review_flag"]


def measured_keywords(rules):
    """Keywords of the physical (measured) items in rules.yaml: milk, fuels, energy, refrigerants..."""
    return {k for r in rules if r.get("physical_only") for k in r.get("match", [])}


def add_flag(res, flag):
    res["review_flag"] = "; ".join(x for x in (res["review_flag"], flag) if x)


def run_pipeline(df=None):
    """Classify every train+test line. Returns the audit frame (one row per line)."""
    df = load_ledgers() if df is None else df
    rules = load_rules(ROOT / "rules.yaml")
    factors, airports, packaging = load_factors(), load_airports(), load_packaging()
    dups = find_duplicates(df)

    results, pending = {}, []
    for i, row in df.iterrows():
        if row["line_id"] in dups:
            res = result(
                "EXCLUDE", "", 0.0, "", "excluded", 0.0, "DUPLICATE",
                "Same doc_no, counterparty, description, quantity and amount as an earlier line.",
                flag=f"duplicate of {dups[row['line_id']]}")
        else:
            res, _ = classify(row, rules, factors, airports, packaging)
        if res is None:
            pending.append(i)
        else:
            results[i] = res

    if pending:  # ML fallback: spend-based factor predicted from text + GL
        model = SpendFallback().fit(df[df["set"] == "train"])
        rows = df.loc[pending]
        for i, (ef, cat, p) in zip(pending, model.predict(rows)):
            res = spend_result(df.loc[i], ef, cat, factors, "ML_FALLBACK",
                               "No rule matched; spend factor predicted from description and GL.",
                               confidence=round(p, 3), flag="new item")
            if p < LOW_CONFIDENCE:
                add_flag(res, "low confidence")
            near = possible_typo(df.at[i, "text"], measured_keywords(rules))
            if near:  # e.g. "Фрион" landing on a spend factor: probably a refrigerant with a typo
                add_flag(res, f"possible typo of a measured item ('{near}'): check")
            results[i] = res

    for i, res in results.items():
        if df.at[i, "quantity_unreadable"]:
            add_flag(res, QTY_FLAG)
        if df.at[i, "vat_unreadable"]:
            add_flag(res, "VAT unreadable")
        if df.at[i, "vat_inconsistent"] and "VAT inconsistent" not in res["review_flag"]:
            add_flag(res, "VAT inconsistent with gross")
    for i, flag in find_carrier_overlap(df, {i: r["rule_id"] for i, r in results.items()}).items():
        add_flag(results[i], flag)

    audit = pd.DataFrame.from_dict(results, orient="index").sort_index()
    audit.insert(0, "line_id", df["line_id"])
    audit.insert(1, "set", df["set"])
    for i in df.index[df["injection"]]:  # planted instructions were stripped, not obeyed
        audit.at[i, "review_flag"] = "; ".join(
            x for x in (audit.at[i, "review_flag"], "instruction-like text ignored") if x)
    audit["tco2e"] = audit["tco2e"].astype(float).round(4)
    audit["activity_qty"] = audit["activity_qty"].astype(float).round(4)
    return df, audit[AUDIT_COLS]


def summarise(audit):
    if audit["tco2e"].isna().any():
        raise ValueError("Resolve all audit rows before calculating inventory totals.")
    a = audit.copy()
    a["scope"] = a["category"].str.extract(r"^(S\d)")[0].fillna("EXCLUDE")
    a["t_activity"] = a["tco2e"].where(a["method"] == "activity", 0.0)
    a["t_spend"] = a["tco2e"].where(a["method"] == "spend", 0.0)
    g = a.groupby(["scope", "category"]).agg(lines=("line_id", "size"), tco2e=("tco2e", "sum"),
                                             tco2e_activity=("t_activity", "sum"),
                                             tco2e_spend=("t_spend", "sum")).reset_index()
    total = g["tco2e"].sum()
    g["share_of_total"] = g["tco2e"] / total
    g["activity_share"] = (g["tco2e_activity"] / g["tco2e"]).where(g["tco2e"] != 0, 0.0)
    tot = pd.DataFrame([{"scope": "TOTAL", "category": "ALL", "lines": g["lines"].sum(), "tco2e": total,
                         "tco2e_activity": g["tco2e_activity"].sum(), "tco2e_spend": g["tco2e_spend"].sum(),
                         "share_of_total": 1.0, "activity_share": g["tco2e_activity"].sum() / total}])
    out = pd.concat([g, tot], ignore_index=True)
    # The brief asks for tCO2e per tonne of product (105,000 t, set in scenarios.yaml).
    out["tco2e_per_t_product"] = out["tco2e"] / product_tonnes()
    out["basis"] = out["category"].map(BASIS).fillna("")
    # Memo rows below TOTAL: shown next to the inventory, not part of it (see src/memo.py).
    memo = memo_items(audit, load_factors())
    memo["tco2e_per_t_product"] = memo["tco2e"] / product_tonnes()
    return pd.concat([out, memo], ignore_index=True).round(4)


def product_tonnes():
    with open(ROOT / "scenarios.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["product"]["finished_product_t"]


def report_train(df, audit):
    tr = df[df["set"] == "train"].merge(audit, on=["line_id", "set"])
    s = score(tr["y_category"], tr["category"], tr["y_tco2e"], tr["tco2e"])
    print(f"TRAIN  macro-F1 {s['macro_f1']:.4f} | WAPE {s['wape']:.4f} | score {s['score']:.4f}")
    print(f"       ML-fallback lines: train {(tr['rule_id'] == 'ML_FALLBACK').sum()}, "
          f"test {((audit['set'] == 'test') & (audit['rule_id'] == 'ML_FALLBACK')).sum()}")
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 45):
        print("\n15 worst train lines by absolute tCO2e error:")
        print(worst_lines(tr).to_string(index=False))
        print("\nConfusion matrix (rows = true, cols = predicted):")
        print(confusion(tr).to_string())
    return s


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    df, audit = run_pipeline()
    OUT.mkdir(exist_ok=True)
    review_path = OUT / "audit.review.csv"
    if audit["method"].eq("review").any():
        audit.to_csv(review_path, index=False, encoding="utf-8-sig")
        count = int(audit["method"].eq("review").sum())
        raise SystemExit(f"{count} unresolved rows. See {review_path}. No new predictions or totals exported.")

    test = audit[audit["set"] == "test"]
    test[["line_id", "category", "tco2e"]].to_csv(OUT / "predictions.csv", index=False, float_format="%.4f")
    audit.to_csv(OUT / "audit.csv", index=False, encoding="utf-8-sig")
    summarise(audit).to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    review_path.unlink(missing_ok=True)
    report_train(df, audit)
    print(f"\nWrote outputs/predictions.csv ({len(test)} rows), outputs/audit.csv ({len(audit)} rows), "
          f"outputs/summary.csv")
    report_warnings(audit)


def report_warnings(audit):
    """Count of lines per hardening flag, so nothing fails silently."""
    print("\nReview warnings (lines flagged in outputs/audit.csv):")
    flags = audit["review_flag"].fillna("")
    for flag in (QTY_FLAG, UNIT_GAP_FLAG, FUEL_OVERLAP_FLAG, FREIGHT_OVERLAP_FLAG):
        hit = flags.str.contains(flag, regex=False)
        n_train = int((hit & (audit["set"] == "train")).sum())
        n_test = int((hit & (audit["set"] == "test")).sum())
        print(f"  WARNING {flag}: {n_train + n_test} (train {n_train}, test {n_test})")


if __name__ == "__main__":
    main()
