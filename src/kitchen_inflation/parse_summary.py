"""Extract two tables from the weekly SPI executive summary PDF.

1. Annexure-III, para 2: the SPI index level for each consumption quintile
   (Q1 = poorest ... Q5 = richest) and combined, with PBS's own week-on-week
   and year-on-year % changes.
2. Para 5: one row per item with this week's national average price, the
   previous and corresponding-week prices, % changes, the item's *weight* in
   the lowest-quintile and combined baskets, and its impact in % points.

The weights are what explain question 2 (why the poorest quintile's
inflation differs): they are fixed at the 2015-16 base, so differences in
quintile inflation come entirely from which items each basket leans on.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from .parse_annex import NUM_RE, _cells_by_mcid, clean_num

WEEK_RE = re.compile(r"WEEK\s+ENDED\s+ON\s+(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", re.I)
N = r"(-?\d[\d,]*\.\d+|-?\d+)"
QUINTILE_RE = re.compile(
    rf"^\s*(Q[1-5]|Combined)\b\s*(\([^)]*\))?\s+{N}\s+{N}\s+{N}\s+{N}\s+{N}\s*$", re.I
)


@dataclass
class SummaryResult:
    week_end: dt.date | None
    quintiles: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _date(m) -> dt.date | None:
    if not m:
        return None
    d, mth, y = (int(g) for g in m.groups())
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, mth, d)
    except ValueError:
        return None


def parse_summary(path: Path) -> SummaryResult:
    with pdfplumber.open(path) as pdf:
        texts = [(p.extract_text() or "") for p in pdf.pages]
        res = SummaryResult(week_end=_date(WEEK_RE.search(texts[0] if texts else "")))

        # --- quintile table ------------------------------------------------
        for text in texts:
            for line in text.splitlines():
                m = QUINTILE_RE.match(line)
                if not m:
                    continue
                group, band, *nums = m.groups()
                vals = [clean_num(v) for v in nums]
                res.quintiles.append({
                    "group": group.upper() if group.lower() != "combined" else "Combined",
                    "income_band": (band or "").strip("() "),
                    "spi": vals[0], "spi_prev_week": vals[1], "spi_year_ago": vals[2],
                    "wow_pct": vals[3], "yoy_pct": vals[4],
                })
            if len(res.quintiles) >= 6:
                break
        # The 10-week trend table also contains lines that could look similar;
        # keep only the first block of six.
        res.quintiles = res.quintiles[:6]
        if len(res.quintiles) != 6:
            res.warnings.append(f"quintile table: {len(res.quintiles)} of 6 rows")

        # --- item table (para 5) ---------------------------------------------
        for pno, page in enumerate(pdf.pages, start=1):
            if "Weight" not in texts[pno - 1] and "TOTAL" not in texts[pno - 1]:
                continue
            words = page.extract_words()
            tops = sorted({round(w["top"], 1) for w in words})
            rows_seen: set[float] = set()
            for top in tops:
                if any(abs(top - t) < 2.5 for t in rows_seen):
                    continue
                row_chars = [c for c in page.chars if abs(c["top"] - top) < 2.5]
                cells = [t for _, _, t in _cells_by_mcid(row_chars)]
                nums = [c for c in cells if NUM_RE.fullmatch(c.replace(",", ""))]
                text_cells = [c for c in cells if c not in nums or cells.index(c) < 1]
                # A data row: rank, name, unit, then exactly 9 numbers.
                if len(cells) < 12 or len(nums) < 10:
                    continue
                tail = cells[-9:]
                if not all(NUM_RE.fullmatch(t.replace(",", "")) for t in tail):
                    continue
                rows_seen.add(top)
                head = cells[:-9]
                head = [h for h in head if not re.fullmatch(r"\d{1,2}", h)]
                name = head[0] if head else ""
                unit = head[-1] if len(head) > 1 else ""
                v = [clean_num(t) for t in tail]
                res.items.append({
                    "item_name": re.sub(r"\s+", " ", name), "unit": unit,
                    "price": v[0], "price_prev_week": v[1], "price_year_ago": v[2],
                    "wow_pct": v[3], "yoy_pct": v[4],
                    "weight_q1": v[5], "weight_combined": v[6],
                    "impact_q1": v[7], "impact_combined": v[8],
                    "page": pno,
                })
        if len(res.items) != 51:
            res.warnings.append(f"item table: {len(res.items)} of 51 rows")
    return res
