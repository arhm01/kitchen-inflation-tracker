"""Find every SPI report file PBS has published, without guessing URLs.

Why not build URLs from the date?
    The file names are hand-typed and change style every few months, e.g.
    ``SPI_AnnexUSCP_06072023.pdf``, ``ANNEX202620USCP2002.05.2024.pdf`` (a
    URL-encoded space that became a literal "20"), ``Annex-12-06-2025.pdf``,
    ``Annex_05.11.pdf`` (no year), ``Annex.pdf`` (no date at all). Guessing
    would silently miss weeks.

Where links come from (all three are merged):
    1. The human index pages (``/price-statistics/`` and the home page). They
       only list the latest week but are the first place a new report appears.
    2. Weekly SPI blog posts (WordPress category 113) via the REST API.
    3. The WordPress media library via the REST API. After the 2023/24 site
       migration this is the only place the back catalogue is still listed.

Each file is classified by kind (``annex`` = city-wise prices, ``summary`` =
executive summary with the quintile table, ...) and given a *hinted* week-end
date parsed from its name. The hint is only used to order and de-duplicate;
the authoritative date is read from inside the PDF at parse time.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import asdict, dataclass
from urllib.parse import unquote, urljoin

import pandas as pd
from bs4 import BeautifulSoup

from . import config, fetch

log = logging.getLogger(__name__)

FILE_EXT = re.compile(r"\.(pdf|xlsx?)$", re.I)


@dataclass
class SourceFile:
    url: str
    filename: str
    ext: str
    kind: str                 # annex | summary | report_xlsx | monthly | other
    uploaded: str | None      # ISO date WordPress recorded for the upload
    week_hint: str | None     # ISO date parsed from the filename (may be None)
    hint_rule: str            # which filename rule produced the hint
    found_via: str            # index | post | media


# --- classification --------------------------------------------------------

def classify(filename: str) -> str:
    n = filename.lower()
    if "monthly" in n:
        return "monthly"
    # "Anex" (sic, 10-08-2023) and "Annexure" both occur.
    if re.search(r"an+ex", n):
        return "annex"
    # "Sumary" (sic) is the spelling used for most of 2023-24.
    if re.search(r"exec|sum+ary", n):
        return "summary"
    if re.search(r"spi[\W_]*report", n):
        return "report_xlsx" if n.endswith((".xlsx", ".xls")) else "report"
    return "other"


# --- dates in file names ---------------------------------------------------

# No digit look-arounds on the separated form: a URL-encoded space often
# survives as a literal "20" glued to the date ("USCP2002.05.2024" is
# "USCP 02.05.2024"), and some names run on after the year
# ("13.06.2024202620USCP-merged"). Leftmost-match semantics pick the right
# split in both cases; see tests/test_discover.py.
_SEP_DMY = re.compile(r"(\d{1,2})[.\-_](\d{1,2})[.\-_](20\d{2})")
_COMPACT = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
_COMPACT_YY = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")  # "070923"
_DM_ONLY = re.compile(r"(?<!\d)(\d{2})[.\-_](\d{2})(?![.\-_]?\d)")


def _mk(d: str, m: str, y: str | int) -> dt.date | None:
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def week_hint(filename: str, uploaded: dt.date | None) -> tuple[dt.date | None, str]:
    """Best-effort week-end date from a file name.

    Returns ``(date, rule)``. Rules are tried strictest first; ``rule`` is
    stored so odd cases can be audited later.
    """
    stem = FILE_EXT.sub("", unquote(filename))
    # "%20" sometimes survived as a literal "20" ("...Report2020.06.2024"),
    # the separated-date regex anchors on the separators so this is harmless.
    hits = [_mk(*m.groups()) for m in _SEP_DMY.finditer(stem)]
    hits = [h for h in hits if h]
    if hits:
        return hits[-1], "dd.mm.yyyy"
    hits = [_mk(*m.groups()) for m in _COMPACT.finditer(stem)]
    hits = [h for h in hits if h]
    if hits:
        return hits[-1], "ddmmyyyy"
    hits = [_mk(d, m, 2000 + int(y)) for d, m, y in _COMPACT_YY.findall(stem)]
    hits = [h for h in hits if h and h.year >= 2015]
    if hits:
        return hits[-1], "ddmmyy"
    # "Annex_05.11.pdf": day and month only. Take the most recent such date
    # on or before the upload date (reports are uploaded the day after).
    m = _DM_ONLY.search(stem)
    if m and uploaded:
        for year in (uploaded.year, uploaded.year - 1):
            cand = _mk(m.group(1), m.group(2), year)
            if cand and cand <= uploaded + dt.timedelta(days=1):
                return cand, "dd.mm+upload_year"
    return None, "none"


# --- crawling --------------------------------------------------------------

def _wp_paginate(url: str, params: dict) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        resp = fetch.get(url, params={**params, "per_page": 100, "page": page})
        if resp.status_code == 400:  # WordPress: page beyond the last one
            break
        resp.raise_for_status()
        batch = resp.json()
        out.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        log.info("%s page %d/%d", url.rsplit("/", 1)[-1], page, total_pages)
        if page >= total_pages or not batch:
            break
        page += 1
    return out


def _links_in_html(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = (urljoin(base, a["href"]) for a in soup.find_all("a", href=True))
    return [u for u in links if FILE_EXT.search(u.split("?")[0])]


def _make(url: str, uploaded: dt.date | None, via: str) -> SourceFile:
    filename = unquote(url.split("?")[0].rsplit("/", 1)[-1])
    hint, rule = week_hint(filename, uploaded)
    return SourceFile(
        url=url,
        filename=filename,
        ext=filename.rsplit(".", 1)[-1].lower(),
        kind=classify(filename),
        uploaded=uploaded.isoformat() if uploaded else None,
        week_hint=hint.isoformat() if hint else None,
        hint_rule=rule,
        found_via=via,
    )


def crawl(full_media_scan: bool = True) -> pd.DataFrame:
    """Return one row per distinct file URL that looks SPI-related."""
    found: dict[str, SourceFile] = {}

    def add(sf: SourceFile) -> None:
        # Keep the first sighting but prefer one that carries an upload date.
        old = found.get(sf.url)
        if old is None or (old.uploaded is None and sf.uploaded):
            found[sf.url] = sf

    # 1. Human index pages.
    for page in config.INDEX_PAGES:
        resp = fetch.get(page)
        resp.raise_for_status()
        for u in _links_in_html(resp.text, page):
            add(_make(u, None, "index"))

    # 2. Weekly SPI posts; each links that week's annex + summary.
    posts = _wp_paginate(
        config.WP_POSTS,
        {"categories": config.SPI_POST_CATEGORY, "_fields": "date,link,content"},
    )
    for p in posts:
        up = dt.date.fromisoformat(p["date"][:10])
        for u in _links_in_html(p["content"]["rendered"], p["link"]):
            add(_make(u, up, "post"))

    # 3. Media library. A full scan (~60 requests) does not depend on PBS
    #    using any particular word in titles; the weekly run can use search.
    if full_media_scan:
        media = _wp_paginate(config.WP_MEDIA, {"_fields": "date,source_url"})
    else:
        media = []
        for term in ("SPI", "Annex"):
            media += _wp_paginate(
                config.WP_MEDIA, {"search": term, "_fields": "date,source_url"}
            )
    for m in media:
        u = m["source_url"]
        if FILE_EXT.search(u):
            add(_make(u, dt.date.fromisoformat(m["date"][:10]), "media"))

    df = pd.DataFrame([asdict(s) for s in found.values()])
    # Keep only SPI files. Annex/summary names rarely say "SPI", so filter on
    # kind, then drop the obviously unrelated annexes (CPI, trade, ...).
    spi_like = df["filename"].str.contains(r"spi|uscp", case=False, regex=True)
    keep = df["kind"].isin(["annex", "summary", "report_xlsx", "report"]) & (
        spi_like | df["kind"].eq("annex")
    )
    unrelated = df["filename"].str.contains(
        r"cpi(?!.*spi)|wpi|trade|lsm|gdp|census|labour|coding", case=False, regex=True
    ) & ~spi_like
    df = df[keep & ~unrelated].copy()
    return df.sort_values(["week_hint", "kind", "uploaded"], na_position="first")
