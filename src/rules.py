"""Rule engine: reads rules.yaml and returns the first matching rule's result for a ledger line."""
import math
from pathlib import Path

import yaml

from .convert import flight_legs, parse_km, piece_weight_kg, refrigerant_ef, unit_multiplier

SPEND_UNIT = "1000 KZT net"

# Review flags written to the audit file (run.py prints a count for each).
QTY_FLAG = "quantity unreadable"
UNIT_GAP_FLAG = "activity item computed by spend: unit not covered"

# Why a matching rule could not produce a number (the engine then tries the next rule).
UNIT_NOT_COVERED = "unit not covered"
QTY_UNREADABLE = "quantity unreadable"


def load_rules(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    for r in rules:  # yaml may read GL codes as ints; keep them as strings
        r["gl"] = [str(g) for g in r.get("gl", [])]
    return rules


def matches(rule: dict, row) -> bool:
    if rule["gl"] and row["gl"] not in rule["gl"]:
        return False
    if "unit" in rule and row["unit_code"] not in rule["unit"]:
        return False
    if "match" in rule and not any(k in row["text"] for k in rule["match"]):
        return False
    return True


def result(category, ef_id, qty, unit, method, tco2e, rule_id, reason, confidence=1.0, flag=""):
    return {"category": category, "ef_id": ef_id or "", "activity_qty": qty, "activity_unit": unit,
            "method": method, "tco2e": tco2e, "rule_id": rule_id, "reason": reason,
            "confidence": confidence, "review_flag": flag}


def spend_result(row, ef_id, category, factors, rule_id, reason, confidence=1.0, flag=""):
    qty = row["net_kzt"] / 1000.0  # thousand KZT, net of VAT
    return result(category, ef_id, qty, SPEND_UNIT, "spend", qty * factors[ef_id]["value"] / 1000.0,
                  rule_id, reason, confidence, flag)


def flight_result(rule, legs, q, factors):
    """One leg or several with the same factor: that factor. Legs with different factors
    (e.g. NQZ-ALA domestic + ALA-FRA long-haul): factors joined with '+', per-leg km in the reason."""
    pkm = sum(km for *_, km, _ in legs) * q
    tco2e = sum(km * q * factors[ef]["value"] for *_, km, ef in legs) / 1000.0
    efs = list(dict.fromkeys(ef for *_, ef in legs))  # distinct, in route order
    reason = rule["reason"]
    if len(efs) > 1:
        per_leg = ", ".join(f"{a}-{b} {km:.0f} km ({ef})" for a, b, km, ef in legs)
        reason = f"{reason} Mixed route; legs: {per_leg}."
    return result(rule["category"], "+".join(efs), pkm, "pkm", "activity", tco2e, rule["id"], reason)


def apply_rule(rule: dict, row, factors: dict, airports: dict, packaging: dict):
    """Compute the result for a matching rule.

    Returns (result, None) on success, or (None, why) when the rule cannot produce a number
    (unit not covered / quantity unreadable); the engine then tries the next rule."""
    method = rule.get("method", "activity")
    cat, rid, reason = rule["category"], rule["id"], rule["reason"]
    text, q = row["text"], row["quantity"]

    if method == "excluded":
        return result("EXCLUDE", "", 0.0, "", "excluded", 0.0, rid, reason), None

    if method == "spend":
        return spend_result(row, rule["ef_id"], cat, factors, rid, reason), None

    # every method below multiplies the ledger quantity, so it must be readable
    if q is None or (isinstance(q, float) and math.isnan(q)):
        return None, QTY_UNREADABLE

    if method == "flight":
        legs = flight_legs(text, airports)
        if not legs:
            return None, UNIT_NOT_COVERED
        return flight_result(rule, legs, q, factors), None

    if method == "rail":
        km = parse_km(text)
        if km is None:
            return None, UNIT_NOT_COVERED
        tkm = q * km
        return result(cat, rule["ef_id"], tkm, "tkm", "activity",
                      tkm * factors[rule["ef_id"]]["value"] / 1000.0, rid, reason), None

    # plain activity rule: quantity x unit multiplier, in the factor's unit
    units, unit = rule.get("units", {}), row["unit_code"]
    if unit not in units:
        return None, UNIT_NOT_COVERED
    if unit == "шт":  # pieces -> kg: packaging_specs.csv, then grams in the name, then rules.yaml
        mult, source = piece_weight_kg(text, units[unit], packaging)
        if source:
            reason = f"{reason} {source}"
    else:
        mult = unit_multiplier(units[unit], text)
    if mult is None:
        return None, UNIT_NOT_COVERED
    ef_id = refrigerant_ef(text) if rule["ef_id"] == "by_gas" else rule["ef_id"]
    if ef_id is None:
        return None, UNIT_NOT_COVERED
    qty = q * mult  # negative quantity (credit note) stays negative: never abs()
    return result(cat, ef_id, qty, factors[ef_id]["unit"], "activity",
                  qty * factors[ef_id]["value"] / 1000.0, rid, reason), None


def classify(row, rules: list, factors: dict, airports: dict, packaging: dict | None = None):
    """First matching rule that can compute the line wins.

    Returns (result or None, unit_gap). result None means the ML fallback decides.
    unit_gap is True when an activity-item rule (review_if_unit_missing) matched but could not
    convert the line's unit, so the line falls through to a later rule or the ML fallback."""
    packaging = packaging or {}
    unit_gap = False
    for rule in rules:
        if matches(rule, row):
            res, why = apply_rule(rule, row, factors, airports, packaging)
            if res is not None:
                return res, unit_gap
            if why == UNIT_NOT_COVERED and rule.get("review_if_unit_missing"):
                unit_gap = True
    return None, unit_gap


def review_flags(row, res: dict, unit_gap: bool) -> list:
    """Flags that do not depend on which rule won: unreadable quantity, and an activity item
    that ended up spend-based because its unit was not covered."""
    flags = []
    if bool(row.get("quantity_unreadable", False)):
        flags.append(QTY_FLAG)
    if unit_gap and res["method"] == "spend":
        flags.append(UNIT_GAP_FLAG)
    return flags
