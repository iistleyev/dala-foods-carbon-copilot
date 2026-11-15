"""Conversions for ledger quantities, package weights and flight itineraries."""

import math
import re

THOUSANDS = r"[ \u00a0\u202f]"
NUM = rf"([+-]?(?:\d{{1,3}}(?:{THOUSANDS}\d{{3}})+|\d+)(?:[.,]\d+)?)"
EARTH_RADIUS_KM = 6371.0
LONG_HAUL_KM = 3700.0

# Ledger unit, accepted spellings in either the unit column or an amount such as "1 500 kWh".
SUFFIXES = {
    "кг": ("кг", "kg"),
    "км": ("км", "km"),
    "г": ("г", "g"),
    "т": ("т", "t"),
    "л": ("л", "l"),
    "кВт·ч": ("квт·ч", "квт*ч", "квт.ч", "квтч", "kwh"),
    "МВт·ч": ("мвт·ч", "мвт*ч", "мвт.ч", "мвтч", "mwh"),
    "Гкал": ("гкал", "gcal"),
    "ГДж": ("гдж", "gj"),
    "м3": ("м3", "м³", "m3", "m³"),
    "тыс. м3": ("тыс. м3", "тыс. м³", "тыс.м3", "тыс м3"),
}
UNIT_ALIASES = {alias: unit for unit, aliases in SUFFIXES.items() for alias in aliases}
UNIT_PATTERN = "|".join(map(re.escape, sorted(UNIT_ALIASES, key=len, reverse=True)))
MEASUREMENT = re.compile(rf"(?<![\w.,]){NUM}\s*({UNIT_PATTERN})(?!\w)", re.I)
WEIGHT_IN_NAME = re.compile(rf"(?<!\w){NUM}\s*(?:г|g)\b", re.I)


def _num(s: str) -> float:
    return float(re.sub(THOUSANDS, "", s).replace(",", "."))


def parse_number(s):
    """'1 500,5' / '1500.5' / '1,500.5' / '1.500,5' -> float; anything unreadable -> None.
    A lone comma is a decimal comma (Kazakh/Russian style); with both separators the first is thousands."""
    s = str(s).strip()
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+\.\d+", s):
        return float(s.replace(",", ""))
    if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+,\d+", s):
        return float(s.replace(".", "").replace(",", "."))
    return _num(s) if re.fullmatch(NUM, s) else None


def parse_measure(text, unit):
    """First quantity written with the given unit in a text, or None."""
    for match in MEASUREMENT.finditer(text):
        if UNIT_ALIASES[match[2].lower()] == unit:
            return _num(match[1])
    return None


def parse_kg(text):
    """Kilograms written in a text ('11.1 кг'), or None."""
    return parse_measure(text, "кг")


def parse_km(text):
    """Kilometres written in a text ('3100 км'), or None."""
    return parse_measure(text, "км")


def parse_grams(text):
    """Grams written in a text ('28 г'), or None."""
    return parse_measure(text, "г")


def _package_key(name):
    # Remove the nominal gram weight, retaining SKU dimensions and bottle volume.
    name = WEIGHT_IN_NAME.sub(" ", name.lower()).replace("пэт", "pet")
    name = re.sub(r"(?<=\d),(?=\d)", ".", name)
    name = re.sub(r"(?<=\d)\s*[lл]\b", " л", name)
    return tuple(re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", name))


def piece_weight_kg(text, packaging):
    """Prefer the reference SKU, then the written grams, then a unique weight-free SKU."""
    if text in packaging:
        return packaging[text], "Piece weight from packaging_specs.csv."
    grams = parse_grams(text)
    if grams is not None:
        if math.isfinite(grams) and grams > 0:
            return grams / 1000, "Piece weight from grams in the item name."
        return None, None
    words = _package_key(text)
    matches = []
    for name, weight in packaging.items():
        key = _package_key(name)
        if key and any(words[i : i + len(key)] == key for i in range(len(words) - len(key) + 1)):
            matches.append(weight)
    if len(matches) == 1:
        return matches[0], "Piece weight from packaging_specs.csv."
    return None, None


def unit_multiplier(spec, text):
    """Number that converts the ledger quantity to the factor's unit."""
    if spec == "kg_in_text":
        return parse_kg(text)
    if isinstance(spec, str) and "/" in spec:
        a, b = spec.split("/")
        return float(a) / float(b)
    return float(spec)


def haversine_km(a, b) -> float:
    """Great-circle distance between two airports (R = 6371 km)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(h, 1.0)))


# A comma, semicolon or free text separates itineraries. Only connect codes joined by
# a route separator, so separate tickets never acquire a fictitious transfer leg.
ROUTE_JOIN = re.compile(r"\s*(?:->|[-‐‑–—→/>]|\b(?:to|via|до|через)\b)\s*|\s+", re.I)
IATA = re.compile(r"\b[a-z]{3}\b", re.I | re.ASCII)
# A separately listed ticket carries a number ("Ticket 1:", "билет №2"). The bare word is not a
# label: "Авиабилет ALA-NQZ" or "Each ticket is for one passenger" must not count as tickets.
TICKET_LABEL = re.compile(r"\b(?:ticket|авиабилет|билет)\s*(?:no\.?\s*|[#№]\s*)?\d+\s*:?", re.I)
AIRPORT_PAIR = re.compile(r"(?=\b([a-z]{3})\s*(?:->|[-‐‑–—→/>])\s*([a-z]{3})\b)", re.I | re.ASCII)
TICKET_BOUNDARY = re.compile(r"([-‐‑–—→]\s*[a-z]{3})(?:\s+/\s+|\s+)(?=[a-z]{3}\s*[-‐‑–—→])", re.I | re.ASCII)


def flight_legs(text: str, airports: dict):
    """Return all flown segments in document order, or None for an incomplete route."""
    # Check overlapping pairs so an unknown final stop cannot truncate a valid route.
    for pair in AIRPORT_PAIR.finditer(text):
        if any(code.upper() not in airports for code in pair.groups()):
            return None
    # Disconnected ticket strings must not acquire a fictitious transfer leg.
    text = TICKET_BOUNDARY.sub(r"\1;", text)
    codes = [m for m in IATA.finditer(text) if m[0].upper() in airports]
    legs = []
    used = set()
    for i, (left, right) in enumerate(zip(codes, codes[1:], strict=False)):
        if not ROUTE_JOIN.fullmatch(text[left.end() : right.start()]):
            continue
        a, b = left[0].upper(), right[0].upper()
        km = haversine_km(airports[a], airports[b])
        if airports[a][2] == airports[b][2] == "KZ":
            factor = "EF_FLIGHT_DOM_PKM"
        elif km < LONG_HAUL_KM:
            factor = "EF_FLIGHT_SHORT_PKM"
        else:
            factor = "EF_FLIGHT_LONG_PKM"
        legs.append((a, b, km, factor))
        used.update((i, i + 1))
    return legs if legs and len(used) == len(codes) else None


def ticket_counts(text, legs, quantity, airports):
    """A ledger quantity applies to the itinerary. Individually listed tickets count once each."""
    labels = list(TICKET_LABEL.finditer(text))
    if len(labels) < 2:
        # No separately numbered tickets: the quantity is the party size and flies every listed leg,
        # connected or not ("ALA-NQZ; DXB-FRA", 2 tickets -> 2 passengers on each leg).
        return [quantity] * len(legs)
    if abs(quantity) != len(labels):
        return None
    listed = []
    for i, label in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        trip = flight_legs(text[label.end() : end], airports)
        if not trip:
            return None
        listed.extend(trip)
    if listed != legs:
        return None
    return [math.copysign(1.0, quantity)] * len(legs)


def refrigerant_ef(text: str):
    """Refrigerant factor id named in a text (R404A, R134A, R410A, R744), or None."""
    t = text.lower().replace("-", "").replace(" ", "")
    for gas in ("r404a", "r134a", "r410a", "r744"):
        if gas in t:
            return "EF_" + gas.upper() + "_KG"
    return None
