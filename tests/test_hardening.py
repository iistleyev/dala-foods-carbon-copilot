"""Hardening for unseen data, tested on small INVENTED lines (no test-set lines):
1. no silent failures (unreadable quantity, activity item with an uncovered unit),
2. number/unit parsing with thousand separators and Latin units,
3. piece weights from packaging_specs.csv -> grams in the name -> rules.yaml default,
4. mixed-factor flight routes."""
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run import run_pipeline  # noqa: E402
from src.convert import parse_grams, parse_kg, parse_km, parse_number  # noqa: E402
from src.load import (ROOT, load_airports, load_factors, load_ledgers, load_packaging,  # noqa: E402
                      normalise, parse_quantity)
from src.rules import QTY_FLAG, UNIT_GAP_FLAG, classify, load_rules, review_flags  # noqa: E402

NBSP = " "


@pytest.fixture(scope="module")
def ctx():
    return {"rules": load_rules(ROOT / "rules.yaml"), "factors": load_factors(),
            "airports": load_airports(), "packaging": load_packaging()}


def make_row(description, gl, unit, quantity, gross=112_000.0, vat=12_000.0, line_id="X00001"):
    """An invented ledger line, normalised exactly like the real ones."""
    raw = pd.DataFrame([{"line_id": line_id, "posting_date": "2025-06-01", "doc_no": f"INV-{line_id}",
                         "counterparty": "VENDOR_TEST", "description": description, "gl_account": gl,
                         "cost_center": "Plant", "quantity": quantity, "unit": unit,
                         "amount_kzt_gross": gross, "vat_kzt": vat}])
    return normalise(raw).iloc[0]


def run_row(ctx, row, packaging=None):
    pk = ctx["packaging"] if packaging is None else packaging
    return classify(row, ctx["rules"], ctx["factors"], ctx["airports"], pk)


# ---------------------------------------------------------------- 1. no silent failures
def test_parse_quantity_keeps_values_and_marks_unreadable():
    values, unreadable = parse_quantity(pd.Series(["12", "1 500", "2,5", f"3{NBSP}000", "abc", "", None]))
    assert values.iloc[:4].tolist() == [12.0, 1500.0, 2.5, 3000.0]
    assert values.iloc[4:].isna().all()               # NaN, never silently 0
    assert unreadable.tolist() == [False, False, False, False, True, True, True]


def test_numeric_quantities_pass_through_unchanged():
    s = pd.Series([229632.0, -2234.0, 0.54])
    values, unreadable = parse_quantity(s)
    assert values.tolist() == s.tolist() and not unreadable.any()


def test_unreadable_quantity_on_activity_line_is_flagged_not_zeroed(ctx):
    row = make_row("Молоко сырое (тестовая партия)", "1310", "кг", "n/a")
    assert math.isnan(row["quantity"]) and row["quantity_unreadable"]
    res, unit_gap = run_row(ctx, row)
    assert res is None and unit_gap is False          # no milk number from an unreadable quantity
    assert review_flags(row, {"method": "spend"}, unit_gap) == [QTY_FLAG]


def test_unreadable_quantity_on_spend_line_still_flagged(ctx):
    row = make_row("Консалтинговые услуги (тест)", "7211", "усл", "")
    res, unit_gap = run_row(ctx, row)
    assert res["ef_id"] == "SP_SERVICES_PROF" and res["tco2e"] == pytest.approx(100 * 0.25 / 1000)
    assert review_flags(row, res, unit_gap) == [QTY_FLAG]


def test_activity_item_with_uncovered_unit_falls_through_and_is_flagged(ctx):
    # Sugar in "мешок" (bags): the sugar rule has no conversion for it -> ML fallback (spend)
    row = make_row("Сахар-песок тестовый", "1312", "мешок", 40)
    res, unit_gap = run_row(ctx, row)
    assert res is None and unit_gap is True
    assert review_flags(row, {"method": "spend"}, unit_gap) == [UNIT_GAP_FLAG]


def test_refrigerant_service_without_kg_falls_to_spend_rule_and_is_flagged(ctx):
    row = make_row("Сервисное обслуживание, дозаправка фреона (тест)", "8111", "усл", 1)
    res, unit_gap = run_row(ctx, row)
    assert res["rule_id"] == "SP_MAINTENANCE" and res["method"] == "spend"
    assert UNIT_GAP_FLAG in review_flags(row, res, unit_gap)


def test_normal_lines_get_no_hardening_flags(ctx):
    for row in [make_row("Молоко сырое (тест)", "1310", "л", 1000),
                make_row("Транспортные услуги (тест)", "7110", "рейс", 1),   # freight spend is normal
                make_row("Электроэнергия тест, завод", "8110", "МВт·ч", 2)]:
        res, unit_gap = run_row(ctx, row)
        assert res is not None and review_flags(row, res, unit_gap) == []


def test_flags_reach_audit_and_predictions_end_to_end():
    df = load_ledgers()
    extra = pd.concat([make_row("Сахар-песок тестовый", "1312", "мешок", 40, line_id="X90001").to_frame().T,
                       make_row("Молоко сырое тестовое", "1310", "кг", "abc", line_id="X90002").to_frame().T])
    extra["set"] = "test"
    _, audit = run_pipeline(pd.concat([df, extra], ignore_index=True))
    a = audit.set_index("line_id")
    assert UNIT_GAP_FLAG in a.loc["X90001", "review_flag"] and a.loc["X90001", "method"] == "spend"
    assert QTY_FLAG in a.loc["X90002", "review_flag"]
    assert not a.loc[["X90001", "X90002"], "tco2e"].isna().any()  # still a number in predictions


# ---------------------------------------------------------------- 2. parsing
@pytest.mark.parametrize("text, expected", [
    ("дозаправка r404a 11.1 кг", 11.1),               # existing format still works
    ("дозаправка r404a 1 500 кг", 1500.0),            # space as thousand separator
    (f"дозаправка 1{NBSP}500,5 кг", 1500.5),          # no-break space + decimal comma
    ("refill r134a 12 kg", 12.0),                     # Latin unit
    ("refill 2 750.25kg", 2750.25),
])
def test_parse_kg(text, expected):
    assert parse_kg(text) == pytest.approx(expected)


@pytest.mark.parametrize("text, expected", [
    ("алматы-ташкент, 41.1 т, 3100 км", 3100.0),
    ("алматы-ташкент, 41.1 т, 3 100 км", 3100.0),
    (f"route a-b, 12 т, 1{NBSP}250 km", 1250.0),
])
def test_parse_km(text, expected):
    assert parse_km(text) == pytest.approx(expected)


@pytest.mark.parametrize("text, expected", [
    ("преформа пэт 28 г, 1,5 л", 28.0),
    ("преформа pet 22г 0,9л", 22.0),
    ("preform pet 30 g, 1 l", 30.0),
    ("крышка 1 250 г упаковка", 1250.0),
])
def test_parse_grams(text, expected):
    assert parse_grams(text) == pytest.approx(expected)


def test_parsers_do_not_misread():
    assert parse_grams("крышка 28 kg") is None        # kg is not grams
    assert parse_kg("r404a баллон") is None           # the 404 in the gas name is not a weight
    assert parse_km("41.1 т") is None
    assert parse_number("12 34") is None              # not a valid thousands group
    assert parse_number(f"1{NBSP}500") == 1500.0


# ---------------------------------------------------------------- 3. packaging weights
def test_packaging_specs_loaded_on_normalised_name():
    pk = load_packaging()
    assert len(pk) == 6 and pk["крышка hdpe 38 мм"] == pytest.approx(0.0025)


def test_piece_weight_from_specs_beats_grams_in_name(ctx):
    row = make_row("Преформа ПЭТ тестовая 30 г", "1311", "шт", 1000)
    res, _ = run_row(ctx, row, packaging={"преформа пэт тестовая 30 г": 0.031})
    assert res["activity_qty"] == pytest.approx(31.0) and "packaging_specs.csv" in res["reason"]


def test_piece_weight_from_grams_in_name(ctx):
    row = make_row("Преформа ПЭТ тестовая 30 г", "1311", "шт", 1000)
    res, _ = run_row(ctx, row, packaging={})
    assert res["activity_qty"] == pytest.approx(30.0) and "grams in the item name" in res["reason"]


def test_piece_weight_rules_yaml_default_last(ctx):
    row = make_row("Крышка тестовая без веса", "1311", "шт", 1000)
    res, _ = run_row(ctx, row, packaging={})
    assert res["ef_id"] == "EF_HDPE_KG" and res["activity_qty"] == pytest.approx(2.5)
    assert "rules.yaml default" in res["reason"]


def test_pieces_with_no_weight_anywhere_fall_through_and_are_flagged(ctx):
    # PET has no rules.yaml default for шт (it relies on grams in the name)
    row = make_row("Преформа ПЭТ тестовая", "1311", "шт", 1000)
    res, unit_gap = run_row(ctx, row, packaging={})
    assert res is None and unit_gap is True


# ---------------------------------------------------------------- 4. mixed flights
def test_mixed_factor_route_joins_factors_and_lists_legs(ctx):
    row = make_row("Авиабилет NQZ-ALA-FRA, EMP_99, эконом", "7212", "билет", 1)
    res, _ = run_row(ctx, row)
    assert res["ef_id"] == "EF_FLIGHT_DOM_PKM+EF_FLIGHT_LONG_PKM"
    assert "NQZ-ALA" in res["reason"] and "ALA-FRA" in res["reason"] and "km" in res["reason"]
    one = [run_row(ctx, make_row(f"Авиабилет {r}, EMP_99, эконом", "7212", "билет", 1))[0]
           for r in ("NQZ-ALA", "ALA-FRA")]
    assert res["tco2e"] == pytest.approx(sum(x["tco2e"] for x in one))     # each leg keeps its factor


def test_same_factor_route_unchanged(ctx):
    row = make_row("Авиабилет ALA-TAS-ALA, EMP_99, эконом", "7212", "билет", 2)
    res, _ = run_row(ctx, row)
    assert res["ef_id"] == "EF_FLIGHT_SHORT_PKM" and "+" not in res["ef_id"]
    assert "Mixed route" not in res["reason"]
