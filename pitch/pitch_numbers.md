# Pitch numbers (computed by pitch/build_pitch.py from outputs/audit.csv)

## Inventory 2025 (train + test)
- Total: **199,638.2 tCO2e**; test lines only: 67,029.1 tCO2e
- By scope: S1 14,088.1 t (7.1%), S2 15,992.8 t (8.0%), S3 169,557.4 t (84.9%)
- Activity-based 99.5% / spend-based 0.5%
- Lines: 1,952; flagged for review: 58

| Category | tCO2e |
|---|---|
| S3_C1_GOODS | 168,213.6 |
| S2_ELECTRICITY | 14,495.7 |
| S1_STATIONARY | 8,530.3 |
| S1_MOBILE | 4,155.4 |
| S2_HEAT | 1,497.0 |
| S1_FUGITIVE | 1,402.3 |
| S3_C2_CAPITAL | 776.9 |
| S3_C5_WASTE | 345.0 |
| S3_C4_TRANSPORT | 173.6 |
| S3_C6_TRAVEL | 48.3 |

## Footprint per product
- **1.901 kg CO2e per kg**, 1.958 kg CO2e per litre — average across all products (105,000 t); per litre at 1.03 kg/l

## Carbon per tenge
- Energy (electricity, gas, heat): **2.2% of spend, 12.3% of emissions**

| Group | Net spend, m KZT | Share of spend | tCO2e | Share of tCO2e | tCO2e per m KZT |
|---|---|---|---|---|---|
| raw milk | 27,833.0 | 75.0% | 157,499.3 | 78.9% | 5.66 |
| electricity | 581.1 | 1.6% | 14,495.7 | 7.3% | 24.95 |
| natural gas | 201.0 | 0.5% | 8,530.3 | 4.3% | 42.44 |
| district heat | 47.4 | 0.1% | 1,497.0 | 0.7% | 31.58 |
| refrigerants | 5.1 | 0.0% | 1,402.3 | 0.7% | 276.16 |
| own-fleet fuel | 452.4 | 1.2% | 4,155.4 | 2.1% | 9.19 |
| packaging | 5,672.4 | 15.3% | 9,540.3 | 4.8% | 1.68 |
| capital goods | 644.0 | 1.7% | 776.9 | 0.4% | 1.21 |
| services | 611.4 | 1.6% | 179.3 | 0.1% | 0.29 |
| other | 1,075.1 | 2.9% | 1,561.7 | 0.8% | 1.45 |

## Hotspots (top 5)
- raw milk: 78.9%
- electricity: 7.3%
- packaging: 4.8%
- natural gas: 4.3%
- own-fleet fuel: 2.1%

## Green loan
- Natural gas: 4,466,141 m3 = 8,530.3 tCO2e; grid electricity: 18,120 MWh = 14,495.7 tCO2e
- **Break-even COP 3.56** (gas 34.0 MJ/m3, boiler 90%, grid 0.8 kg/kWh, gas 1.91 kg/m3)
- If 40% of boiler heat moves to heat pumps:

| COP | Change tCO2e/yr | vs Scope 1+2 |
|---|---|---|
| 2.5 | +1,447 | +4.8% |
| 3.0 | +637 | +2.1% |
| 3.5 | +59 | +0.2% |
| 4.0 | -375 | -1.2% |
| 5.0 | -983 | -3.3% |

- Solar: **1,040 tCO2e saved per MWp** per year (1,300 kWh/kWp)
- High-temperature steam (pasteurisation, UHT) cannot fully move to heat pumps; the best use is low-temperature heat (CIP, hot water, pre-heating) and heat recovery from refrigeration.

## Last year's mistakes caught
- Refrigerant refills = leaks: 13 lines, **1,402.3 tCO2e**; 4 of them hidden in service acts (unit усл): 244.1 tCO2e
- L00131: refill hidden in a service act — 22.5 kg x 3943 / 1000 = 88.7175 tCO2e
- Flights: 80 tickets, 49 round trips counted with both legs (+17.44 tCO2e that one-way counting would miss)

## Robustness
- Injection lines in the test set: 4, ignored: 4
- Stress test: 107/107 checks pass

Charts: chart_scopes.png, chart_spend_vs_emissions.png, chart_hotspots.png, chart_heat_pumps.png
