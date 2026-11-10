# Methods note

How the Kitchen Inflation Tracker turns PBS's weekly SPI PDFs into the numbers on the dashboard, and every decision made along the way. Rule IDs (D*, P*, C*, V*) match comments in the code.

## 1. Source

The Pakistan Bureau of Statistics publishes the **Sensitive Price Indicator (SPI)** every week: 51 essential items, 50 markets, 17 cities, base 2015-16 = 100. Prices are collected once a week, normally on Thursday. Each week has two files:

| File | What we use |
|---|---|
| **Annex** (Appendix-A), PDF; since late 2025 also XLSX | Minimum, average and maximum price of each item in each city |
| **Executive summary**, PDF | SPI index for each consumption quintile (Q1 poorest to Q5 richest) and combined; each item's national price, its weight in the lowest-quintile and combined baskets, and its impact in % points |

## 2. Finding the files (`discover.py`)

- **D1. No guessed URLs.** File names are hand-typed and change style every few months: `SPI_AnnexUSCP_06072023.pdf`, `ANNEX202620USCP2002.05.2024.pdf`, `Annex-12-06-2025.pdf`, `Annex_05.11.pdf` (no year), `Annex.pdf` (no date). Building URLs from dates would silently miss weeks.
- **D2. Three link sources, merged.** (a) The human index pages (`/price-statistics/`, home page), which only show the latest week but list it first. (b) The weekly SPI posts, via the WordPress REST API. (c) The WordPress **media library**, via the REST API. After the 2023/24 site migration, (c) is the only place the back catalogue is still listed. The first run scans the whole library (about 6,000 files, 61 requests); weekly runs search it for "SPI" and "Annex". The catalog is append-only, so a file seen once is never forgotten.
- **D3. The file name only hints at the date.** Seven filename date patterns are parsed (see `tests/test_discover.py`). One example: a URL-encoded space left behind as a literal "20" (`USCP2002.05.2024` is `USCP 02.05.2024`). **The week used is always the date printed inside the file** ("PRICES ON 05-11-2026" / "WEEK ENDED ON 05.11.2026"). The filename date is used only when the file has none, and a mismatch is logged (one case: a summary named 20.02.2026 is for 19.02.2026).
- **D4. Content decides what a file is.** A file named like an annex but containing no SPI table (`Annexures-.pdf` is a 127-page trade report) is marked `not_spi`.
- **D5. Duplicates.** Re-uploads (`-1`, `_0` suffixes) are collapsed when their parsed values are identical. If they differ, the latest upload wins (PBS corrects by re-uploading) and the conflict is logged.

## 3. Parsing the PDFs (`parse_annex.py`, `parse_summary.py`)

The PDFs are text-based, not scans, so no OCR is needed. The difficulty is the table geometry.

- **P1. Numbers are placed by x-position.** Each number goes to the column whose `MIN`/`AVG`/`MAX` header is nearest. A blank cell can't shift every following value one city to the left, as it would if values were read in order. Page size and offsets differ between years (792×612 in 2023, 842×595 in 2026); positions are measured from each page's own header.
- **P2. Rows are anchored on the trailing serial-number column**, which is never glued to other text (the leading one is: `1Wheat Flour`). Rows above the "PRICES ON" banner (the column-number row `1 2 3 … 24 1`) are skipped.
- **P3. Description and unit cells overlap on the page.** Plain text extraction interleaves them: `Rice Basmati Broken (Average Qualit1y )Kg`. The PDFs are tagged, though, and every table cell is its own marked-content sequence (`mcid`). Cells are rebuilt from the mcids, giving `Rice Basmati Broken (Average Quality)` / `1 Kg`. This also recovers descriptions that overflow into the first city's columns (`Cooking Oil … (SN), 5 Litre Tin`). Untagged pages would fall back to an x-split plus a unit regex, marked `method = xsplit`. So far every page in the archive is tagged.
- **P4. Pages without Appendix-A are skipped**: Appendix-B fertiliser prices and, in 2023-24, a Utility Stores comparison page.
- **P5. Summary tables.** The quintile table is matched line by line. The item table is rebuilt from mcid cells (rank, name, unit, then exactly 9 numbers).

**How we know the parser is right.** For the **60 weeks** where PBS also published the annex as XLSX, the PDF parse is compared with it cell by cell (check V9): **156,060 cells, 0 differences**. `tests/test_parsers.py` repeats this on committed fixtures.

## 4. Cleaning (`clean.py`)

- **C1. A zero price means "not collected in this city".** For example, IRRI rice in Gujranwala and Sialkot. Zeros become NULL, never 0 (579 of 141,321 city-item-weeks).
- **C2. An item's identity is its SPI serial number (1–51)**, which is fixed for the 2015-16 basket. Descriptions are kept as published each week.
- **C3. Specifications are versioned.** Description and unit are normalised (case, punctuation, the truncated `Per Minut`). A new version starts when the normalised text changes; V5 then tests whether the price jumped at the same moment (a real unit change).
- **C3a. Label aliases.** PBS alternates week to week between "Gas Charges upto 3.3719 MMBTU" and "Gas Charges for Q1" at an unchanged price, so they are treated as the same specification.
- **C4. Linking summary rows to items.** Each summary row is matched to an item number by its price, which equals the annex national average to the paisa. If that fails, a fuzzy name match is used (8,203 rows linked by price, 59 by name).
- **C5. Nothing is imputed.** A city-item-week with no price is left out of that week's comparison (see Q1).

## 5. Validation (`validate.py`, report in `reports/validation.md`)

Severity: **error** stops the weekly publish, **warn** is published but listed for a human, **info** records a decision.

| Check | What it tests | Severity |
|---|---|---|
| V1 | Every week has 51 items × 17 cities | error |
| V2 | 6 quintile rows; basket weights sum to 100; item impacts sum to the published week-on-week change | error / warn |
| V3 | No negative prices; min ≤ avg ≤ max | error / warn |
| V4 | A city's price is more than 3× or less than ⅓ of the 17-city median (unit mix-ups, decimal slips) | warn |
| V5 | Specification text changed; warn if the price also jumped more than 25% | info / warn |
| V6 | Week-on-week jump over 60% with the description unchanged: info for perishables, warn ("possible unit change") otherwise | info / warn |
| V7 | Weeks end on Wednesday or Thursday; missing weeks listed | warn |
| V8 | Summary price equals annex national average | warn |
| V9 | PDF parse equals PBS's XLSX | error if over 0.1% of cells differ |
| V10 | Item YoY contributions plus gaps plus revisions equal PBS's published YoY | warn if off by more than 0.15 pp |
| V11 | A report's "previous week" index differs from what the previous report published (a PBS revision) | info |

**What the checks found in the current archive:**
- **Larkana tomatoes, Apr–May 2025 (V4).** Rs 11–16 while the 17-city median was Rs 50–60, about ¼ of the median five weeks running. This is consistent with a price per pao (250 g) entered as a price per kg. It is left as published and flagged.
- **Chilli powder, 26 Jul 2023 (V6).** Rs 215 to Rs 400 overnight with the description still "200 gm Packet". This could be a price hike or an unannounced pack change; we can't tell, so it is flagged.
- **Gas (Q1), 16 Nov 2023 (V6).** Rs 295 to Rs 1,711 per MMBTU, consistent with the November 2023 gas tariff revision for protected consumers.
- **Q1 index revised, 27 Nov 2025 (V11).** The 27 Nov report restates the 20 Nov Q1 index 2.04 points higher than the 20 Nov report did (combined unchanged).
- **Missing weeks (V7).** 32 weeks between 16 Feb 2023 and 5 Nov 2026 have no annex anywhere on the site, including a 7-week hole in Sep–Nov 2024 (the media library for those dates holds census tables only). The archive effectively starts on 6 Jul 2023; 16 Feb 2023 is a lone surviving week.

## 6. The three questions (`sql/views.sql`)

### Q1. Which city pays most for the same basket?
- **Basket:** the 29 grocery items (SPI 1–29), restricted each week to items priced in **all 17 cities**. Every city is compared on exactly the same items.
- **Index:** each city's price divided by the 17-city mean for that item, averaged with the combined SPI weights; 100 = average.
- **Robustness:** an unweighted geometric version is also computed (`idx_geometric`). The **top four are identical** (Islamabad, Rawalpindi, Karachi, Peshawar), but the middle and bottom reorder (Spearman 0.79 between the two rankings): Larkana is 5th weighted and 13th unweighted, and Bannu rather than Sargodha is cheapest unweighted. The unweighted version gives garlic as much say as wheat flour and milk, so we headline the weighted one, which reflects what households spend. Claims about mid-table cities should be read with this in mind.
- **Stability:** weekly ranks, the share of weeks dearest / in the top 3 / in the bottom 3, and the standard deviation of each city's index.
- **Caveat:** these are average prices in the markets PBS samples (50 markets across 17 cities, about 3 per city), not a cost-of-living index. Housing, transport and wages are outside the SPI.

### Q2. Do poorer households face different inflation?
- **The series is PBS's own:** YoY change of the SPI by consumption quintile. We only parse it.
- **Why it differs:** the baskets differ, with weights fixed at 2015-16. **Decomposition:** PBS publishes each item's weekly impact in % points of the previous week's index, so the YoY change splits exactly:
  `contrib_i = Σ_k impact_{i,k} × I_{k−1} / I_{t−52}` over the 52 weeks to t.
  Missing weeks are handled without guessing. The *total* change over a gap is known from index levels (the first report after a gap states the previous week's index), so it is shown as "missing weeks (unattributed)". Windows with more than 4 missing weeks are skipped. PBS revisions get their own bucket. All **136** decomposed week-baskets (68 weeks × 2 baskets) close to PBS's published YoY within **0.01 pp** (4-decimal rounding).
- *Tried and rejected:* recovering 2015-16 base prices from the impact columns (p₀ = w·ΔP / (impact·I/100)) to decompose with price relatives. The implied p₀ varied by up to ±150% across weeks: PBS aggregates city-level item indices, not national average prices.

### Q3. How large is the Ramadan effect, by item?
- **Dates:** Ramadan as observed in Pakistan: 12 Mar–9 Apr 2024, 2–30 Mar 2025, 19 Feb–20 Mar 2026. 2023 falls before the archive. Weekly data makes ±1 day irrelevant.
- **Windows:** baseline = price dates 8–35 days before the first fast. The final week is skipped because stocking up already moves prices then; it is reported separately as the "run-up". Ramadan = price dates from the first to the last fast. National price = PBS's summary price, else the annex national average, else the mean of the 17 city averages.
- **Counterfactual:** the same window shape anchored on every week whose window does not touch any Ramadan. Its median per item is the item's *typical* change. **Effect = Ramadan change − typical change**, in percentage points.
- *Why not deflate by the overall SPI:* the SPI contains the Ramadan items themselves, and deflating makes every fixed-price item look like it fell.
- **"Clear" effects:** an effect counts as clear only if it exceeds the item's normal 4-week swing (the interquartile range of its typical change). The dashboard fades the rest.
- **Biggest limitation:** all three Ramadans so far fell in late winter or spring, so for strongly seasonal produce (onions, tomatoes, potatoes) Ramadan and season cannot be separated yet. Ramadan moves about 11 days earlier each year and reaches mid-winter around 2029–30; the weekly pipeline keeps accumulating the comparison.

## 7. Reproducing

```bash
uv sync
uv run python -m kitchen_inflation run --full-scan   # first run: whole media library
uv run python -m kitchen_inflation run               # weekly
uv run python -m kitchen_inflation run --offline     # rebuild from data/raw, no network
uv run pytest
```
