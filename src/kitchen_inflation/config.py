"""Paths, URLs and constants shared by every stage of the pipeline.

Everything that a future maintainer might need to tweak lives here, so the
other modules contain logic only.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"            # downloaded PDFs/XLSX, exactly as PBS served them
INTERIM = DATA / "interim"    # catalog + per-file parse output (CSV, for diffing)
DB_PATH = DATA / "spi.duckdb"
SITE = ROOT / "site"          # static dashboard published to GitHub Pages
REPORTS = ROOT / "reports"    # validation report and other generated markdown

# --- Source ----------------------------------------------------------------
BASE = "https://www.pbs.gov.pk"
# Human-facing index pages. They only ever link the latest week, but we crawl
# them anyway so a brand-new report is found even before WordPress indexes it.
INDEX_PAGES = [
    f"{BASE}/price-statistics/",
    f"{BASE}/",
]
# The site is WordPress. Its REST API exposes (a) the weekly SPI posts and
# (b) the full media library, which is the only place the back catalogue of
# report files is still listed after the 2023/24 site migration.
WP_POSTS = f"{BASE}/wp-json/wp/v2/posts"
WP_MEDIA = f"{BASE}/wp-json/wp/v2/media"
SPI_POST_CATEGORY = 113  # "Weekly SPI" category id on the WordPress site

USER_AGENT = (
    "kitchen-inflation-tracker/0.1 (open-source research project; "
    "weekly fetch of public SPI reports)"
)
REQUEST_DELAY_S = 1.0   # pause between requests to the PBS server
TIMEOUT_S = 90
MAX_RETRIES = 4
