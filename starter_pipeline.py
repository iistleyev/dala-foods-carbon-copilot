"""Case 2 starter pipeline (Dala Foods). A deliberately simple baseline: improve it!
Run:  python starter_pipeline.py      (needs pandas; put the CSV files in the same folder)
"""
import pandas as pd

ef = pd.read_csv("emission_factors.csv").set_index("ef_id")["kgCO2e_per_unit"]
train = pd.read_csv("ledger_train.csv")
test = pd.read_csv("ledger_test.csv")

# 1. Keyword rules: (words to look for, category, emission factor id). Order matters: first match wins.
RULES = [
    (["молок", "сүт", "milk"], "S3_C1_GOODS", "EF_MILK_KG"),
    (["дизел", "diesel"], "S1_MOBILE", "EF_DIESEL_L"),
    (["электр"], "S2_ELECTRICITY", "EF_GRID_KZ_KWH"),
    (["налог", "штраф"], "EXCLUDE", None),
]
DEFAULT = ("S3_C1_GOODS", "SP_SERVICES_PROF")       # everything else: spend-based services

# 2. Unit conversion to the factor's unit. Extend this table!
TO_BASE = {"кг": 1.0, "т": 1000.0, "кВт·ч": 1.0, "МВт·ч": 1000.0, "л": 1.0}

def classify(row):
    text = str(row["description"]).lower()
    for words, cat, ef_id in RULES:
        if any(w in text for w in words):
            return cat, ef_id
    return DEFAULT

def emissions_t(row, cat, ef_id):
    if ef_id is None:
        return 0.0
    if ef_id.startswith("SP_"):                        # spend-based: thousand KZT, NET of VAT
        net = row["amount_kzt_gross"] - row["vat_kzt"]
        return net / 1000 * ef[ef_id] / 1000
    qty = row["quantity"] * TO_BASE.get(str(row["unit"]), 1.0)   # activity-based
    return qty * ef[ef_id] / 1000                      # kg CO2e -> t CO2e

def run(df):
    out = []
    for _, row in df.iterrows():
        cat, ef_id = classify(row)
        out.append({"line_id": row["line_id"], "category": cat, "ef_id": ef_id or "",
                    "tco2e": round(emissions_t(row, cat, ef_id), 4)})
    return pd.DataFrame(out)

# 3. Check yourself on the labelled training lines before touching the test set
pred = run(train)
def macro_f1(y_true, y_pred):
    f1s = []
    for c in sorted(set(y_true)):
        tp = ((y_pred == c) & (y_true == c)).sum(); fp = ((y_pred == c) & (y_true != c)).sum(); fn = ((y_pred != c) & (y_true == c)).sum()
        p = tp / (tp + fp) if tp + fp else 0; r = tp / (tp + fn) if tp + fn else 0
        f1s.append(2 * p * r / (p + r) if p + r else 0)
    return sum(f1s) / len(f1s)
f1 = macro_f1(train["y_category"], pred["category"])
wape = (pred["tco2e"] - train["y_tco2e"]).abs().sum() / train["y_tco2e"].abs().sum()
print(f"Train macro-F1 {f1:.3f} | WAPE {wape:.3f} | estimated score {0.4 * f1 + 0.6 * max(0, 1 - wape):.3f}")
wrong = train[pred["category"] != train["y_category"]]
print("Examples to fix:\n", wrong[["description", "unit", "y_category"]].head(10).to_string())

# 4. Predict the test set and save the submission
run(test)[["line_id", "category", "tco2e"]].to_csv("predictions.csv", index=False)
print("Saved predictions.csv")
