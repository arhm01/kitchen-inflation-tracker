"""Cleaning rules and the YoY decomposition on small synthetic data."""

import datetime as dt

import pandas as pd
import pytest

from kitchen_inflation.clean import norm_spec
from kitchen_inflation.validate import decomposition


def test_spec_alias_and_typos():
    assert norm_spec("Gas Charges upto 3.3719 MMBTU", "MMBTU") == norm_spec("Gas Charges for Q1", "MMBTU")
    assert norm_spec("Telephone Call Charges", "Per Minut") == norm_spec("Telephone Call Charges", "Per Minute")
    assert norm_spec("Tea 190 gm", "Each") != norm_spec("Tea 170 gm", "Each")


def _synthetic(weeks: int, drop: set[int] = frozenset(), revise_at: int | None = None):
    """Two items; item 1 adds 0.2% a week, item 2 adds 0.1%. The index is
    their running sum, so the decomposition has a known answer."""
    start = dt.date(2025, 1, 2)
    q_rows, i_rows = [], []
    level = 100.0
    levels = [level]
    for k in range(1, weeks + 1):
        # A revision restates last week's level; like PBS, this week's index
        # is then computed from the revised level.
        reported_prev = levels[-1] + (1.0 if k == revise_at else 0.0)
        imp1, imp2 = 0.2, 0.1
        new = reported_prev * (1 + (imp1 + imp2) / 100)
        levels.append(new)
        w = start + dt.timedelta(days=7 * k)
        if k in drop:
            continue
        year_ago = levels[k - 52] if k >= 52 else None
        for g in ("Q1", "Combined"):
            q_rows.append({"week_end": w, "group": g, "spi": new, "spi_prev_week": reported_prev,
                           "spi_year_ago": year_ago, "wow_pct": imp1 + imp2,
                           "yoy_pct": 100 * (new / year_ago - 1) if year_ago else None})
        for item, imp in ((1, imp1), (2, imp2)):
            i_rows.append({"week_end": w, "item_no": item, "impact_q1": imp, "impact_combined": imp,
                           "weight_q1": 50.0, "weight_combined": 50.0})
    return {"quintiles": pd.DataFrame(q_rows), "summary_items": pd.DataFrame(i_rows)}


def _closure(d):
    tot = d.groupby(["week_end", "basket"]).agg(s=("contrib_pp", "sum"), p=("pbs_yoy", "first"))
    return (tot["s"] - tot["p"]).abs().max()


def test_decomposition_closes_exactly():
    d = decomposition(_synthetic(60))
    assert d["week_end"].nunique() == 60 - 52 + 1
    assert _closure(d) < 1e-9
    last = d[(d.week_end == d.week_end.max()) & (d.basket == "combined")].set_index("item_no")
    assert last.loc[1, "contrib_pp"] == pytest.approx(2 * last.loc[2, "contrib_pp"], rel=0.01)


def test_decomposition_with_missing_weeks_and_revision():
    d = decomposition(_synthetic(60, drop={55, 56}, revise_at=58))
    assert _closure(d) < 1e-9  # gap -> item 0, revision -> item -1
    last = d[d.week_end == d.week_end.max()].set_index(["basket", "item_no"])
    assert last.loc[("combined", 0), "contrib_pp"] > 0
    assert last.loc[("combined", -1), "contrib_pp"] != 0


def test_too_many_missing_weeks_skipped():
    # Weeks 53-57 missing: week 52's window doesn't touch them, but every
    # later window has 5 missing weeks (> MAX_MISSING = 4) and is skipped.
    d = decomposition(_synthetic(60, drop={53, 54, 55, 56, 57}))
    assert set(d["week_end"]) == {dt.date(2025, 1, 2) + dt.timedelta(days=7 * 52)}
