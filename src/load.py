"""Load the ledgers and reference tables, and normalise text, units and amounts."""
import re
from pathlib import Path

import pandas as pd

from .convert import parse_number

ROOT = Path(__file__).resolve().parent.parent

# Pipeline inputs: masked ledgers (counterparties -> VENDOR_xxx, employee names -> EMP_xx).
# Masking is one-to-one, so duplicate detection on counterparty still works.
TRAIN_FILE = "ledger_train_masked.csv"
TEST_FILE = "ledger_test_masked.csv"

# Every spelling we accept for a unit -> one canonical code (the codes used in the official data).
UNIT_MAP = {
    "кг": "кг", "кг.": "кг", "kg": "кг", "килограмм": "кг",
    "т": "т", "т.": "т", "тн": "т", "тонна": "т", "t": "т",
    "л": "л", "л.": "л", "литр": "л", "l": "л",
    "м3": "м3", "м³": "м3", "м.куб": "м3", "m3": "м3",
    "тыс. м3": "тыс. м3", "тыс.м3": "тыс. м3", "тыс м3": "тыс. м3",
    "квт·ч": "кВт·ч", "квт*ч": "кВт·ч", "квтч": "кВт·ч", "квт.ч": "кВт·ч", "kwh": "кВт·ч",
    "мвт·ч": "МВт·ч", "мвт*ч": "МВт·ч", "мвтч": "МВт·ч", "mwh": "МВт·ч",
    "гкал": "Гкал", "gcal": "Гкал",
    "гдж": "ГДж", "gj": "ГДж",
    "шт": "шт", "шт.": "шт", "pcs": "шт",
    "ткм": "ткм", "т·км": "ткм", "tkm": "ткм",
    "билет": "билет", "сут": "сут", "усл": "усл", "рейс": "рейс", "мес": "мес", "уп": "уп",
}

# Sentences that talk to an AI instead of describing a purchase. Ledger text is data, never
# instructions: we strip these before classifying so they cannot change the output.
INJECTION_RE = re.compile(
    r"ignore (all |the )?previous|instruction|assistant|ассистент|\bai\b|\bии\b|note to the model|"
    r"system note|tco2e|emission|выброс|carbon neutral|установи 0|\bexclude\b",
    re.IGNORECASE,
)


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / name, encoding="utf-8-sig", dtype={"gl_account": str})


def norm_text(s) -> str:
    """Lower-case, unify quotes/dashes, collapse whitespace."""
    s = "" if pd.isna(s) else str(s)
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»\"“”„']", "", s)
    s = re.sub(r"[–—]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_injection(raw) -> tuple[str, bool]:
    """Remove HTML comments, bracketed notes and sentences addressed to an AI.

    Returns (clean_text, was_anything_removed)."""
    s = "" if pd.isna(raw) else str(raw)
    original = s
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)
    s = re.sub(r"\[[^\]]*\]", lambda m: " " if INJECTION_RE.search(m.group(0)) else m.group(0), s)
    sentences = re.split(r"(?<=[.!?])\s+", s.strip())
    kept = [x for x in sentences if not INJECTION_RE.search(x)]
    if not kept:  # never return an empty description
        kept = sentences[:1]
    s = " ".join(kept).strip()
    return s, norm_text(s) != norm_text(original)


def norm_unit(u) -> str:
    if pd.isna(u) or str(u).strip() == "":
        return ""
    key = re.sub(r"\s+", " ", str(u).strip().lower())
    return UNIT_MAP.get(key, str(u).strip())


def parse_quantity(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Ledger quantity -> (float values, unreadable mask).

    Numbers pandas already parsed are kept as they are. Text like '1 500' or '2,5' is parsed with
    the same rules as numbers in descriptions. Missing or non-numeric stays NaN (never 0) and is
    marked unreadable, so the line gets review_flag 'quantity unreadable'."""
    num = pd.to_numeric(values, errors="coerce")
    retry = num.isna() & values.notna()
    if retry.any():
        num = num.astype(float)
        num[retry] = values[retry].map(parse_number).astype(float)
    num = num.astype(float)
    return num, num.isna()


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Add the helper columns the rules use (works on any ledger-shaped frame)."""
    df = df.copy()
    df["gl"] = df["gl_account"].fillna("").astype(str).str.strip()
    clean = df["description"].map(strip_injection)
    df["text"] = clean.map(lambda x: norm_text(x[0]))
    df["injection"] = clean.map(lambda x: x[1])
    df["raw_text"] = df["description"].map(norm_text)  # used only for duplicate matching
    df["unit_code"] = df["unit"].map(norm_unit)
    df["quantity"], df["quantity_unreadable"] = parse_quantity(df["quantity"])
    df["vat_kzt"] = pd.to_numeric(df["vat_kzt"], errors="coerce").fillna(0.0)
    df["net_kzt"] = df["amount_kzt_gross"] - df["vat_kzt"]
    return df


def load_ledgers() -> pd.DataFrame:
    """Train + test in one frame with normalised helper columns."""
    train = read_csv(TRAIN_FILE)
    test = read_csv(TEST_FILE)
    train["set"], test["set"] = "train", "test"
    df = normalise(pd.concat([train, test], ignore_index=True))
    return df.sort_values("line_id").reset_index(drop=True)


def load_packaging() -> dict:
    """packaging_specs.csv -> {normalised item name: kg per piece}."""
    spec = read_csv("packaging_specs.csv")
    return {norm_text(r.item): float(r.unit_weight_g) / 1000 for r in spec.itertuples()}


def load_factors() -> dict:
    ef = read_csv("emission_factors.csv")
    return {r.ef_id: {"value": float(r.kgCO2e_per_unit), "unit": r.unit,
                      "category": r.typical_category} for r in ef.itertuples()}


def load_airports() -> dict:
    ap = read_csv("airports.csv")
    return {r.iata: (float(r.lat), float(r.lon), r.country) for r in ap.itertuples()}
