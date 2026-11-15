# Dala Foods — Carbon Copilot (Catalyst hackathon, Case 2)

Turns Dala Foods' messy 2025 purchase ledger into a **Scope 1/2/3 GHG inventory with an audit trail for
every line**. Rules + a small local ML model; **no cloud calls, no LLM, no hand-labelling**. Every number
traces to a rule, a factor from `emission_factors.csv` and a written reason.

| Result | Value |
|---|---|
| Train score (leaderboard formula) | **1.0000** (macro-F1 1.0000, WAPE 0.0000) |
| Inventory 2025, train + test | **199,638 tCO2e** — Scope 1 7.1 %, Scope 2 8.0 %, Scope 3 84.9 % |
| Per kg of product (average, 105,000 t) | 1.901 kg CO2e/kg · 1.958 kg CO2e/l |
| Biggest source | raw milk, 78.9 % |
| Tests / stress checks | 172 tests · 107/107 stress checks on invented lines |

## Setup (3 commands, Python 3.12+)

```
pip install -r requirements.txt
python run.py
python -m pytest
```

## What to run

| Command | What it does | Writes |
|---|---|---|
| `python run.py` | the pipeline; prints train score, worst lines, confusion matrix, review warnings | `outputs/predictions.csv`, `audit.csv`, `summary.csv` |
| `streamlit run app.py` | local demo page: **Live run** (upload a ledger CSV) and **Pitch** (numbers, charts, green-loan sliders) | nothing |
| `python pitch/build_pitch.py` | pitch numbers and 16:9 charts, all computed from the outputs | `pitch/pitch_numbers.md/.json`, `pitch/*.png` |
| `python analysis.py` | answers for the bank, retailer and CFO | `outputs/loan_scenarios.csv`, `product_footprint.csv`, `cost_model.csv` |
| `python report.py` | everything in one Excel workbook with live formulas | `outputs/carbon_report.xlsx` |
| `python stress_test.py` | 107 checks on invented lines: file chaos, value chaos, typos, 17 injection styles, accounting traps, determinism, fresh clone | prints a pass/fail table |
| `python make_submission.py --team 07` | builds the submission zip (no raw ledgers, no mapping) | `Team07_DalaFoods.zip` |

## Folder map

```
run.py              pipeline entry point
rules.yaml          every rule as data: keywords, GL, units, factor, conversion, reason
src/load.py         read and normalise ledgers (units, numbers, VAT, injection stripping)
src/rules.py        rule engine (first match wins; unmeasurable physical items -> review)
src/convert.py      unit conversion, flights (haversine), kg/km/grams in text
src/duplicates.py   duplicate postings; fuel/freight overlap for one carrier
src/fallback.py     ML fallback for unseen spend lines (TF-IDF + logistic regression)
src/memo.py         memo items next to the inventory (market-based Scope 2, Cat 12, CH4/N2O)
src/demo.py         processing behind the demo page
src/score.py        exact leaderboard formula
app.py              Streamlit demo (UI only)
pitch/              build_pitch.py, pitch_numbers.md/.json, charts
analysis.py, report.py, scenarios.yaml   Inbox answers and the Excel report
mask_ledger.py      masks names in the raw ledgers (run locally, once)
stress_test.py      the stress test; tests/ holds 172 pytest tests
data/               demo files for the live run
outputs/            predictions, audit trail, summary, report
```

## Outputs

- **`outputs/predictions.csv`** — the submission: line_id, category, tco2e (683 test lines).
- **`outputs/audit.csv`** — one row per train + test line: category, ef_id, activity quantity and unit,
  method (activity / spend / excluded), tCO2e, rule_id, reason, confidence, review_flag. No names.
- **`pitch/bank_summary.pdf`** — one-page GHG inventory summary for the bank: totals by scope and category,
  activity vs spend share, hotspots, Pareto of suppliers and lines, intensity per tonne of product.
- **`outputs/summary.csv`** — totals by scope and category, activity vs spend share, tCO2e per tonne of
  product, calculation basis, and memo rows below the total.

## How a line is calculated

1. **Normalise**: lower-case text, unify units and number formats (`1 500,5`, `1,500.5`), net = gross − VAT.
2. **Duplicates**: same doc_no **and** counterparty, description, quantity and amount → later copy excluded.
3. **Rules** (`rules.yaml`, first match wins): GL excludes (taxes, advances, fines, per diem) → freight,
   travel, capital → refrigerants → energy → fuels → raw milk → packaging, ingredients, chemicals →
   water and waste → spend keywords.
4. **ML fallback** only for unseen spend lines; it can output a spend factor, never `EXCLUDE`, and flags
   the line `new item`.

Activity: `tCO2e = quantity × unit conversion × factor / 1000`. Spend: `tCO2e = net KZT / 1000 × factor / 1000`.
Special cases: raw milk by GL (descriptions are full of typos; l × 1.03); refrigerant refills = leaks,
including kg written in service acts ("дозаправка R404A 22.5 кг" → 88.7175 t); flights per leg with
round trips counted both ways; hired-carrier diesel in Scope 3 Cat 4; credit notes stay negative.

## Safeguards

- **No cloud, no LLM.** Everything runs on the laptop. The demo binds to `localhost` and sends no
  usage statistics (`.streamlit/config.toml`).
- **Masked data only.** The pipeline reads `ledger_*_masked.csv` (counterparties → `VENDOR_xxx`,
  employees → `EMP_xx`). Raw ledgers and `mask_mapping.csv` stay local and are git-ignored; a local test
  re-runs the masker and fails if any real name leaks.
- **Ledger text is data, never instructions.** Instruction-like text (English, Russian, Kazakh, HTML,
  JSON, "SYSTEM:", fake rule ids, auditor claims) is stripped and flagged. `EXCLUDE` can only come from
  the GL account or a duplicate, never from text, so no injection can zero a line.
- **No hand-labelling.** No `line_id` logic anywhere; a test checks that no rule keyword appears only in
  the test ledger.
- **No silent guesses.** Unreadable quantities, unknown units and inconsistent VAT are flagged; a physical
  item that can't be measured is held for review and `run.py` refuses to export until it is resolved.

## How to verify

```
python -m pytest            # 172 tests
python stress_test.py       # 107/107 checks
python run.py               # train score 1.0000
```

`predictions.csv` SHA-256: `4e3cc530e5ea08b2be473bf8d969a30cd464bfcb225bffe0dd36f9d51b34b15e`.
The stress test also copies the tracked files to a temp folder and checks a fresh run reproduces it.

## Reporting basis (GHG Protocol, Scope 2 / Scope 3 guidance, IFRS S2)

| Item | Basis |
|---|---|
| Organisation | Dala Foods LLP, **operational control** consolidation approach |
| Period / base year | Calendar year 2025 (posting dates 1 Jan – 31 Dec 2025); first inventory = base year |
| Fuels (Scope 1) | IPCC 2006 Tier 1 CO2 defaults, **CO2 only** (the factor file has no CH4/N2O; memo row ≈ 74 t, 0.04 %) |
| Fuel quantity | fuel **purchased** in 2025 treated as burned in 2025; stock changes are not in the ledger |
| Refrigerants | refill = leak; GWP-100 from **IPCC AR5** as given (IFRS S2 expects AR6 unless a relief applies) |
| Scope 2 | **location-based** 15,993 t; **market-based** also 15,993 t (memo row): no certificates, no supplier factor, no residual mix for Kazakhstan |
| Scope 3 included | Cat 1 goods & services, Cat 2 capital goods (full in year bought), Cat 4 transport (incl. outbound paid by Dala), Cat 5 waste & wastewater, Cat 6 business travel |
| Scope 3 not included | Cat 12 packaging end of life: indicative memo ≈ 3,214 t (1.6 %); Cat 3 well-to-tank / grid losses: not estimated (no factor in the case); Cats 7–11, 13–15: no data in a purchase ledger |
| Completeness | 12 monthly bills for each utility; district heat 7 (billed only Jan–Apr and Oct–Dec), so complete |
| Known overlap | diesel bought for a hired carrier and freight bought from the same carrier may cover the same trips (≈ 29 + 28 t); both counted, all 38 lines flagged |

## Answers to the Inbox (details in `pitch/pitch_numbers.md` and `outputs/carbon_report.xlsx`)

- **Bank (KZT 5 bn green loan):** solar saves 1,040 tCO2e per MWp per year. On the Kazakhstan grid
  (0.8 kg/kWh) heat pumps **raise** emissions below a seasonal **COP of 3.56**; at COP 3, moving 40 % of
  boiler heat adds 637 t. Finance heat pumps with solar, require COP ≥ 3.6, or use refrigeration heat
  recovery. High-temperature steam (pasteurisation, UHT) cannot fully move to heat pumps.
- **Retailer:** 1.901 kg CO2e per kg (1.958 per litre) is a plant average; a label per product needs
  output volumes and a fat/protein allocation of raw milk.
- **CFO:** about KZT 2.3 m a year (staff time), against a KZT 15 m budget; no licences or cloud.

## Known limitations

- Factors are used exactly as given (hard rule): CO2-only fuels, AR5 GWPs, one grid factor.
- Fuel purchases are treated as consumption; no stock changes.
- Typos in rare item words can still reach the ML fallback; they are flagged `possible typo` for review.
- Hired-carrier fuel and freight from the same carrier are both counted (flagged, not netted).
- 4 test lines are new services decided by the ML fallback with low confidence (flagged `new item`).
- `python run.py` stops if any physical line can't be measured; the demo app shows such lines as
  "Needs review" instead.

## Demo (3 minutes)

`streamlit run app.py` → **Live run**: upload `data/demo_bad_columns.csv` (clear message for the missing
column), then `data/demo_lines.csv` (10 invented 2026 lines): totals, colour-coded lines, the hidden
refrigerant (`N26004`: 15 kg × 3,943 / 1000 = 59.1450 t), the ignored instruction (`N26009`), the line
in review (`N26010`, sugar in bags), downloads. → **Pitch**: computed numbers, charts, green-loan sliders.
