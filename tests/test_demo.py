"""The live demo's processing function (src/demo.py) on data/demo_lines.csv, without the UI."""
import hashlib

import pytest

from src.demo import UploadError, process, read_upload, validate
from src.load import ROOT

DEMO = ROOT / "data" / "demo_lines.csv"


@pytest.fixture(scope="module")
def result():
    pred = ROOT / "outputs" / "predictions.csv"
    before = hashlib.sha256(pred.read_bytes()).hexdigest()
    res = process(read_upload(DEMO.read_bytes()))
    assert hashlib.sha256(pred.read_bytes()).hexdigest() == before   # the demo never writes outputs/
    return res


def line(result, line_id):
    return result["rows"].set_index("line_id").loc[line_id]


def test_ten_result_rows_only_demo_lines(result):
    assert len(result["rows"]) == 10 and len(result["results"]) == 10
    assert set(result["audit"]["set"]) == {"demo"}


def test_tax_line_is_excluded(result):
    assert line(result, "N26008")["category"] == "EXCLUDE"


def test_unknown_unit_lands_in_review_and_does_not_stop_the_run(result):
    assert line(result, "N26010")["method"] == "review"
    assert list(result["review"]["line_id"]) == ["N26010"]
    assert result["stats"]["calculated"] == 8


def test_injection_line_is_not_excluded_and_is_flagged(result):
    row = line(result, "N26009")
    assert row["category"] != "EXCLUDE" and row["tco2e"] > 0
    assert "instruction-like text ignored" in row["review_flag"]
    assert list(result["injection"]["line_id"]) == ["N26009"]


def test_hidden_refrigerant_calculation_is_written_out(result):
    row = line(result, "N26004")
    assert row["category"] == "S1_FUGITIVE" and row["tco2e"] == pytest.approx(15 * 3943 / 1000)
    assert row["calculation"] == "15 kg × 3 943 kgCO2e/kg / 1000 = 59.1450 tCO2e"


def test_missing_column_gives_a_message_not_a_crash():
    frame = read_upload((ROOT / "data" / "demo_bad_columns.csv").read_bytes())
    assert validate(frame) and "vat_kzt" in validate(frame)[0]
    with pytest.raises(UploadError, match="vat_kzt"):
        process(frame)


def test_semicolon_and_cp1251_files_read_the_same():
    plain = read_upload(DEMO.read_bytes())
    text = DEMO.read_bytes().decode("utf-8-sig")
    semicolon = plain.to_csv(index=False, sep=";").encode("cp1251", errors="replace")
    other = read_upload(semicolon)
    assert list(other.columns) == list(plain.columns) and len(other) == len(plain)
    assert other["description"].tolist()[0] == plain["description"].tolist()[0]
    assert "Молако" in text


def test_garbage_file_is_a_message():
    with pytest.raises(UploadError):
        read_upload(b"")
