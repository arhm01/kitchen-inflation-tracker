"""Parser tests against real PBS files (tests/fixtures, public data)."""

import datetime as dt
from pathlib import Path

import pytest

from kitchen_inflation.parse_annex import parse_annex
from kitchen_inflation.parse_summary import parse_summary
from kitchen_inflation.parse_xlsx import parse_xlsx

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def annex_2026():
    return parse_annex(FX / "Annex_05.11.pdf")


def test_annex_shape(annex_2026):
    r = annex_2026
    assert r.week_end == dt.date(2026, 11, 5)
    assert len(r.rows) == 51 * 17
    assert {x.item_no for x in r.rows} == set(range(1, 52))
    assert len({x.city_code for x in r.rows}) == 17
    assert not r.warnings
    assert {x.method for x in r.rows} == {"mcid"}


def test_annex_matches_pbs_excel_exactly(annex_2026):
    """The PDF parse must reproduce PBS's own XLSX for the same week."""
    week, xl = parse_xlsx(FX / "Annex_05.11.2026.xlsx")
    assert week == dt.date(2026, 11, 5)
    pdf = {(a.item_no, a.city_code): a for a in annex_2026.rows}
    ref = {(a.item_no, a.city_code): a for a in xl}
    assert pdf.keys() == ref.keys()
    for k, b in ref.items():
        a = pdf[k]
        for f in ("price_min", "price_avg", "price_max"):
            assert getattr(a, f) == pytest.approx(getattr(b, f), abs=0.006), (k, f)
        assert a.item_name == b.item_name.strip()


def test_overlapping_description_and_unit_cells(annex_2026):
    """Text extraction interleaves these ("Qualit1y )Kg"); mcid cells must not."""
    rows = {(a.item_no, a.city_code): a for a in annex_2026.rows}
    assert rows[(2, 1)].item_name == "Rice Basmati Broken (Average Quality)"
    assert rows[(2, 1)].unit == "1 Kg"
    # Description overflowing into the first city's columns stays in the description.
    assert rows[(13, 1)].item_name.endswith("5 Litre Tin")
    assert rows[(13, 1)].price_avg == pytest.approx(3115.0)
    assert rows[(50, 1)].unit == "Per Minute"


def test_zero_means_not_collected(annex_2026):
    rows = {(a.item_no, a.city): a for a in annex_2026.rows}
    assert rows[(3, "Gujranwala")].price_avg == 0  # turned into NULL in clean.py (C1)


def test_annex_2025_layout():
    """A different year: other page size and x-offsets, values without decimals."""
    r = parse_annex(FX / "Annex-12-06-2025.pdf")
    assert r.week_end == dt.date(2025, 6, 12)
    assert len(r.rows) == 867 and not r.warnings
    isb_rice = next(x for x in r.rows if x.item_no == 2 and x.city_code == 1)
    assert (isb_rice.price_min, isb_rice.price_avg, isb_rice.price_max) == (250.0, 258.99, 280.0)


def test_summary():
    s = parse_summary(FX / "SPI-Executive-Summary-Report-05.11.2026.pdf")
    assert s.week_end == dt.date(2026, 11, 5)
    q = {r["group"]: r for r in s.quintiles}
    assert q["Q1"]["yoy_pct"] == 10.15 and q["Q5"]["yoy_pct"] == 12.75
    assert q["Combined"]["spi"] == 374.61
    assert len(s.items) == 51
    assert sum(i["weight_q1"] for i in s.items) == pytest.approx(100, abs=0.01)
    assert sum(i["weight_combined"] for i in s.items) == pytest.approx(100, abs=0.01)
    # Item impacts add up to the published week-on-week change.
    assert sum(i["impact_combined"] for i in s.items) == pytest.approx(q["Combined"]["wow_pct"], abs=0.01)
    assert sum(i["impact_q1"] for i in s.items) == pytest.approx(q["Q1"]["wow_pct"], abs=0.01)
