"""One-page summary for the bank:  python pitch/build_bank_summary.py

Writes pitch/bank_summary.html and pitch/bank_summary.pdf (A4, one page): totals by scope and
category, activity vs spend share, hotspots and kg CO2e per kg of product. Every number is computed
from outputs/audit.csv (run run.py first) with the same code as pitch/build_pitch.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from pitch.build_pitch import PRODUCT_T, compute
from src.load import load_factors, read_csv
from src.memo import memo_items

OUT = ROOT / "pitch"
SCOPE_TEXT = {
    "S1": "Scope 1: own fuel, boiler gas, refrigerant leaks",
    "S2": "Scope 2: purchased electricity and district heat (location-based)",
    "S3": "Scope 3: purchased goods and services, capital goods, transport, waste, travel",
}
CSS = """
* { font-family: sans-serif; color: #0b0b0b; }
body { font-size: 9pt; }
h1 { font-size: 15pt; margin: 0 0 2pt 0; }
h2 { font-size: 10.5pt; margin: 9pt 0 3pt 0; color: #2a78d6; }
p.sub { font-size: 8pt; color: #5f5e58; margin: 0 0 6pt 0; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; font-size: 8pt; color: #5f5e58; border-bottom: 1px solid #999; padding: 2pt 4pt; }
td { padding: 2pt 4pt; border-bottom: 1px solid #e3e2dd; font-size: 8.5pt; }
td.n, th.n { text-align: right; }
tr.total td { font-weight: bold; border-top: 1px solid #999; }
table.kpi td { border: none; text-align: center; padding: 4pt; width: 25%; }
.big { font-size: 15pt; font-weight: bold; }
.lbl { font-size: 7.5pt; color: #5f5e58; }
ul { margin: 0; padding-left: 12pt; }
li { font-size: 8pt; margin-bottom: 1pt; }
p.foot { font-size: 7pt; color: #5f5e58; margin-top: 6pt; }
"""


def numbers():
    """Pitch numbers plus per-category activity shares, memo rows and category names."""
    n = compute(run_stress=False)
    audit = pd.read_csv(ROOT / "outputs" / "audit.csv", encoding="utf-8-sig")
    counted = audit[audit["method"].isin(["activity", "spend"])]
    activity = counted[counted["method"] == "activity"].groupby("category")["tco2e"].sum()
    n["activity_share_by_category"] = (activity / counted.groupby("category")["tco2e"].sum()).fillna(0).to_dict()
    n["memo"] = memo_items(audit, load_factors())
    n["category_names"] = dict(read_csv("categories.csv")[["category", "meaning"]].values)
    return n


def _t(x):
    return f"{x:,.0f}"


def html(n) -> str:
    """The one-page summary as HTML (also used for the PDF)."""
    inv, prod = n["inventory"], n["product"]
    total = inv["total_tco2e"]
    s12 = inv["by_scope_tco2e"].get("S1", 0) + inv["by_scope_tco2e"].get("S2", 0)
    groups = {g["group"]: g for g in n["purchase_groups"]}
    memo = n["memo"].set_index("category")["tco2e"]

    kpi = (
        '<table class="kpi"><tr>'
        f'<td><div class="big">{_t(total)}</div><div class="lbl">tCO2e in 2025 (Scope 1+2+3)</div></td>'
        f'<td><div class="big">{prod["kgco2e_per_kg"]:.3f}</div><div class="lbl">kg CO2e per kg of product '
        f"({prod['kgco2e_per_l']:.3f} per litre), average of {PRODUCT_T:,} t</div></td>"
        f'<td><div class="big">{inv["activity_share"]:.1%}</div><div class="lbl">activity-based '
        f"(measured quantities); {inv['spend_share']:.1%} spend-based</div></td>"
        f'<td><div class="big">{_t(s12)}</div><div class="lbl">tCO2e Scope 1+2 ({s12 / total:.0%}), '
        "the part the green loan can change</div></td></tr></table>"
    )
    scope_rows = "".join(
        f'<tr><td>{SCOPE_TEXT[s]}</td><td class="n">{_t(v)}</td><td class="n">{v / total:.1%}</td></tr>'
        for s, v in sorted(inv["by_scope_tco2e"].items())
    )
    cat_rows = "".join(
        f"<tr><td>{c}</td><td>{n['category_names'].get(c, '').split(' - ')[-1]}</td>"
        f'<td class="n">{_t(v)}</td><td class="n">{v / total:.1%}</td>'
        f'<td class="n">{n["activity_share_by_category"].get(c, 0):.1%}</td></tr>'
        for c, v in inv["by_category_tco2e"].items()
    )
    hot_rows = "".join(
        f'<tr><td>{i}. {g}</td><td class="n">{_t(groups[g]["tco2e"])}</td><td class="n">{share:.1%}</td></tr>'
        for i, (g, share) in enumerate(n["hotspots"].items(), 1)
    )
    cat12 = memo.get("Scope 3 Cat 12 end of life of sold packaging (indicative)", 0)
    non_co2 = memo.get("CH4 + N2O from fuel combustion, Scope 1", 0)
    basis = [
        "GHG Protocol Corporate Standard, operational control, calendar year 2025 (first inventory = base year).",
        f"Scope 2 location-based; market-based is the same ({_t(memo.get('Scope 2 market-based', 0))} t): "
        "no certificates or supplier factors, no residual mix for Kazakhstan.",
        "Factors exactly as in the case file: IPCC 2006 Tier 1 fuels (CO2 only), refrigerant GWPs from IPCC AR5, "
        "Kazakhstan grid 0.8 kg/kWh. Refrigerant refills counted as leaks.",
        f"Not in the total (memo): Scope 3 Cat 12 packaging end of life about {_t(cat12)} t; CH4/N2O from fuel "
        f"about {_t(non_co2)} t; Cat 3 upstream fuel and grid losses not estimated (no factor in the case).",
        f"All {inv['lines']:,} ledger lines traced to a rule, a factor and a reason (outputs/audit.csv); "
        "duplicates, taxes, advances, fines and per diem excluded with a reason; "
        f"{inv['lines_flagged']} lines carry a review note, none is unresolved.",
    ]
    return (
        f"<html><head><style>{CSS}</style></head><body>"
        "<h1>Dala Foods LLP: GHG inventory 2025, summary for the bank</h1>"
        '<p class="sub">Basis for the KZT 5 bn green-loan application · all figures in tCO2e unless stated · '
        "computed from the 2025 purchase ledger by the Carbon Copilot pipeline</p>"
        f"{kpi}"
        "<h2>Totals by scope</h2>"
        '<table><tr><th>Scope</th><th class="n">tCO2e</th><th class="n">Share</th></tr>'
        f'{scope_rows}<tr class="total"><td>Total</td><td class="n">{_t(total)}</td><td class="n">100%</td></tr></table>'
        "<h2>Totals by category</h2>"
        '<table><tr><th>Category</th><th>Meaning</th><th class="n">tCO2e</th><th class="n">Share</th>'
        f'<th class="n">Activity-based</th></tr>{cat_rows}</table>'
        "<h2>Hotspots: top 5 sources</h2>"
        f'<table><tr><th>Source</th><th class="n">tCO2e</th><th class="n">Share</th></tr>{hot_rows}</table>'
        "<h2>Basis and data quality</h2><ul>" + "".join(f"<li>{b}</li>" for b in basis) + "</ul>"
        '<p class="foot">Generated by pitch/build_bank_summary.py from outputs/audit.csv; '
        "every number is recomputed from the ledger and emission_factors.csv.</p></body></html>"
    )


def write_pdf(page_html: str, path: Path) -> float:
    """Render the HTML onto one A4 page; returns the scale used (1.0 = no shrinking needed)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    _, scale = page.insert_htmlbox(pymupdf.Rect(36, 32, 559, 810), page_html, scale_low=0)
    doc.save(path)
    return scale


def main():
    """Write bank_summary.html and bank_summary.pdf."""
    page_html = html(numbers())
    (OUT / "bank_summary.html").write_text(page_html, encoding="utf-8")
    scale = write_pdf(page_html, OUT / "bank_summary.pdf")
    print(f"Wrote pitch/bank_summary.html and pitch/bank_summary.pdf (one A4 page, scale {scale:.2f})")


if __name__ == "__main__":
    main()
