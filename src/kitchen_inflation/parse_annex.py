"""Extract Appendix-A (city-wise prices of the 51 SPI items) from an annex PDF.

Layout (stable since at least 2023, but page size and x-offsets vary):

    APPENDIX-A  CONSUMER PRICES OF ESSENTIAL ITEMS
    SL. | Islamabad (01) | Rawalpindi (02) | ...            | SL.
    NO. DESCRIPTION UNIT | MIN AVG MAX | MIN AVG MAX | ...  | NO.
    PRICES ON 05-11-2026
    1Wheat Flour Bag 20 Kg 3240.00 3278.77 3333.33 ...       1

Pages 1-2 hold 7 cities each, page 3 holds Bannu, Quetta, Khuzdar plus the
national average and PBS's own % changes. Some years add a 4th/5th page
(Appendix-B fertiliser prices, Utility Stores comparison) which we skip.

Parsing decisions (each is documented in docs/methods.md):

* Numbers are assigned to a column by **x-position** against the MIN/AVG/MAX
  header words, not by their order in the line. A blank cell therefore can't
  shift every following value one city to the left.
* Rows are anchored on the *trailing* serial-number column, which is never
  glued to other text (the leading one is: "1Wheat Flour").
* Description and unit cells overlap on the page, so plain text extraction
  interleaves them ("Average Qualit1y )Kg"). The PDFs are tagged, and every
  table cell is its own marked-content sequence (``mcid``), so we rebuild the
  two cells from their mcids. Untagged pages fall back to an x-split plus a
  unit regex and are flagged ``method='xsplit'``.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

CITY_RE = re.compile(r"([A-Z][A-Za-z .]+?)\s*\((\d{2})\)")
DATE_RE = re.compile(r"PRICES\s+ON\s+(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", re.I)
NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
UNIT_TAIL = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:kg|gm|ltr|litre|mtr)\b.*|each|dozen|pair|per\s+\w+|mmbtu)\s*$",
    re.I,
)

# The 17 SPI cities and their PBS codes. Used to validate headers, so that a
# misread header fails loudly instead of producing a new "city".
CITIES = {
    1: "Islamabad", 2: "Rawalpindi", 3: "Gujranwala", 4: "Sialkot", 5: "Lahore",
    6: "Faisalabad", 7: "Sargodha", 8: "Multan", 9: "Bahawalpur", 10: "Karachi",
    11: "Hyderabad", 12: "Sukkur", 13: "Larkana", 14: "Peshawar", 15: "Bannu",
    16: "Quetta", 17: "Khuzdar",
}


@dataclass
class PriceRow:
    item_no: int
    item_name: str
    unit: str
    city: str
    city_code: int
    price_min: float | None
    price_avg: float | None
    price_max: float | None
    page: int = 0
    method: str = "mcid"


@dataclass
class AnnexResult:
    week_end: dt.date | None
    rows: list[PriceRow] = field(default_factory=list)
    national: list[dict] = field(default_factory=list)  # PBS national averages
    warnings: list[str] = field(default_factory=list)
    pages_used: list[int] = field(default_factory=list)


def clean_num(s) -> float | None:
    """'3,240.00' -> 3240.0; '', '-', 'N.A.' -> None. Zeros are kept here and
    turned into 'not available' in the cleaning stage, where it is logged."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", "")
    if not s or not NUM_RE.fullmatch(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(text: str) -> dt.date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = (int(g) for g in m.groups())
    if y < 100:
        y += 2000
    try:
        return dt.date(y, mth, d)
    except ValueError:
        return None


def _cells_by_mcid(chars: list[dict]) -> list[tuple[float, float, str]]:
    """Group consecutive chars with the same marked-content id into cells.

    Returns ``(x0, x1, text)``. Chars arrive in content-stream order, which is
    the order PBS's export wrote the cells, so a cell is never interleaved
    with its neighbour even when the two overlap on the page.
    """
    cells = []
    for _, grp in itertools.groupby(chars, key=lambda c: c.get("mcid")):
        grp = list(grp)
        text = re.sub(r"\s+", " ", "".join(c["text"] for c in grp)).strip()
        if text:
            cells.append((min(c["x0"] for c in grp), max(c["x1"] for c in grp), text))
    return cells


def _parse_page(page, page_no: int, res: AnnexResult) -> None:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    text = page.extract_text() or ""
    if "APPENDIX-A" not in text.upper().replace(" ", "") and not CITY_RE.search(text):
        return

    # --- header: cities and numeric column centres -------------------------
    header_line = next((ln for ln in text.splitlines() if len(CITY_RE.findall(ln)) >= 2), None)
    if not header_line:
        return
    header_line = re.sub(r"^\s*SL\.?\s*", "", header_line)
    cities = [(n.strip(), int(c)) for n, c in CITY_RE.findall(header_line)]
    for name, code in cities:
        if CITIES.get(code, "").lower() != name.lower():
            res.warnings.append(f"p{page_no}: unexpected city header {name!r} ({code:02d})")
    has_national = "national" in header_line.lower()

    stat_words = [w for w in words if w["text"] in ("MIN", "AVG", "MAX")]
    if not stat_words:
        res.warnings.append(f"p{page_no}: no MIN/AVG/MAX header")
        return
    hdr_top = min(w["top"] for w in stat_words)
    stat_words = sorted((w for w in stat_words if abs(w["top"] - hdr_top) < 3), key=lambda w: w["x0"])
    centres = [((w["x0"] + w["x1"]) / 2, w["text"]) for w in stat_words]
    n_city_cols = 3 * len(cities)
    if len(centres) < n_city_cols:
        res.warnings.append(f"p{page_no}: {len(centres)} stat columns for {len(cities)} cities")
        return
    spacing = min(b[0] - a[0] for a, b in zip(centres, centres[1:])) if len(centres) > 1 else 25
    unit_hdr = next((w for w in words if w["text"] == "UNIT" and abs(w["top"] - hdr_top) < 3), None)
    first_num_x = centres[0][0] - spacing / 2

    # Data rows start below the "PRICES ON dd-mm-yyyy" banner; anything above
    # it (e.g. the column-number row "1 2 3 4 ... 24 1") is header.
    # (The page title "CONSUMER PRICES OF ..." also contains PRICES, hence
    # the "below the MIN/AVG/MAX header" condition.)
    banner = [w for w in words if w["text"].upper() == "PRICES" and w["top"] > hdr_top]
    data_top = (banner[0]["top"] + 3) if banner else hdr_top + 12

    # Trailing serial-number column: the right-most "SL." / "NO." header.
    sl_hdr = max((w for w in words if w["text"] in ("NO.", "SL.")), key=lambda w: w["x0"])
    sl_x = (sl_hdr["x0"] + sl_hdr["x1"]) / 2
    anchors = [
        w for w in words
        if w["top"] > data_top
        and re.fullmatch(r"\d{1,2}", w["text"])
        and abs((w["x0"] + w["x1"]) / 2 - sl_x) < spacing / 2
    ]
    if not anchors:
        res.warnings.append(f"p{page_no}: no data rows found")
        return
    res.pages_used.append(page_no)
    tagged = sum(c.get("mcid") is not None for c in page.chars) > 0.9 * len(page.chars)

    for a in anchors:
        item_no = int(a["text"])
        top = a["top"]
        row_chars = [c for c in page.chars if abs(c["top"] - top) < 2.5]
        if tagged:
            cells = _cells_by_mcid(row_chars)
            method = "mcid"
        else:
            cells = [(w["x0"], w["x1"], w["text"]) for w in words if abs(w["top"] - top) < 2.5]
            method = "xsplit"

        # --- numeric cells by nearest column centre --------------------------
        values: dict[int, float | None] = {}
        text_cells: list[tuple[float, float, str]] = []
        for x0, x1, t in cells:
            cx = (x0 + x1) / 2
            if abs(cx - sl_x) < spacing / 2 and t == a["text"]:
                continue  # trailing serial number
            if cx < first_num_x or not NUM_RE.fullmatch(t.replace(",", "")):
                text_cells.append((x0, x1, t))
                continue
            idx = min(range(len(centres)), key=lambda i: abs(centres[i][0] - cx))
            if abs(centres[idx][0] - cx) > spacing * 0.6:
                continue
            if idx in values:
                res.warnings.append(f"p{page_no} item {item_no}: two values in column {idx}")
            values[idx] = clean_num(t)

        # --- description and unit -------------------------------------------
        text_cells = [c for c in text_cells if c[0] < first_num_x]
        text_cells.sort(key=lambda c: c[0])
        # Drop the leading serial number (own cell, or glued: "1Wheat Flour").
        stripped = []
        for x0, x1, t in text_cells:
            t = re.sub(rf"^{item_no}(?=\D|$)", "", t).strip() if not stripped else t
            if t:
                stripped.append((x0, x1, t))
        desc, unit = "", ""
        if tagged and len(stripped) >= 2:
            # The unit cell is the one starting nearest the UNIT header.
            ux = unit_hdr["x0"] if unit_hdr else stripped[-1][0]
            ui = min(range(1, len(stripped)), key=lambda i: abs(stripped[i][0] - ux))
            unit = stripped[ui][2]
            desc = " ".join(t for i, (_, _, t) in enumerate(stripped) if i != ui)
        else:
            if method == "mcid":
                method = "mcid+regex"
            desc = " ".join(t for _, _, t in stripped)
            m = UNIT_TAIL.search(desc)
            if m:
                unit = m.group(1).strip()
                desc = desc[: m.start()].strip()
        desc = re.sub(r"\s+", " ", desc)
        unit = re.sub(r"\s+", " ", unit)

        for k, (name, code) in enumerate(cities):
            trio = [values.get(3 * k + j) for j in range(3)]
            res.rows.append(PriceRow(item_no, desc, unit, name, code, *trio, page=page_no, method=method))
        if has_national and len(centres) >= n_city_cols + 3:
            res.national.append({
                "item_no": item_no,
                "nat_min": values.get(n_city_cols),
                "nat_avg": values.get(n_city_cols + 1),
                "nat_max": values.get(n_city_cols + 2),
            })


def parse_annex(path: Path) -> AnnexResult:
    with pdfplumber.open(path) as pdf:
        first_text = "\n".join((p.extract_text() or "") for p in pdf.pages[:1])
        res = AnnexResult(week_end=_parse_date(first_text))
        for i, page in enumerate(pdf.pages, start=1):
            try:
                _parse_page(page, i, res)
            except Exception as exc:  # keep going; the validator will catch gaps
                res.warnings.append(f"p{i}: {type(exc).__name__}: {exc}")
    return res
