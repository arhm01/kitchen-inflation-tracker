# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary (portfolio case study):** hiring managers and recruiters for data analyst / analytics engineer roles, reading arhm01's portfolio. They skim first: they need the findings, the evidence of rigor, and the engineering judgement within a minute, with depth available if they stay.
- **Secondary (live dashboard, `site/index.html`):** anyone who wants to explore the weekly SPI data by city, quintile and item.

## Product Purpose

An automated weekly pipeline over the Pakistan Bureau of Statistics' Sensitive Price Indicator PDFs: discover files, parse city-level prices and quintile tables, validate, load into DuckDB, publish a dashboard. The case-study page turns that into a portfolio piece: what the data shows and how it was built. Success: a hiring manager comes away believing the author finds real insight in messy public data and can be trusted with production data work.

## Positioning

Built from PBS's own PDFs, end to end, with the parse verified against PBS's Excel files (every overlapping cell matches) and every cleaning decision documented. Insights are computed, re-checked weekly, and stated only as strongly as the data supports (e.g. Ramadan effects that can't yet be separated from season are labelled as such).

## Operating Context

- The case study is delivered as **one self-contained HTML file** (inline CSS, JS and data, no external requests) that the user copies into their own portfolio site. Its numbers are frozen at build time; regenerating means re-running the pipeline and re-copying the file.
- The live dashboard stays on GitHub Pages: https://arhm01.github.io/kitchen-inflation-tracker/ (refreshed weekly by GitHub Actions). Repo: https://github.com/arhm01/kitchen-inflation-tracker.
- Sibling portfolio pages (`../pakistan-cashless`, `../zameen-price-map`) share one visual system; the case study must read as part of the same body of work.

## Capabilities and Constraints

- Data: 51 SPI items × 17 cities, weekly, July 2023 onward (one isolated week from Feb 2023); quintile SPI levels and item weights/impacts from the executive summaries. Archive gaps (32 weeks) are real and documented.
- Figures in the write-up come from `src/kitchen_inflation/insights.py`; qualitative claims are re-checked each run (check S1).
- No fabricated figures, quotes, or employer/client claims.

## Brand Commitments

- Byline and links use the GitHub handle **arhm01** only; no real name.
- Source attribution to the Pakistan Bureau of Statistics, with the note that the analysis is independent.

## Evidence on Hand

- `data/clean/*.csv`, `data/spi.duckdb` views, `reports/validation.md`, `docs/methods.md`.
- PDF-vs-Excel agreement: 156,060 of 156,060 overlapping cells across 60 weeks.
- YoY decomposition closes to PBS's published figures within 0.01 pp for every decomposed week.
- Data-quality findings with specifics (Larkana tomato unit slip, chilli powder possible pack change, PBS index revision, archive gaps).

## Product Principles

1. Findings first, engineering second, but the engineering is visible proof, not decoration.
2. Never claim more than the data shows; say what can't be known yet.
3. Every number is reproducible from the pipeline.
4. Skimmable in a minute, rewarding in ten.
