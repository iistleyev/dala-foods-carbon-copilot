# Dala Foods — Carbon Copilot (Case 2)

Turns the 2025 purchase ledger into a Scope 1/2/3 GHG inventory with a per-line audit trail.
Rules + local ML only; no ledger data leaves the laptop.

Inputs: `ledger_train_masked.csv` and `ledger_test_masked.csv` (counterparties → `VENDOR_xxx`,
employee names → `EMP_xx`, one-to-one). The file names are set at the top of `src/load.py`.

## Run

```
pip install -r requirements.txt
python run.py        # ~3 s: prints train score, worst lines, confusion matrix; writes outputs/
python -m pytest     # robustness tests
```

Current train result: **macro-F1 1.0000, WAPE 0.0000, score 1.0000** (0 train lines reach the ML fallback).

## How a line is classified (first match wins)

1. **Normalise** (`src/load.py`): lower-case text, unify quotes/dashes, map unit spellings to one code,
   `net = gross − VAT`. Sentences addressed to an AI ("ignore previous instructions", HTML comments,
   `[SYSTEM NOTE…]`, "ИИ-ассистенту…") are **stripped before classification** and the line is flagged
   `instruction-like text ignored`. Ledger text is data, never instructions.
2. **Duplicates** (`src/duplicates.py`, train + test together): same doc_no **and** counterparty,
   description, quantity and gross amount → later line_id is `EXCLUDE`, 0. doc_no alone is not enough.
3. **Rules** (`rules.yaml`, engine in `src/rules.py`), in this order:
   GL excludes (taxes, social contributions, advances, fines, per diem) → GL-routed (freight 7110,
   travel 7212, capital 2410–2412) → refrigerants → energy → fuels → raw milk (GL 1310) →
   packaging/ingredients/chemicals → water and waste → spend keywords.
4. **ML fallback** (`src/fallback.py`): TF-IDF char 2–4-grams of description + GL → logistic regression
   over the spend factors seen in train. It can only output a spend factor (never `EXCLUDE`) and every
   such line is flagged `new item` (plus `low confidence` if probability < 0.5).

All arithmetic is in code from `emission_factors.csv`:
activity `tCO2e = quantity × unit multiplier × factor / 1000`; spend `tCO2e = net KZT / 1000 × factor / 1000`.

## Special cases

| Case | Handling |
|---|---|
| Raw milk (~80 % of emissions) | GL 1310 decides (descriptions are full of typos); кг ×1, л ×1.03, т ×1000 |
| Milk prepayment | GL 1610 → excluded before the milk rule |
| Rail "сухого молока" | GL 7110 is routed before milk; tonnes × km parsed from text |
| Flights | IATA legs, haversine R = 6371 km; factor per leg: both KZ → domestic, < 3700 km → short, else long; × tickets |
| Hidden refrigerant | GL 8111 service line with "дозаправка R404A 11.1 кг" → kg parsed from text × GWP |
| Diesel for hired carrier | Scope 3 Cat. 4, not Scope 1 |
| Credit notes | negative quantity kept → negative tCO2e (never `abs()`) |
| PET preforms in шт | pieces × grams in the item name / 1000 |

## Safeguards for unseen data

- **No silent failures.** An unreadable or missing quantity stays empty (never 0) and gets
  `review_flag = quantity unreadable`. If a milk/fuel/energy/packaging/chemicals/waste rule matches but
  can't convert the line's unit, the line falls through as before and, if it ends up spend-based, gets
  `activity item computed by spend: unit not covered`. `run.py` prints a count for both flags.
- **Number parsing** accepts thousand separators ("1 500 кг", including no-break spaces) and Latin units (kg, km, g).
- **Piece weights** (unit шт): `packaging_specs.csv` by item name → grams written in the name → the
  rules.yaml default. The audit reason says which source was used.
- **Mixed flights**: if legs use different factors (e.g. NQZ-ALA domestic + ALA-FRA long-haul), ef_id is
  `EF_FLIGHT_DOM_PKM+EF_FLIGHT_LONG_PKM` and the reason lists km per leg.

## Outputs

- `outputs/predictions.csv` — line_id, category, tco2e (683 test rows, 4 decimals)
- `outputs/audit.csv` — every train + test line: category, ef_id, activity_qty/unit, method, tco2e,
  rule_id, reason, confidence, review_flag (no counterparty names)
- `outputs/summary.csv` — totals by scope and category, activity vs spend share

## Test lines needing human review

4 test lines are new services not seen in train (certification, special-equipment rental, analytics
subscription, marketing consulting). They go to the ML fallback as S3_C1_GOODS spend and are flagged.
Each also contained planted AI instructions, which were ignored.

## Changing a rule

Edit `rules.yaml` (each rule has keywords, GL, units, factor, conversion and a reason), re-run
`python run.py`, and keep the change only if the train score does not drop.
