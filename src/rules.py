"""Rule engine: reads rules.yaml and returns the first matching rule's result for a ledger line."""
from pathlib import Path

import yaml

from .convert import flight_legs, parse_km, refrigerant_ef, unit_multiplier

SPEND_UNIT = "1000 KZT net"


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


def apply_rule(rule: dict, row, factors: dict, airports: dict):
    """Compute the result for a matching rule, or None if the conversion is impossible
    (e.g. unit not covered), in which case the engine tries the next rule."""
    method = rule.get("method", "activity")
    cat, rid, reason = rule["category"], rule["id"], rule["reason"]
    text, q = row["text"], row["quantity"]

    if method == "excluded":
        return result("EXCLUDE", "", 0.0, "", "excluded", 0.0, rid, reason)

    if method == "spend":
        return spend_result(row, rule["ef_id"], cat, factors, rid, reason)

    if method == "flight":
        legs = flight_legs(text, airports)
        if not legs:
            return None
        pkm = sum(km for *_, km, _ in legs) * q
        tco2e = sum(km * q * factors[ef]["value"] for *_, km, ef in legs) / 1000.0
        return result(cat, legs[0][3], pkm, "pkm", "activity", tco2e, rid, reason)

    if method == "rail":
        km = parse_km(text)
        if km is None:
            return None
        tkm = q * km
        return result(cat, rule["ef_id"], tkm, "tkm", "activity",
                      tkm * factors[rule["ef_id"]]["value"] / 1000.0, rid, reason)

    # plain activity rule: quantity x unit multiplier, in the factor's unit
    units = rule.get("units", {})
    if row["unit_code"] not in units:
        return None
    mult = unit_multiplier(units[row["unit_code"]], text)
    if mult is None:
        return None
    ef_id = refrigerant_ef(text) if rule["ef_id"] == "by_gas" else rule["ef_id"]
    if ef_id is None:
        return None
    qty = q * mult  # negative quantity (credit note) stays negative: never abs()
    return result(cat, ef_id, qty, factors[ef_id]["unit"], "activity",
                  qty * factors[ef_id]["value"] / 1000.0, rid, reason)


def classify(row, rules: list, factors: dict, airports: dict):
    for rule in rules:
        if matches(rule, row):
            res = apply_rule(rule, row, factors, airports)
            if res is not None:
                return res
    return None  # -> ML fallback
