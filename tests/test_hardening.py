"""Hardening for unseen data, tested on small INVENTED lines (no test-set lines):
1. no silent failures (unreadable quantity, activity item with an uncovered unit),
2. number/unit parsing with thousand separators and Latin units,
3. piece weights from packaging_specs.csv -> grams in the name,
4. mixed-factor flight routes."""

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run import run_pipeline  # noqa: E402
from src.convert import parse_grams, parse_kg, parse_km, parse_number  # noqa: E402
from src.load import ROOT, load_airports, load_factors, load_ledgers, load_packaging, normalise, parse_quantity  # noqa: E402
from src.rules import QTY_FLAG, UNIT_GAP_FLAG, classify, load_rules  # noqa: E402

NBSP = " "


@pytest.fixture(scope="module")
def ctx():
    return {
        "rules": load_rules(ROOT / "rules.yaml"),
        "factors": load_factors(),
        "airports": load_airports(),
        "packaging": load_packaging(),
    }


def make_row(description, gl, unit, quantity, gross=112_000.0, vat=12_000.0, line_id="X00001"):
    """An invented ledger line, normalised exactly like the real ones."""
    raw = pd.DataFrame(
        [
            {
                "line_id": line_id,
                "posting_date": "2025-06-01",
                "doc_no": f"INV-{line_id}",
                "counterparty": "VENDOR_TEST",
                "description": description,
                "gl_account": gl,
                "cost_center": "Plant",
                "quantity": quantity,
                "unit": unit,
                "amount_kzt_gross": gross,
                "vat_kzt": vat,
            }
        ]
    )
    return normalise(raw).iloc[0]


def run_row(ctx, row, packaging=None):
    pk = ctx["packaging"] if packaging is None else packaging
    return classify(row, ctx["rules"], ctx["factors"], ctx["airports"], pk)


# ---------------------------------------------------------------- 1. no silent failures
def test_parse_quantity_keeps_values_and_marks_unreadable():
    values, unreadable = parse_quantity(pd.Series(["12", "1 500", "2,5", f"3{NBSP}000", "abc", "", None]))
    assert values.iloc[:4].tolist() == [12.0, 1500.0, 2.5, 3000.0]
    assert values.iloc[4:].isna().all()  # NaN, never silently 0
    assert unreadable.tolist() == [False, False, False, False, True, True, True]


def test_numeric_quantities_pass_through_unchanged():
    s = pd.Series([229632.0, -2234.0, 0.54])
    values, unreadable = parse_quantity(s)
    assert values.tolist() == s.tolist() and not unreadable.any()


def test_unreadable_quantity_on_activity_line_is_flagged_not_zeroed(ctx):
    row = make_row("Молоко сырое (тестовая партия)", "1310", "кг", "n/a")
    assert math.isnan(row["quantity"]) and row["quantity_unreadable"]
    res, unit_gap = run_row(ctx, row)
    assert unit_gap and res["method"] == "review" and res["tco2e"] is None
    assert res["category"] == "S3_C1_GOODS" and res["ef_id"] == "EF_MILK_KG"


def test_unreadable_quantity_on_spend_line_still_flagged(ctx):
    row = make_row("Консалтинговые услуги (тест)", "7211", "усл", "")
    res, unit_gap = run_row(ctx, row)
    assert res["ef_id"] == "SP_SERVICES_PROF" and res["tco2e"] == pytest.approx(100 * 0.25 / 1000)
    assert row["quantity_unreadable"] and not unit_gap


def test_unconvertible_physical_item_is_held(ctx):
    # No verified kg per bag.
    row = make_row("Сахар-песок тестовый", "1312", "мешок", 40)
    res, unit_gap = run_row(ctx, row)
    assert unit_gap and res["method"] == "review" and UNIT_GAP_FLAG in res["review_flag"]


def test_unmeasurable_refrigerant_is_held_before_maintenance_spend(ctx):
    row = make_row("Сервисное обслуживание, дозаправка фреона (тест)", "8111", "усл", 1)
    res, unit_gap = run_row(ctx, row)
    assert res["rule_id"] == "REFRIGERANT" and res["method"] == "review"
    assert unit_gap and UNIT_GAP_FLAG in res["review_flag"]


def test_normal_lines_get_no_hardening_flags(ctx):
    for row in [
        make_row("Молоко сырое (тест)", "1310", "л", 1000),
        make_row("Транспортные услуги (тест)", "7110", "рейс", 1),  # freight spend is normal
        make_row("Электроэнергия тест, завод", "8110", "МВт·ч", 2),
    ]:
        res, unit_gap = run_row(ctx, row)
        assert res is not None and not res["review_flag"] and not unit_gap


def test_flags_reach_audit_and_predictions_end_to_end():
    df = load_ledgers()
    extra = pd.concat(
        [
            make_row("Сахар-песок тестовый", "1312", "мешок", 40, line_id="X90001").to_frame().T,
            make_row("Молоко сырое тестовое", "1310", "кг", "abc", line_id="X90002").to_frame().T,
        ]
    )
    extra["set"] = "test"
    _, audit = run_pipeline(pd.concat([df, extra], ignore_index=True))
    a = audit.set_index("line_id")
    assert UNIT_GAP_FLAG in a.loc["X90001", "review_flag"] and a.loc["X90001", "method"] == "review"
    assert QTY_FLAG in a.loc["X90002", "review_flag"]
    assert a.loc[["X90001", "X90002"], "tco2e"].isna().all()


# ---------------------------------------------------------------- 2. parsing
@pytest.mark.parametrize(
    "text, expected",
    [
        ("дозаправка r404a 11.1 кг", 11.1),  # existing format still works
        ("дозаправка r404a 1 500 кг", 1500.0),  # space as thousand separator
        (f"дозаправка 1{NBSP}500,5 кг", 1500.5),  # no-break space + decimal comma
        ("refill r134a 12 kg", 12.0),  # Latin unit
        ("refill 2 750.25kg", 2750.25),
    ],
)
def test_parse_kg(text, expected):
    assert parse_kg(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("алматы-ташкент, 41.1 т, 3100 км", 3100.0),
        ("алматы-ташкент, 41.1 т, 3 100 км", 3100.0),
        (f"route a-b, 12 т, 1{NBSP}250 km", 1250.0),
    ],
)
def test_parse_km(text, expected):
    assert parse_km(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("преформа пэт 28 г, 1,5 л", 28.0),
        ("преформа pet 22г 0,9л", 22.0),
        ("preform pet 30 g, 1 l", 30.0),
        ("крышка 1 250 г упаковка", 1250.0),
    ],
)
def test_parse_grams(text, expected):
    assert parse_grams(text) == pytest.approx(expected)


def test_parsers_do_not_misread():
    assert parse_grams("крышка 28 kg") is None  # kg is not grams
    assert parse_kg("r404a баллон") is None  # the 404 in the gas name is not a weight
    assert parse_km("41.1 т") is None
    assert parse_number("12 34") is None  # not a valid thousands group
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


def test_no_default_for_unknown_cap(ctx):
    row = make_row("Крышка тестовая без веса", "1311", "шт", 1000)
    res, _ = run_row(ctx, row, packaging={})
    assert res["ef_id"] == "EF_HDPE_KG" and res["method"] == "review"
    assert res["activity_qty"] is None


def test_unidentified_preform_needs_review(ctx):
    row = make_row("Преформа ПЭТ тестовая", "1311", "шт", 1000)
    res, unit_gap = run_row(ctx, row, packaging={})
    assert unit_gap and res["method"] == "review"


# ---------------------------------------------------------------- 4. mixed flights
def test_mixed_factor_route_records_official_primary_factor_and_each_leg(ctx):
    row = make_row("Авиабилет NQZ-ALA-FRA, EMP_99, эконом", "7212", "билет", 1)
    res, _ = run_row(ctx, row)
    assert res["ef_id"] == "EF_FLIGHT_LONG_PKM"
    legs = json.loads(res["reason"].split("Leg calculations: ")[1])
    assert [(leg["from"], leg["to"]) for leg in legs] == [("NQZ", "ALA"), ("ALA", "FRA")]
    assert {leg["ef_id"] for leg in legs} == {"EF_FLIGHT_DOM_PKM", "EF_FLIGHT_LONG_PKM"}
    for leg in legs:
        assert leg["tco2e"] == pytest.approx(leg["km"] * leg["tickets"] * leg["kgCO2e_per_pkm"] / 1000)
    one = [
        run_row(ctx, make_row(f"Авиабилет {r}, EMP_99, эконом", "7212", "билет", 1))[0] for r in ("NQZ-ALA", "ALA-FRA")
    ]
    assert res["tco2e"] == pytest.approx(sum(x["tco2e"] for x in one))  # each leg keeps its factor


def test_same_factor_route_unchanged(ctx):
    row = make_row("Авиабилет ALA-TAS-ALA, EMP_99, эконом", "7212", "билет", 2)
    res, _ = run_row(ctx, row)
    assert res["ef_id"] == "EF_FLIGHT_SHORT_PKM" and "+" not in res["ef_id"]
    assert "Mixed route" not in res["reason"]


@pytest.mark.parametrize(
    "name,kg",
    [
        ("Партия: Преформа PET 1,5 л", 28),
        ("Преформа ПЭТ 0.9l", 22),
        ("Поставка: Крышка HDPE 38 мм", 2.5),
        ("Гофроящик 4-клапанный, партия 2", 350),
    ],
)
def test_official_weights_without_explicit_grams(ctx, name, kg):
    res, _ = run_row(ctx, make_row(name, "1311", "шт", 1000))
    assert res["activity_qty"] == kg and "packaging_specs.csv" in res["reason"]


@pytest.mark.parametrize(
    "description,gl,unit",
    [
        ("milk", "1310", "kg"),
        ("natural gas", "8110", "m3"),
        ("electricity", "8110", "kWh"),
        ("heat", "7210", "Gcal"),
        ("diesel", "1320", "l"),
        ("R-134a refill", "8111", "kg"),
        ("unknown packaging", "1311", "pcs"),
    ],
)
def test_physical_groups_cannot_reach_spend_fallback(ctx, description, gl, unit):
    for quantity, raw_unit in [("unknown", unit), (20, "unknown")]:
        res, _ = run_row(ctx, make_row(description, gl, raw_unit, quantity))
        assert res["method"] == "review" and res["tco2e"] is None


@pytest.mark.parametrize(
    "suffix,unit",
    [
        ("т", "т"),
        ("t", "т"),
        ("л", "л"),
        ("L", "л"),
        ("кВтч", "кВт·ч"),
        ("kWh", "кВт·ч"),
        ("Гкал", "Гкал"),
        ("Gcal", "Гкал"),
        ("км", "км"),
        ("km", "км"),
        ("kg", "кг"),
        ("г", "г"),
        ("g", "г"),
    ],
)
def test_localised_ledger_amounts_and_embedded_units(suffix, unit):
    row = make_row("test", "1310", "", f"1 500,75 {suffix}", gross="112 000,40", vat="12 000,25")
    assert row["quantity"] == 1500.75 and row["unit_code"] == unit
    assert row["net_kzt"] == pytest.approx(100000.15)


def test_unknown_vat_blocks_spend_but_known_zero_is_valid(ctx):
    bad, _ = run_row(ctx, make_row("consulting research", "7211", "усл", 1, vat="missing"))
    good, _ = run_row(ctx, make_row("consulting research", "7211", "усл", 1, vat=0))
    assert bad["method"] == "review" and bad["tco2e"] is None
    assert good["method"] == "spend" and good["tco2e"] == pytest.approx(0.028)


@pytest.mark.parametrize(
    "route",
    [
        "ALA - NQZ, separate ticket: FRA → IST",
        "ALA/NQZ; unrelated words; FRA to IST",
        "ALA-NQZ / FRA-IST",
        "ALA-NQZ FRA-IST",
    ],
)
def test_disconnected_routes_never_create_a_transfer(ctx, route):
    res, _ = run_row(ctx, make_row(f"Flight {route}", "7212", "билет", 1))
    legs = json.loads(res["reason"].split("Leg calculations: ")[1])
    assert [(leg["from"], leg["to"]) for leg in legs] == [("ALA", "NQZ"), ("FRA", "IST")]


def test_ticket_quantities_and_unknown_endpoints(ctx):
    row = make_row("Flight ticket 1: NQZ-ALA-FRA, ticket 2: FRA-NQZ", "7212", "билет", 2)
    res, _ = run_row(ctx, row)
    legs = json.loads(res["reason"].split("Leg calculations: ")[1])
    assert [leg["tickets"] for leg in legs] == [1, 1, 1]
    for route, qty in [("ALA-NQZ-XYZ", 1), ("NQZ-ALA-FRA, ticket 1: IST-FRA; ticket 2: FRA-IST", 3)]:
        res, _ = run_row(ctx, make_row("Flight " + route, "7212", "билет", qty))
        assert res["method"] == "review"


def test_unnumbered_party_flies_every_listed_leg(ctx):
    # No numbered tickets: the quantity is the party size on each leg, connected or not.
    res, _ = run_row(ctx, make_row("Flight ALA-NQZ; FRA-IST. Party of 2", "7212", "билет", 2))
    legs = json.loads(res["reason"].split("Leg calculations: ")[1])
    assert [(leg["from"], leg["to"], leg["tickets"]) for leg in legs] == [("ALA", "NQZ", 2), ("FRA", "IST", 2)]


def test_the_word_ticket_alone_is_not_a_ticket_label(ctx):
    row = make_row(
        "Flight: Ticket 1: ALA-NQZ-ALA; Ticket 2: CIT-ALA. Each ticket is for one passenger.", "7212", "билет", 2
    )
    res, _ = run_row(ctx, row)
    legs = json.loads(res["reason"].split("Leg calculations: ")[1])
    assert [leg["tickets"] for leg in legs] == [1, 1, 1]


@pytest.mark.parametrize("unit", ["service", "Services", "услуга"])
def test_english_and_russian_service_units_parse_refrigerant_kg(ctx, unit):
    res, _ = run_row(ctx, make_row("Maintenance; refrigerant R134a refill 3.75 kg", "8111", unit, 1))
    assert res["method"] == "activity" and res["activity_qty"] == pytest.approx(3.75)


@pytest.mark.parametrize("unit", ["тыс. шт", "тыс.шт"])
def test_thousands_of_pieces(ctx, unit):
    res, _ = run_row(ctx, make_row("Крышка HDPE 38 мм", "1311", unit, "7,5"))
    assert res["activity_qty"] == pytest.approx(7500 * 0.0025) and "thousands of pieces" in res["reason"]


def test_incomplete_run_exports_diagnostic_only(ctx, tmp_path, monkeypatch):
    import run

    row = make_row("Electricity", "8110", "unknown", 50).to_frame().T
    row["set"] = "test"
    df, audit = run_pipeline(row)
    monkeypatch.setattr(run, "run_pipeline", lambda: (df, audit))
    monkeypatch.setattr(run, "OUT", tmp_path)
    with pytest.raises(SystemExit, match="1 unresolved"):
        run.main()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["audit.review.csv"]
    with pytest.raises(ValueError, match="Resolve all"):
        run.summarise(audit)


def test_refrigerant_mass_in_grams(ctx):
    res, _ = run_row(ctx, make_row("R134a", "1330", "g", "1 500,5"))
    assert res["ef_id"] == "EF_R134A_KG" and res["activity_qty"] == pytest.approx(1.5005)


# ---------------------------------------------------------------- Cat 4 overlap and reporting basis
def test_fuel_and_freight_for_one_carrier_are_flagged_not_changed():
    from run import summarise
    from src.duplicates import FREIGHT_OVERLAP_FLAG, FUEL_OVERLAP_FLAG

    rows = [
        make_row("ДТ для наемного транспорта (перевозчик ИП VENDOR_901)", "1320", "л", 500, line_id="X91001"),
        make_row("Перевозка продукции Алматы–Тараз, 500 км, 10.0 т", "7110", "ткм", 5000, line_id="X91002"),
        make_row("Перевозка продукции Алматы–Тараз, 500 км, 10.0 т", "7110", "ткм", 5000, line_id="X91003"),
    ]
    for row, carrier in zip(rows, ["VENDOR_900", "VENDOR_901", "VENDOR_902"], strict=False):
        row["counterparty"] = carrier  # fuel seller, the hired carrier itself, another carrier
    extra = pd.DataFrame(rows)
    extra["set"] = "test"
    _, audit = run_pipeline(pd.concat([load_ledgers(), extra], ignore_index=True))
    a = audit.set_index("line_id")
    assert FUEL_OVERLAP_FLAG in a.loc["X91001", "review_flag"]
    assert FREIGHT_OVERLAP_FLAG in a.loc["X91002", "review_flag"]
    assert "double count" not in str(a.loc["X91003", "review_flag"])
    assert a.loc["X91001", "tco2e"] == pytest.approx(500 * 2.68 / 1000)  # flag only, numbers unchanged
    assert a.loc["X91002", "tco2e"] == pytest.approx(5000 * 0.11 / 1000)
    basis = summarise(audit).set_index("category")["basis"]
    assert basis["S2_ELECTRICITY"].startswith("location-based") and "market-based equal" in basis["S2_ELECTRICITY"]


def test_kazakh_dana_means_pieces(ctx):
    res, _ = run_row(ctx, make_row("Крышка HDPE 38 мм", "1311", "дана", "10 000"))
    assert res["activity_qty"] == pytest.approx(25.0)


def test_measured_volume_in_text_repairs_a_physical_unit_that_cannot_convert(ctx):
    row = make_row(
        "Природный газ котельная\nMetered consumed volume: 2 500 m3. Накладная ошибочно в kg.", "8110", "kg", 1800
    )
    res, _ = run_row(ctx, row)
    assert res["method"] == "activity" and res["activity_qty"] == pytest.approx(2500)
    assert "taken from the description" in res["reason"]


def test_count_units_never_take_a_quantity_from_text(ctx):
    # 40 bags of 50 kg is 2,000 kg; reading "50 кг" as the quantity would be wrong, so it stays in review
    res, _ = run_row(ctx, make_row("Сахар-песок мешок 50 кг", "1312", "мешок", 40))
    assert res["method"] == "review"


def test_masking_codes_do_not_steer_the_ml_fallback():
    from src.fallback import features

    df = pd.DataFrame(
        {
            "text": [
                "внешнее заключение по договору; сотрудник emp_03; vendor_012.",
                "внешнее заключение по договору; ; .",
            ],
            "gl": ["7211", "7211"],
        }
    )
    a, b = features(df)
    assert a.split() == b.split()
