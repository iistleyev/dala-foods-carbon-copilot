"""Double counting across train + test: duplicate postings, and fuel/freight overlap for one carrier.

A duplicate is the same doc_no AND the same counterparty, description, quantity and gross amount.
doc_no alone is NOT enough: about half of the repeated doc_nos are unrelated purchases.
The lowest line_id is kept; every later copy is EXCLUDE with 0 tCO2e."""
import re

import pandas as pd

KEY = ["doc_no", "counterparty", "raw_text", "quantity", "amount_kzt_gross"]

CARRIER_CODE = re.compile(r"\bvendor_\d+\b")
FUEL_OVERLAP_FLAG = "possible Cat 4 double count: freight bought from this carrier is also counted"
FREIGHT_OVERLAP_FLAG = "possible Cat 4 double count: fuel bought for this carrier is also counted"


def find_carrier_overlap(df: pd.DataFrame, rule_ids: dict) -> dict:
    """Scope 3 Cat 4: diesel we buy for a hired carrier (FUEL_DIESEL_HIRED, carrier code in the text)
    and freight we buy from that same carrier (FREIGHT_* rules, carrier = counterparty) may cover the
    same trips. The Scope 3 Calculation Guidance counts a trip with the fuel-based OR the distance/spend
    method, not both. The ledger can't show which trips overlap, so this only flags; numbers stay.

    rule_ids: {row index: rule_id}. Returns {row index: flag}."""
    fuel = {}
    for i, rule_id in rule_ids.items():
        m = CARRIER_CODE.search(df.at[i, "text"]) if rule_id == "FUEL_DIESEL_HIRED" else None
        if m:
            fuel.setdefault(m[0].upper(), []).append(i)
    flags = {}
    for i, rule_id in rule_ids.items():
        carrier = df.at[i, "counterparty"]
        if rule_id.startswith("FREIGHT_") and carrier in fuel:
            flags[i] = FREIGHT_OVERLAP_FLAG
            flags.update({j: FUEL_OVERLAP_FLAG for j in fuel[carrier]})
    return flags


def find_duplicates(df: pd.DataFrame) -> dict:
    """Return {line_id_of_copy: line_id_of_original}."""
    dups = {}
    for _, grp in df.sort_values("line_id").groupby(KEY, dropna=False):
        if len(grp) > 1:
            first = grp["line_id"].iloc[0]
            for lid in grp["line_id"].iloc[1:]:
                dups[lid] = first
    return dups
