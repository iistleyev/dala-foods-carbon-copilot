"""Use fictitious names and verify masking before either split is published."""
import pandas as pd
import pytest

from mask_ledger import FILES, LedgerMasker, main


@pytest.mark.parametrize("name", [
    "Иван Петров", "Ілияс Төлегенов", "Jane Mary Smith", "DOE JOHN", "Smith A.",
    "Smith A.B.", "J. K. Smith", "J.K.", "А.Б.", "Jane M. Smith", "John O'Neill", "employee: jane smith",
    'ТОО «Тест Сервис»', 'TOO "Example Supplies"', "ИП Тестов", "АО Альфа Бета",
    "LLP Example Gate", "Example & Test LLC", "sample partner llp",
])
def test_names_and_legal_entities_are_masked(name):
    masker = LedgerMasker(["Private Holdings LLP"])
    text = masker.mask_desc("delivery, " + name + ", 20 kg")
    assert text.startswith("delivery, ") and text.endswith(", 20 kg")
    token = text.removeprefix("delivery, ").removesuffix(", 20 kg").removeprefix("employee: ")
    assert token.startswith(("EMP_", "VENDOR_")) and token.rsplit("_", 1)[1].isdigit()
    assert text == masker.mask_desc("delivery, " + name + ", 20 kg")


def test_names_in_descriptions_and_route_tokens():
    masker = LedgerMasker(["North Example LLC"])
    text = masker.mask_desc("Авиабилет ALA-NQZ-ALA, J. Smith, north example, 20 kWh")
    assert text == "Авиабилет ALA-NQZ-ALA, EMP_01, VENDOR_001, 20 kWh"
    assert masker.mask_desc("Преформа ПЭТ 28 г") == "Преформа ПЭТ 28 г"


def test_fail_closed_for_unresolved_marker_in_second_split(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # A bare marker with no name on either side is deliberately unresolvable.
    for name, desc in zip(FILES, ["local service", "invoice; LLP: ???"]):
        pd.DataFrame([{"line_id": "X123", "counterparty": "North Example LLC",
                       "description": desc}]).to_csv(name, index=False)
    with pytest.raises(ValueError, match="X123"):
        main()
    assert len(list(tmp_path.glob("*_masked.csv"))) == 0
    assert not (tmp_path / "mask_mapping.csv").exists()
