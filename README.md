# Dala Foods — Carbon Copilot (Case 2)

Turns the 2025 purchase ledger into a Scope 1/2/3 GHG inventory with a per-line audit trail.
Rules + local ML only; no ledger data leaves the laptop.

Inputs: `ledger_train_masked.csv` and `ledger_test_masked.csv` (counterparties → `VENDOR_xxx`,
employee names → `EMP_xx`, one-to-one). The file names are set at the top of `src/load.py`.

## Run

Python 3.12 or newer.

```
pip install -r requirements.txt
python run.py        # ~3 s: prints train score, worst lines, confusion matrix; writes outputs/
python analysis.py   # answers for the bank, the retailer and the CFO (reads outputs/audit.csv)
python report.py     # everything in one spreadsheet: outputs/carbon_report.xlsx
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
| PET preforms in шт | pieces × verified kg per piece |

## Safeguards for unseen data

- Unknown physical quantities, units, package weights and incomplete flight routes produce
  a review row. Invalid gross amounts or VAT also block spend calculations. A blocked run
  writes `outputs/audit.review.csv` and exits before replacing the last completed inventory.
- Numbers accept space-grouped thousands and comma decimals. A quantity with a written unit
  can supply a missing unit or confirm the unit column.
- Piece weights come from the official specification or explicit grams in the item description.
  A weight-free SKU must identify a unique reference entry.
- Every flight audit reason lists each leg, ticket count, distance, factor, rate and tonnes.
  On mixed itineraries the main factor ID identifies the largest absolute contribution.
  Separately labelled tickets are counted individually. Conflicting ticket counts require review.
- For a new year, run `python mask_ledger.py` locally on the raw train and test CSVs first.
  It checks both splits before writing masked files. Keep `mask_mapping.csv` and the raw files private.

## Reporting basis (GHG Protocol, Scope 2 / Scope 3 guidance, IFRS S2)

| Item | Basis |
|---|---|
| Organisation | Dala Foods LLP, **operational control** consolidation approach |
| Reporting period | Calendar year 2025 (posting dates 1 Jan – 31 Dec 2025) |
| Base year | 2025 — first inventory; no recalculation policy needed yet |
| Gases | Reported as total tCO2e only; the case factor file does not split gases |
| Fuels (Scope 1) | IPCC 2006 Tier 1 CO2 defaults (diesel 74,100, petrol 69,300, LPG 63,100, natural gas 56,100 kg/TJ, Vol. 2 Ch. 2–3). **CO2 only**: CH4/N2O are not in the factor file. Memo row: ≈ 74 tCO2e (0.04 % of the total) with IPCC Tables 3.2.2 / 2.3 and GWP AR5 — below materiality, so not added |
| Fuel quantity | Fuel **purchased** in 2025 is treated as fuel burned in 2025 (incl. 2 deliveries into the own storage tank); stock changes are not in the ledger |
| Refrigerants | Refill = leak (mass-balance simplification); GWP-100 from **IPCC AR5** as given in the factor file. IFRS S2 expects the latest IPCC report (AR6) unless a relief applies |
| Scope 2 | **Location-based**: 15,993 tCO2e (Kazakhstan grid average; Almaty district heating). **Market-based**: also 15,993 tCO2e (memo row) — Dala has no energy attribute certificates or supplier-specific factors and no residual mix is published for Kazakhstan, so the Scope 2 Guidance falls back to the grid average |
| Scope 3 included | Cat 1 goods & services (incl. mains water), Cat 2 capital goods (full emissions in the year bought, not depreciated), Cat 4 upstream transport (incl. outbound freight paid by Dala), Cat 5 waste & wastewater, Cat 6 business travel (flights by distance, hotels, taxi; per diem excluded as cash) |
| Scope 3 not included | **Cat 12** end of life of sold packaging: **indicative memo ≈ 3,214 tCO2e (1.6 %)** = 5,542 t packaging bought (taken as sold) × the case landfill factor; not added because Cat 12 is outside the case's 11 categories. **Cat 3** fuel- and energy-related activities: relevant but **not estimated** — no well-to-tank or grid-loss factor in the case, and outside factors are not allowed. Cat 7 commuting (no data). Cats 8–11, 13–15 not applicable or no data in a purchase ledger |
| Known overlap | Diesel bought for a hired carrier (fuel-based) and freight bought from the same carrier (distance/spend-based) may cover the same trips: 15 + 23 lines, ≈ 29 + 28 tCO2e. Both are counted because the ledger can't show which trips overlap; all 38 lines carry a `possible Cat 4 double count` flag |
| Excluded lines | Taxes, social contributions, advances, fines, per diem, duplicates: `method = excluded` with a reason in `audit.csv` |
| Completeness | 12 monthly bills each for electricity (plant and office), natural gas, water, wastewater and waste. District heat has 7 bills because it is billed only in the heating season (Jan–Apr, Oct–Dec), so it is complete |
| Data quality | Share of activity- vs spend-based tCO2e per category in `summary.csv`; per-line method, rule and confidence in `audit.csv` |

## Outputs

- `outputs/predictions.csv` — line_id, category, tco2e (683 test rows, 4 decimals)
- `outputs/audit.csv` — every train + test line: category, ef_id, activity_qty/unit, method, tco2e,
  rule_id, reason, confidence, review_flag (no counterparty names)
- `outputs/summary.csv` — totals by scope and category, activity vs spend share, tCO2e per tonne of
  product (105,000 t), calculation basis
- `outputs/loan_scenarios.csv`, `outputs/product_footprint.csv`, `outputs/cost_model.csv` — from `analysis.py`
- `outputs/carbon_report.xlsx` — from `report.py`: Summary, Audit (every line with its factor and a
  recomputation), Review queue, Loan scenarios, Product footprint, Cost model, Injection lines, Factors.
  Totals and scenarios are Excel formulas: change a yellow assumption cell and the sheet recalculates.
  Values appear when the file is opened in Excel (openpyxl does not store computed values).

## Answers to the Inbox

Built by `analysis.py` from `outputs/audit.csv`, `emission_factors.csv` and `scenarios.yaml`.
Whole-year inventory (train + test): **199,638.2 tCO2e**.

**Bank — green loan (KZT 5 bn), Scope 1+2 location-based**

| Scenario | Scope 1 t | Scope 2 t | Change t/yr | vs Scope 1+2 |
|---|---|---|---|---|
| Baseline 2025 | 14,088 | 15,993 | — | — |
| Solar only (3,000 kWp) | 14,088 | 12,753 | −3,240 | −10.8 % |
| Heat pumps only, COP 3.0 | 10,676 | 20,042 | **+637** | **+2.1 %** |
| Solar + heat pumps, COP 2.5 | 10,676 | 17,612 | −1,793 | −6.0 % |
| Solar + heat pumps, COP 3.0 | 10,676 | 16,802 | −2,603 | −8.7 % |
| Solar + heat pumps, COP 4.0 | 10,676 | 15,790 | −3,615 | −12.0 % |

- Solar always cuts emissions (4.05 GWh × 0.8 kg/kWh).
- On the Kazakhstan grid (0.8 kg/kWh, mostly coal) heat pumps **raise** emissions unless the seasonal
  COP is above **3.56** (break-even = 34 MJ/m³ ÷ 3.6 × 0.9 boiler efficiency × 0.8 ÷ 1.91).
- Recommendation: finance heat pumps together with solar, make COP ≥ 3.6 a loan condition, or use
  heat recovery from the refrigeration plant.
- The loan reaches only ~12 % of the inventory (electricity, gas, heat); 79 % is raw milk from farms.
- Estimated capex for these assumptions: KZT 2.04 bn.

**Retailer (EuroMart) — product footprint, cradle-to-gate**

| Stage | kg CO2e per kg | Share |
|---|---|---|
| Raw milk | 1.500 | 79.2 % |
| Electricity | 0.138 | 7.3 % |
| Packaging | 0.091 | 4.8 % |
| Natural gas | 0.081 | 4.3 % |
| Own fleet fuel | 0.040 | 2.1 % |
| Other (heat, refrigerants, ingredients, water/waste, services, transport, chemicals) | 0.043 | 2.3 % |
| **Total** | **1.893 per kg = 1.950 per litre** | 100 % |

- This is a **plant average** over 105,000 t of product. Capital goods and business travel are left out.
- Company transport is included: the ledger does not say whether a trip is milk collection or delivery.
- Per-litre figures use the density of milk (1.03 kg/l) for every product.
- A label per product (milk, kefir, yoghurt, cream) needs output volumes per product and an allocation
  of raw milk by fat and protein (IDF method). These data are not in the ledger; that is the next step.

**CFO — annual running cost vs KZT 15 m budget**

| Item | Days | KZT / year |
|---|---|---|
| Annual run and review of flagged lines (accountant) | 10 | 450,000 |
| Rule and factor-library update (analyst / developer) | 15 | 900,000 |
| Internal second check before external assurance | 5 | 300,000 |
| Training and handover when staff change | 5 | 300,000 |
| Hardware, cloud, licences (existing laptop, open-source Python) | — | 0 |
| Contingency 20 % | | 390,000 |
| **Total** | | **2,340,000** (16 % of budget) |

The tool runs locally without cloud services or licences; the cost is people's time.

**Inputs: data pack vs our assumptions** (`scenarios.yaml`)

| Input | Value | Source |
|---|---|---|
| Green loan | KZT 5 bn | Data pack (brief / Inbox) |
| Finished product | 105,000 t | Data pack (brief) |
| Gas heating value | 34 MJ/m³ | Data pack (`emission_factors.csv` note) |
| Milk density | 1.03 kg/l | Data pack (`emission_factors.csv` note) |
| CFO budget | KZT 15 m | Data pack (brief / Inbox) |
| Solar capacity | 3,000 kWp | **Assumption** (~18,000 m² roof) |
| Solar yield | 1,350 kWh/kWp/yr | **Assumption** (Almaty region) |
| Solar capex | KZT 300,000 / kWp | **Assumption** |
| Share of boiler heat for heat pumps | 40 % | **Assumption** (low-temperature heat; steam stays on gas) |
| Heat-pump seasonal COP | 3.0 (range 2.5–4.5) | **Assumption** |
| Boiler efficiency | 90 % | **Assumption** |
| Heat-pump full-load hours / capex | 6,000 h / KZT 450,000 per kWth | **Assumption** |
| Staff days and day rates | see CFO table | **Assumption** (replace with Dala Foods' rates) |

## Test lines needing human review

4 test lines are new services not seen in train (certification, special-equipment rental, analytics
subscription, marketing consulting). They go to the ML fallback as S3_C1_GOODS spend and are flagged.
Each also contained planted AI instructions, which were ignored.

## Changing a rule

Edit `rules.yaml` (each rule has keywords, GL, units, factor, conversion and a reason), re-run
`python run.py`, and keep the change only if the train score does not drop.
