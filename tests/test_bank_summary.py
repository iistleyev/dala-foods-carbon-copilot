"""The bank summary is one A4 page and its numbers come from the audit."""

import pandas as pd
import pymupdf

from pitch.build_bank_summary import html, numbers, write_pdf
from src.load import ROOT


def test_one_page_with_the_computed_total(tmp_path):
    page_html = html(numbers())
    audit = pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")
    total = f"{audit['tco2e'].sum():,.0f}"
    write_pdf(page_html, tmp_path / "s.pdf")
    doc = pymupdf.open(tmp_path / "s.pdf")
    text = doc[0].get_text()
    assert doc.page_count == 1
    for needed in [total, "Totals by scope", "Totals by category", "Hotspots", "kg CO2e per kg", "activity-based"]:
        assert needed in text, needed
