# Kitchen Inflation Tracker

An automated pipeline that reads Pakistan's weekly **Sensitive Price Indicator** (SPI) PDFs from the Pakistan Bureau of Statistics. It extracts city-level prices for 51 essentials in 17 cities, validates them, loads them into DuckDB and publishes a dashboard every week via GitHub Actions.

Most of the work is parsing. PDF layouts and file names change over the years, so every cleaning decision is written down in **[docs/methods.md](docs/methods.md)**.

## Results at a glance

Archive: **163 weeks** of city prices (Jul 2023 – 5 Nov 2026, plus one surviving week from Feb 2023) and 162 weeks of quintile data. 141,321 price rows from 385 PDF/XLSX files.

| Question | Answer from the data |
|---|---|
| **1. Which city pays most for the same basket? Is it stable?** | **Islamabad**: its kitchen basket is 11.3% above the 17-city average, and it was the dearest city in 93% of weeks. Rawalpindi (+8.2%), Karachi (+7.0%) and Peshawar follow; that top four holds under an unweighted index too. **Sargodha** (−9.1%), Bannu and Bahawalpur are cheapest on the weighted index; mid-table order depends on weighting ([methods](docs/methods.md#q1-which-city-pays-most-for-the-same-basket)). The ranking barely moves over time: the dearest–cheapest spread is about 12× a typical city's weekly standard deviation. Islamabad's premium comes from fresh produce (bananas +62%, potatoes +33%, tomatoes +31%), not packaged goods. |
| **2. Do poorer households face different inflation?** | Yes, and the sign flips. Q1 (poorest) YoY minus Q5 (richest) averaged **−1.7 pp**; it was positive in only 27% of weeks and ranged from −6.7 to +4.0 pp. Latest week: **10.15% vs 12.75%**. The exact decomposition shows petrol, Q1 electricity and gas pulling the poorest quintile's rate *below* the average, and firewood, onions and wheat flour pushing it above. |
| **3. Ramadan effect by item, across years?** | **Bananas** are the one large, consistent effect: +41, +46 and +49 pp above their typical 4-week change in Ramadan 2024, 2025 and 2026. Beef and mutton rise a small (1–3 pp) but consistent amount. Potatoes went +19 / −11 / −24 pp, so for seasonal produce Ramadan can't yet be separated from season (every Ramadan so far fell in spring). 11 of 29 kitchen items never moved beyond their normal swing. |
| **Is the parse right?** | For the 60 weeks where PBS also published Excel, the PDF parse matches it on **156,060 of 156,060 cells**. Item contributions reproduce PBS's published YoY within 0.01 pp in all 136 decomposed week-baskets. |

## Pipeline

```
discover ─▶ download ─▶ parse ─▶ consolidate ─▶ clean + validate ─▶ DuckDB ─▶ dashboard
(WP index,   (cached in   (pdfplumber,  (one file per   (rules C1–C5,      (views per   (static HTML,
 posts,      data/raw)    mcid cells)   week, by date   checks V1–V11)     question)    GitHub Pages)
 media API)                             inside file)
```

| Stage | Code | Output |
|---|---|---|
| Find report links without guessing URLs | `src/kitchen_inflation/discover.py` | `data/interim/catalog.csv` |
| Extract city price tables (Appendix-A) | `parse_annex.py` | per-file cache in `data/interim/parsed/` |
| Extract quintile + item-weight tables | `parse_summary.py` | ″ |
| Reference parse of PBS's XLSX | `parse_xlsx.py` | used by check V9 |
| Cleaning rules | `clean.py` | `data/clean/*.csv` (committed) |
| Validation checks | `validate.py` | `data/clean/issues.csv`, `reports/validation.md` |
| Load + analysis views | `load.py`, `sql/views.sql` | `data/spi.duckdb` (rebuilt each run) |
| Dashboard | `dashboard.py`, `templates/index.html` | `site/` |
| Weekly schedule | `.github/workflows/weekly.yml` | commit + Pages deploy |

## Running it

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m kitchen_inflation run --full-scan   # first run: lists the whole media library
uv run python -m kitchen_inflation run               # weekly incremental run
uv run python -m kitchen_inflation run --offline     # rebuild from data/raw without network
uv run pytest                                        # 30 tests, incl. PDF-vs-Excel on real files
python -m http.server -d site 8765                   # view the dashboard
```

On a slow connection, `uv run python scripts/backfill.py` downloads the archive first (3 polite workers, summaries first) and can be resumed.

The run exits non-zero if any validation **error** fires, so GitHub Actions publishes nothing that failed the hard checks.

## Querying the data

```bash
uv run python -c "import duckdb; print(duckdb.connect('data/spi.duckdb').sql('select * from city_stability'))"
```

Views: `city_index`, `city_rank`, `city_stability`, `city_item_premium`, `quintile_yoy`, `gap_contrib`, `item_national`, `typical_window_change`, `ramadan_effect`. Tables: `prices`, `items`, `quintiles`, `summary_items`, `yoy_contrib`, `national`, `issues`, `source_files`, `xlsx_check`.

## Publishing (one-time setup)

1. Push to GitHub.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions → *weekly-spi* → *Run workflow* (tick *full scan* the first time).

After that it runs every Saturday 06:00 UTC (PBS posts on Friday afternoons), with a Monday catch-up run for late uploads and corrections.

## Data notice

All data is published by the Pakistan Bureau of Statistics. This is an independent analysis; PBS is not responsible for it. Raw PDFs are not committed (they are re-downloadable and cached in CI). Three small public PBS files are included in `tests/fixtures/` as parser test cases.
