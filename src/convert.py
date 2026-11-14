"""Unit conversion to the factor's unit, plus parsers for kg / km / grams / flight routes in text."""
import math
import re

NUM = r"(-?\d+(?:[.,]\d+)?)"
EARTH_RADIUS_KM = 6371.0
LONG_HAUL_KM = 3700.0


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_kg(text: str):
    """'дозаправка r404a 11.1 кг' -> 11.1"""
    m = re.search(NUM + r"\s*кг", text)
    return _num(m.group(1)) if m else None


def parse_km(text: str):
    """'алматы-ташкент, 41.1 т, 3100 км' -> 3100"""
    m = re.search(NUM + r"\s*км\b", text)
    return _num(m.group(1)) if m else None


def parse_grams(text: str):
    """'преформа пэт 28 г, 1,5 л' -> 28 ; 'преформа pet 22г 0,9л' -> 22"""
    m = re.search(NUM + r"\s*г(?![а-яa-z])", text)
    return _num(m.group(1)) if m else None


def unit_multiplier(spec, text: str):
    """A conversion spec from rules.yaml -> number to multiply the ledger quantity by.

    spec is a number (1, 1.03, 1000 ...), a fraction string like '1/4.1868',
    'kg_in_text' (quantity is a service count; the kg are written in the text), or
    'grams_in_text' (pieces x grams-per-piece written in the item name / 1000)."""
    if isinstance(spec, (int, float)):
        return float(spec)
    if spec == "kg_in_text":
        return parse_kg(text)
    if spec == "grams_in_text":
        g = parse_grams(text)
        return g / 1000 if g is not None else None
    if isinstance(spec, str) and "/" in spec:
        a, b = spec.split("/")
        return float(a) / float(b)
    return float(spec)


def haversine_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def flight_legs(text: str, airports: dict):
    """'авиабилет ala-nqz-ala, ...' -> [(ALA, NQZ, km, ef_id), (NQZ, ALA, km, ef_id)].

    The factor is chosen per leg: both airports in KZ -> domestic; else < 3700 km -> short; else long."""
    m = re.search(r"\b([a-z]{3}(?:-[a-z]{3})+)\b", text)
    if not m:
        return None
    codes = [c.upper() for c in m.group(1).split("-")]
    if not all(c in airports for c in codes):
        return None
    legs = []
    for x, y in zip(codes, codes[1:]):
        km = haversine_km(airports[x], airports[y])
        if airports[x][2] == "KZ" and airports[y][2] == "KZ":
            ef = "EF_FLIGHT_DOM_PKM"
        elif km < LONG_HAUL_KM:
            ef = "EF_FLIGHT_SHORT_PKM"
        else:
            ef = "EF_FLIGHT_LONG_PKM"
        legs.append((x, y, km, ef))
    return legs


def refrigerant_ef(text: str):
    """Pick the refrigerant factor from the gas name in the text."""
    t = text.replace("-", "").replace(" ", "")
    for gas in ("r404a", "r134a", "r410a", "r744"):
        if gas in t:
            return "EF_" + gas.upper() + "_KG"
    return None
