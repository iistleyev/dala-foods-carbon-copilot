"""Duplicate postings across train + test.

A duplicate is the same doc_no AND the same counterparty, description, quantity and gross amount.
doc_no alone is NOT enough: about half of the repeated doc_nos are unrelated purchases.
The lowest line_id is kept; every later copy is EXCLUDE with 0 tCO2e."""
import pandas as pd

KEY = ["doc_no", "counterparty", "raw_text", "quantity", "amount_kzt_gross"]


def find_duplicates(df: pd.DataFrame) -> dict:
    """Return {line_id_of_copy: line_id_of_original}."""
    dups = {}
    for _, grp in df.sort_values("line_id").groupby(KEY, dropna=False):
        if len(grp) > 1:
            first = grp["line_id"].iloc[0]
            for lid in grp["line_id"].iloc[1:]:
                dups[lid] = first
    return dups
