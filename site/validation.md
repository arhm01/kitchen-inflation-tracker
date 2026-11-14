# Validation report

_Generated 2026-11-14 13:06 UTC by the pipeline. Checks are defined in `src/kitchen_inflation/validate.py`; cleaning rules in `clean.py`; both are explained in `docs/methods.md`._

## Coverage

- Weeks with city prices: **164** (2023-02-16 to 2026-11-12)
- Weeks with quintile data: **163**
- Price rows: **142,188**; NULL (reported as 0.00): 582
- Parse method: mcid: 142,188
- Source files discovered: 485, selected: 388

## Issues by check

| check | error | warn | info |
|---|---:|---:|---:|
| V10_decomposition | 0 | 0 | 1 |
| V11_index_revision | 0 | 0 | 1 |
| V4_city_outlier | 0 | 5 | 0 |
| V6_big_jump | 0 | 0 | 2 |
| V6_possible_unit_change | 0 | 2 | 0 |
| V7_missing_weeks | 0 | 8 | 0 |
| V9_pdf_vs_xlsx | 0 | 0 | 61 |
| filename_date_mismatch | 0 | 0 | 1 |
| summary_link | 0 | 0 | 1 |
| zero_as_missing | 0 | 0 | 1 |

## Details

### V10_decomposition (1)

- **info** `all weeks`: 100% of week-baskets close within 0.15pp; median |gap| 0.003pp

### V11_index_revision (1)

- **info** `2025-11-27 Q1`: previous-week index revised by +2.04 points vs the 2025-11-20 report

### V4_city_outlier (5)

- **warn** `2025-04-24 Larkana Tomatoes`: 11.45 vs median 60.00 (0.19x)
- **warn** `2025-04-30 Larkana Tomatoes`: 13.1 vs median 56.46 (0.23x)
- **warn** `2025-05-08 Larkana Tomatoes`: 16.51 vs median 50.00 (0.33x)
- **warn** `2025-05-15 Larkana Tomatoes`: 13.1 vs median 50.00 (0.26x)
- **warn** `2025-05-22 Larkana Tomatoes`: 16.51 vs median 50.00 (0.33x)

### V6_big_jump (2)

- **info** `2025-10-30 #22 Onions`: national median 112.63 -> 186.43 (+66%) in one week (perishable)
- **info** `2025-11-20 #23 Tomatoes`: national median 120.00 -> 200.00 (+67%) in one week (perishable)

### V6_possible_unit_change (2)

- **warn** `2023-07-26 #27 Chilli powder`: national median 215.00 -> 400.00 (+86%) in one week, description unchanged
- **warn** `2023-11-16 #42 Gas (Q1)`: national median 295.00 -> 1711.00 (+480%) in one week, description unchanged

### V7_missing_weeks (8)

- **warn** `2023-02-16 -> 2023-07-06`: 19 week(s) with no annex found
- **warn** `2024-02-01 -> 2024-02-15`: 1 week(s) with no annex found
- **warn** `2024-04-04 -> 2024-04-18`: 1 week(s) with no annex found
- **warn** `2024-06-27 -> 2024-07-11`: 1 week(s) with no annex found
- **warn** `2024-09-12 -> 2024-11-07`: 7 week(s) with no annex found
- **warn** `2025-06-12 -> 2025-06-26`: 1 week(s) with no annex found
- **warn** `2026-05-21 -> 2026-06-04`: 1 week(s) with no annex found
- **warn** `2026-06-18 -> 2026-07-02`: 1 week(s) with no annex found

### V9_pdf_vs_xlsx (61)

- **info** `2025-04-30`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-05-15`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-07-17`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-07-24`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-07-31`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-10-09`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-10-16`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-10-23`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-10-30`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-11-06`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-11-13`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-11-20`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-11-27`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-12-04`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-12-11`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-12-18`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2025-12-24`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-01-01`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-01-08`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-01-15`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-01-22`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-01-29`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-02-04`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-02-12`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-02-19`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-02-26`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-03-05`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-03-11`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-03-18`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-03-26`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-04-02`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-04-09`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-04-16`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-04-23`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-04-30`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-05-07`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-05-14`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-05-21`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-06-04`: 0 of 2601 cells differ, 0 unmatched keys
- **info** `2026-06-11`: 0 of 2601 cells differ, 0 unmatched keys
- ... 21 more in `data/clean/issues.csv`

### filename_date_mismatch (1)

- **info** `Executive-Summary-SPI-Report_20.02.2026.pdf`: name says 2026-02-20, content says 2026-02-19

### summary_link (1)

- **info** `summary_items`: 8254 rows linked by price, 59 by name (C4)

### zero_as_missing (1)

- **info** `prices`: 582 city-item-weeks reported as 0.00 -> NULL (C1)
