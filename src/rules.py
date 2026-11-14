"""Rule engine: reads rules.yaml and returns the first matching rule's result for a ledger line."""
import json
import math
from pathlib import Path

import yaml

from .convert import flight_legs, parse_km, piece_weight_kg, refrigerant_ef, ticket_counts, unit_multiplier

SPEND_UNIT = "1000 KZT net"

# Review flags written to the audit file (run.py prints a count for each).
QTY_FLAG = "quantity unreadable"
UNIT_GAP_FLAG = "physical activity requires review"

# Reasons returned when a matched physical rule cannot calculate emissions.
UNIT_NOT_COVERED = "unit not covered"



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


def unresolved(category, ef_id, rule_id, reason, flag):
    """No estimate is possible. Missing values are distinct from measured zeroes."""
    return result(category, ef_id, None, "", "review", None, rule_id, reason, 0.0, flag)


def spend_result(row, ef_id, category, factors, rule_id, reason, confidence=1.0, flag=""):
    if not math.isfinite(row["net_kzt"]):
        return unresolved(category, ef_id, rule_id, "Check gross amount and recorded VAT.", "net spend unreadable")
    qty = row["net_kzt"] / 1000.0
    return result(category, ef_id, qty, SPEND_UNIT, "spend", qty * factors[ef_id]["value"] / 1000.0,
                  rule_id, reason, confidence, flag)


def flight_result(rule, legs, counts, factors):
    """The official primary factor is the one contributing the most absolute CO2e."""
    detail, totals = [], {}
    for (origin, dest, km, ef), count in zip(legs, counts, strict=True):
        pkm = km * count
        rate = factors[ef]["value"]
        tonnes = pkm * rate / 1000
        detail.append({"from": origin, "to": dest, "km": km, "tickets": count, "pkm": pkm,
                       "ef_id": ef, "kgCO2e_per_pkm": rate, "tco2e": tonnes})
        totals[ef] = totals.get(ef, 0.0) + abs(tonnes)
    # Display only: operating systems' math libraries differ in the last digits of km, so the
    # audit shows 9 decimals to stay identical on any machine. Totals use the unrounded values.
    shown = [{k: round(v, 9) if isinstance(v, float) else v for k, v in leg.items()} for leg in detail]
    reason = rule["reason"] + " Leg calculations: " + json.dumps(shown, separators=(",", ":"))
    return result(rule["category"], max(totals, key=totals.get), sum(leg["pkm"] for leg in detail),
                  "pkm", "activity", sum(leg["tco2e"] for leg in detail), rule["id"], reason)


def apply_rule(rule: dict, row, factors: dict, airports: dict, packaging: dict):
    """Calculate the line or return the reason that its activity could not be measured."""
    method = rule.get("method", "activity")
    cat, rid, reason = rule["category"], rule["id"], rule["reason"]
    text, q = row["text"], row["quantity"]

    if method == "excluded":
        return result("EXCLUDE", "", 0.0, "", "excluded", 0.0, rid, reason), None

    if method == "spend":
        return spend_result(row, rule["ef_id"], cat, factors, rid, reason), None

    # every method below multiplies the ledger quantity, so it must be readable
    if q is None or (isinstance(q, float) and math.isnan(q)):
        return None, QTY_FLAG

    if method == "flight":
        legs = flight_legs(text, airports)
        if not legs:
            return None, "incomplete or unknown airport route"
        counts = ticket_counts(text, legs, q, airports)
        if counts is None:
            return None, "ticket count does not reconcile with listed itineraries"
        return flight_result(rule, legs, counts, factors), None

    if method == "rail":
        km = parse_km(text)
        if km is None:
            return None, "missing freight distance"
        tkm = q * km
        return result(cat, rule["ef_id"], tkm, "tkm", "activity",
                      tkm * factors[rule["ef_id"]]["value"] / 1000.0, rid, reason), None

    # plain activity rule: quantity x unit multiplier, in the factor's unit
    units, unit = rule.get("units", {}), row["unit_code"]
    if unit == "г" and "кг" in units:
        q, unit = q / 1000, "кг"
        reason += " Ledger grams converted to kg."
    if unit == "тыс. шт" and "шт" in units:  # thousands of pieces -> pieces, then piece weight
        q, unit = q * 1000, "шт"
        reason += " Ledger thousands of pieces converted to pieces."
    if unit not in units:
        return None, UNIT_NOT_COVERED
    if units[unit] == "package_weight":
        mult, source = piece_weight_kg(text, packaging)
        if source:
            reason = f"{reason} {source}"
    else:
        mult = unit_multiplier(units[unit], text)
    if mult is None:
        return None, "missing or ambiguous unit weight or refill mass"
    ef_id = refrigerant_ef(text) if rule["ef_id"] == "by_gas" else rule["ef_id"]
    if ef_id is None:
        return None, "unidentified refrigerant"
    qty = q * mult  # negative quantity (credit note) stays negative: never abs()
    return result(cat, ef_id, qty, factors[ef_id]["unit"], "activity",
                  qty * factors[ef_id]["value"] / 1000.0, rid, reason), None


def classify(row, rules: list, factors: dict, airports: dict, packaging: dict | None = None):
    """Return the matched result and whether a physical calculation needs review."""
    for rule in rules:
        if not matches(rule, row):
            continue
        res, why = apply_rule(rule, row, factors, airports, packaging or {})
        if res is not None:
            return res, False
        if rule.get("physical_only"):
            ef = rule.get("ef_id")
            if ef == "by_gas":
                ef = refrigerant_ef(row["text"])
            return unresolved(rule["category"], ef, rule["id"], why, UNIT_GAP_FLAG), True

    # Every purchase in these ledger accounts requires an identified physical item.
    if row["gl"] in {"1310", "1311", "1320", "7210", "8110"}:
        return unresolved("", "", "UNKNOWN_PHYSICAL_ITEM", "Identify the item and physical unit.",
                          UNIT_GAP_FLAG), True
    return None, False
