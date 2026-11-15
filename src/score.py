"""Exact leaderboard formula plus diagnostics (worst lines, confusion matrix)."""

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score


def score(true_cat, pred_cat, true_t, pred_t) -> dict:
    """score = 0.4 * macro_F1(category) + 0.6 * max(0, 1 - sum|pred - true| / sum|true|)"""
    f1 = f1_score(true_cat, pred_cat, average="macro")
    pred_t, true_t = np.asarray(pred_t, dtype=float), np.asarray(true_t, dtype=float)
    wape = np.abs(pred_t - true_t).sum() / np.abs(true_t).sum()
    return {"macro_f1": f1, "wape": wape, "score": 0.4 * f1 + 0.6 * max(0.0, 1 - wape)}


def worst_lines(merged: pd.DataFrame, n=15) -> pd.DataFrame:
    """The n train lines with the largest absolute tCO2e error."""
    m = merged.assign(abs_err=(merged["tco2e"] - merged["y_tco2e"]).abs())
    cols = [
        "line_id",
        "description",
        "gl",
        "quantity",
        "unit",
        "category",
        "y_category",
        "ef_id",
        "y_ef_id",
        "tco2e",
        "y_tco2e",
        "abs_err",
        "rule_id",
    ]
    return m.sort_values("abs_err", ascending=False).head(n)[cols]


def confusion(merged: pd.DataFrame) -> pd.DataFrame:
    """Confusion matrix of true vs predicted category."""
    return pd.crosstab(merged["y_category"], merged["category"], rownames=["true"], colnames=["pred"])
