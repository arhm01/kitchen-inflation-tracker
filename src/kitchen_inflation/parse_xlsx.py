"""Read the city-price table (Appendix-A) from PBS's XLSX annex.

PBS only started publishing XLSX annexes in late 2025, so the pipeline parses
the PDFs for every week. The XLSX files serve as an independent reference:
``tests/test_pdf_vs_xlsx.py`` checks that the PDF parser reproduces them.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import openpyxl

from .parse_annex import CITY_RE, PriceRow, _parse_date, clean_num


def parse_xlsx(path: Path) -> tuple[dt.date | None, list[PriceRow]]:
    """Return (week_end from the 'PRICES ON dd-mm-yyyy' cell, rows)."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]  # Appendix-A
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    out: list[PriceRow] = []
    cities: list[tuple[str, int]] = []
    week = None
    for r in rows:
        cells = ["" if c is None else str(c).strip() for c in r]
        if week is None:
            week = _parse_date(" ".join(cells))
        # Header row with city names, e.g. "Islamabad (01)".
        found = [(i, CITY_RE.fullmatch(c)) for i, c in enumerate(cells)]
        found = [(i, m) for i, m in found if m]
        if found:
            cities = [(m.group(1).strip(), int(m.group(2))) for _, m in found]
            starts = [i for i, _ in found]
            continue
        if not cities or not re.fullmatch(r"\d{1,2}", cells[0] or ""):
            continue
        if not cells[1] or cells[1] == "2":  # column-number row "1 2 3 4 ..."
            continue
        item_no = int(cells[0])
        for (city, code), col in zip(cities, starts):
            mn, avg, mx = (clean_num(cells[col + k]) for k in range(3))
            out.append(PriceRow(item_no, cells[1], cells[2], city, code, mn, avg, mx))
    return week, out
