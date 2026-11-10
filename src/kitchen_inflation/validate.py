"""Validation checks. Each returns issue dicts with a severity:

* error -> the weekly GitHub Action fails and nothing is published. Reserved
           for things that mean the parse is wrong, not that prices are odd.
* warn  -> published, but listed in reports/validation.md for a human.
* info  -> a cleaning decision was applied; logged for transparency.

V1  Shape: every week has 51 items x 17 cities.                     (error)
V2  Summary: 6 quintile rows; lowest/combined weights each sum to 100. (error)
V3  Price sanity: no negatives; min <= avg <= max.                   (error/warn)
V4  Cross-city outlier: a city's price is >3x or <1/3 of that week's
    median across cities (typical sign of a unit mix-up or misplaced
    decimal).                                                         (warn)
V5  Unit/spec change: the item's description or unit text changed;
    escalated to warn if the national median jumps >25% that week.    (info/warn)
V6  Week-on-week jump >60% in the national median price, outside a
    spec change. Perishables do this legitimately; listed, not fixed. (info)
V7  Calendar: weeks end on Thursday (Wednesday before holidays);
    missing weeks are listed.                                          (warn)
V8  Cross-file: summary price == annex national average for the item. (warn)
V9  Reference: PDF parse == PBS XLSX for weeks where both exist.      (error if >0.1% cells)
V10 Decomposition: item YoY contributions sum to PBS's published YoY. (warn if off by >0.15pp)
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd


def issue(severity: str, check: str, subject: str, detail: str) -> dict:
    return {"severity": severity, "check": check, "subject": str(subject), "detail": detail}


PERISHABLE = {16, 21, 22, 23, 28, 7, 11}  # bananas, potatoes, onions, tomatoes, garlic, chicken, eggs


def run_checks(t: dict) -> list[dict]:
    out: list[dict] = []
    p = t["prices"]

    # V1 shape
    shape = p.groupby("week_end").agg(items=("item_no", "nunique"), cities=("city_code", "nunique"),
                                      rows=("item_no", "size"))
    for week, r in shape.iterrows():
        if r["items"] != 51 or r["cities"] != 17 or r["rows"] != 867:
            out.append(issue("error", "V1_shape", week,
                             f"{r['items']} items, {r['cities']} cities, {r['rows']} rows (want 51/17/867)"))

    # V2 summary
    q = t["quintiles"]
    for week, grp in q.groupby("week_end"):
        if len(grp) != 6 or set(grp["group"]) != {"Q1", "Q2", "Q3", "Q4", "Q5", "Combined"}:
            out.append(issue("error", "V2_quintiles", week, f"{len(grp)} quintile rows"))
    si = t["summary_items"]
    wow = q.pivot_table(index="week_end", columns="group", values="wow_pct")
    for week, grp in si.groupby("week_end"):
        for col in ("weight_q1", "weight_combined"):
            s = grp[col].sum()
            if abs(s - 100) > 0.05 or len(grp) != 51:
                out.append(issue("error", "V2_weights", week, f"{col} sums to {s:.3f} over {len(grp)} items"))
        # Item impacts must add up to the published week-on-week change.
        for col, g in (("impact_q1", "Q1"), ("impact_combined", "Combined")):
            if week in wow.index and abs(grp[col].sum() - wow.at[week, g]) > 0.02:
                out.append(issue("warn", "V2_impacts", week,
                                 f"{col} sums to {grp[col].sum():.3f} vs PBS WoW {wow.at[week, g]:.2f}%"))

    # V11 index revisions: this week's "previous week" index should equal the
    # index the previous report published. Differences are PBS revisions.
    for g, grp in q.groupby("group"):
        grp = grp.sort_values("week_end")
        days = grp["week_end"].diff().map(lambda d: d.days if pd.notna(d) else None)
        diff = grp["spi_prev_week"] - grp["spi"].shift()
        for wk, d, n, prev_wk in zip(grp["week_end"], diff, days, grp["week_end"].shift()):
            if n is not None and n <= 10 and abs(d) > 0.02:
                out.append(issue("info", "V11_index_revision", f"{wk} {g}",
                                 f"previous-week index revised by {d:+.2f} points vs the {prev_wk} report"))

    # V3 sanity
    neg = p[(p[["price_min", "price_avg", "price_max"]] < 0).any(axis=1)]
    for r in neg.itertuples():
        out.append(issue("error", "V3_negative", f"{r.week_end} {r.city} #{r.item_no}", "negative price"))
    bad = p[(p["price_avg"] < p["price_min"] - 0.01) | (p["price_avg"] > p["price_max"] + 0.01)]
    for r in bad.itertuples():
        out.append(issue("warn", "V3_avg_outside_range", f"{r.week_end} {r.city} {r.short_name}",
                         f"min {r.price_min} avg {r.price_avg} max {r.price_max}"))

    # V4 cross-city outliers
    x = p[["week_end", "item_no", "city", "short_name", "price_avg"]].copy()
    x["med"] = x.groupby(["week_end", "item_no"])["price_avg"].transform("median")
    x["ratio"] = x["price_avg"] / x["med"]
    for r in x[(x["ratio"] > 3) | (x["ratio"] < 1 / 3)].itertuples():
        out.append(issue("warn", "V4_city_outlier", f"{r.week_end} {r.city} {r.short_name}",
                         f"{r.price_avg} vs median {r.med:.2f} ({r.ratio:.2f}x)"))

    # V5 / V6 spec changes and jumps on the national median
    nm = (p.groupby(["item_no", "short_name", "week_end", "spec_version"])["price_avg"].median()
          .reset_index().sort_values(["item_no", "week_end"]))
    nm["prev"] = nm.groupby("item_no")["price_avg"].shift()
    nm["prev_spec"] = nm.groupby("item_no")["spec_version"].shift()
    nm["chg"] = nm["price_avg"] / nm["prev"] - 1
    items = t["items"].set_index(["item_no", "spec_version"])
    for r in nm[nm["prev_spec"].notna() & (nm["spec_version"] != nm["prev_spec"])].itertuples():
        old = items.loc[(r.item_no, int(r.prev_spec))]
        new = items.loc[(r.item_no, r.spec_version)]
        sev = "warn" if abs(r.chg) > 0.25 else "info"
        out.append(issue(sev, "V5_spec_change", f"{r.week_end} #{r.item_no} {r.short_name}",
                         f"'{old['item_name']} | {old['unit']}' -> '{new['item_name']} | {new['unit']}'"
                         f"; median price {r.prev:.2f} -> {r.price_avg:.2f} ({r.chg:+.0%})"))
    # Only consecutive weeks: a jump across an archive gap says nothing.
    nm["days"] = nm.groupby("item_no")["week_end"].diff().map(lambda d: d.days if pd.notna(d) else 99)
    jumps = nm[(nm["chg"].abs() > 0.6) & (nm["spec_version"] == nm["prev_spec"]) & (nm["days"] <= 10)]
    for r in jumps.itertuples():
        perishable = r.item_no in PERISHABLE
        # A packaged/administered item nearly doubling overnight with an
        # unchanged description may be an unannounced pack-size change; we
        # can't tell from the PDF, so it is flagged for a human, not altered.
        out.append(issue("info" if perishable else "warn",
                         "V6_big_jump" if perishable else "V6_possible_unit_change",
                         f"{r.week_end} #{r.item_no} {r.short_name}",
                         f"national median {r.prev:.2f} -> {r.price_avg:.2f} ({r.chg:+.0%}) in one week"
                         + (" (perishable)" if perishable else ", description unchanged")))

    # V7 calendar
    weeks = sorted(p["week_end"].unique())
    for w in weeks:
        if w.weekday() not in (2, 3):
            out.append(issue("warn", "V7_weekday", w, f"week ends on a {w:%A}"))
    for a, b in zip(weeks, weeks[1:]):
        gap = (b - a).days
        if gap > 8:
            out.append(issue("warn", "V7_missing_weeks", f"{a} -> {b}",
                             f"{round(gap / 7) - 1} week(s) with no annex found"))

    # V8 summary price vs annex national average
    nat = t["national"]
    if not nat.empty and not si.empty:
        m = si.merge(nat, on=["week_end", "item_no"], how="inner")
        off = m[(m["price"] - m["nat_avg"]).abs() > 0.011]
        for r in off.itertuples():
            out.append(issue("warn", "V8_summary_vs_annex", f"{r.week_end} #{r.item_no}",
                             f"summary {r.price} vs annex national avg {r.nat_avg}"))

    # V9 PDF vs XLSX
    for r in t["xlsx_check"].itertuples():
        share = r.mismatches / max(r.cells, 1)
        sev = "error" if share > 0.001 or r.unmatched_keys else "info"
        out.append(issue(sev, "V9_pdf_vs_xlsx", r.week_end,
                         f"{r.mismatches} of {r.cells} cells differ, {r.unmatched_keys} unmatched keys"))

    # V10 decomposition closes
    dec = decomposition(t)
    if not dec.empty:
        tot = dec.groupby(["week_end", "basket"]).agg(sum_c=("contrib_pp", "sum"),
                                                      pbs=("pbs_yoy", "first")).reset_index()
        tot["gap"] = tot["sum_c"] - tot["pbs"]
        for r in tot[tot["gap"].abs() > 0.15].itertuples():
            out.append(issue("warn", "V10_decomposition", f"{r.week_end} {r.basket}",
                             f"contributions sum to {r.sum_c:.2f}pp vs PBS YoY {r.pbs:.2f}%"))
        ok = (tot["gap"].abs() <= 0.15).mean()
        out.append(issue("info", "V10_decomposition", "all weeks",
                         f"{ok:.0%} of week-baskets close within 0.15pp; median |gap| "
                         f"{tot['gap'].abs().median():.3f}pp"))
    return out


def decomposition(t: dict) -> pd.DataFrame:
    """Item contributions (percentage points) to YoY SPI change, Q1 and combined.

    PBS publishes each item's weekly impact in % points of the previous
    week's index. Chaining 52 of them gives an exact decomposition:

        I_t - I_{t-52} = sum_k sum_i impact_{i,k} * I_{k-1} / 100
        contrib_i      = sum_k impact_{i,k} * I_{k-1} / I_{t-52}      (pp)

    The archive has gaps (weeks PBS never uploaded). For a gap, the item
    split is unknown but the *total* change is not: the first report after
    the gap states the index for the week before it ("previous week"), and
    the last report before the gap states its own index. That total is
    returned as item 0, "unattributed (missing weeks)". Windows with more
    than MAX_MISSING missing weeks are skipped.

    V10 then checks sum(items) + unattributed == PBS's published YoY. The
    two sides are computed independently (impacts vs index levels), so the
    check tests both the parse and the chaining.
    """
    si, q = t["summary_items"], t["quintiles"]
    cols = ["week_end", "item_no", "basket", "weight", "contrib_pp", "pbs_yoy", "missing_weeks"]
    if si.empty:
        return pd.DataFrame(columns=cols)
    piv_q = {c: q.pivot_table(index="week_end", columns="group", values=c)
             for c in ("spi", "spi_prev_week", "spi_year_ago", "yoy_pct")}
    weeks = sorted(set(si["week_end"]) & set(piv_q["spi"].index))
    si = si.dropna(subset=["item_no"])
    rows = []
    for basket, icol, wcol, qcol in (("q1", "impact_q1", "weight_q1", "Q1"),
                                     ("combined", "impact_combined", "weight_combined", "Combined")):
        spi, prev = piv_q["spi"][qcol], piv_q["spi_prev_week"][qcol]
        x = si[["week_end", "item_no", icol, wcol]].copy()
        x["scaled"] = x[icol] * x["week_end"].map(prev)
        piv = x.pivot_table(index="week_end", columns="item_no", values="scaled", aggfunc="first")
        wts = x.groupby("item_no")[wcol].median()
        for t_end in weeks:
            # Expected 52 price dates t, t-7, ..., t-357; holidays move a
            # collection day by a day or two, so match within +/-3 days.
            window = []
            for k in range(52):
                exp = t_end - dt.timedelta(days=7 * k)
                hit = [w for w in weeks if abs((w - exp).days) <= 3]
                if hit:
                    window.append(hit[0])
            missing = 52 - len(window)
            if missing > MAX_MISSING:
                continue
            i_ya = piv_q["spi_year_ago"][qcol].get(t_end) if qcol in piv_q["spi_year_ago"] else None
            if i_ya is None or pd.isna(i_ya):
                continue  # no published year-ago index for this week
            c = piv.loc[window].sum() / i_ya
            # From index levels only:
            #  item 0  = change over missing weeks (prev[first after gap] - spi[last before])
            #  item -1 = PBS revisions: a report's "previous week" index that
            #            differs from what the previous report published.
            unattr, revised = 0.0, 0.0
            win = sorted(window)
            for a, b in zip(win, win[1:]):
                if (b - a).days > 10:
                    unattr += prev[b] - spi[a]
                else:
                    revised += prev[b] - spi[a]
            start_gap = (win[0] - (t_end - dt.timedelta(days=357))).days > 3
            if start_gap:
                unattr += prev[win[0]] - i_ya
            else:
                revised += prev[win[0]] - i_ya
            base = {"week_end": t_end, "basket": basket,
                    "pbs_yoy": piv_q["yoy_pct"].at[t_end, qcol], "missing_weeks": missing}
            for item_no, v in c.items():
                rows.append({**base, "item_no": int(item_no), "weight": wts.get(item_no), "contrib_pp": v})
            rows.append({**base, "item_no": 0, "weight": None, "contrib_pp": 100 * unattr / i_ya})
            rows.append({**base, "item_no": -1, "weight": None, "contrib_pp": 100 * revised / i_ya})
    return pd.DataFrame(rows, columns=cols)


MAX_MISSING = 4


def write_report(t: dict, path: Path) -> None:
    iss = t["issues"]
    p = t["prices"]
    lines = [
        "# Validation report",
        "",
        f"_Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC by the pipeline. "
        "Checks are defined in `src/kitchen_inflation/validate.py`; cleaning rules in "
        "`clean.py`; both are explained in `docs/methods.md`._",
        "",
        "## Coverage",
        "",
        f"- Weeks with city prices: **{p['week_end'].nunique()}** "
        f"({p['week_end'].min()} to {p['week_end'].max()})",
        f"- Weeks with quintile data: **{t['quintiles']['week_end'].nunique()}**",
        f"- Price rows: **{len(p):,}**; NULL (reported as 0.00): "
        f"{int(p['price_avg'].isna().sum()):,}",
        f"- Parse method: " + ", ".join(f"{k}: {v:,}" for k, v in p["method"].value_counts().items()),
        f"- Source files discovered: {len(t['source_files'])}, "
        f"selected: {int(t['source_files']['selected'].sum())}",
        "",
        "## Issues by check",
        "",
        "| check | error | warn | info |",
        "|---|---:|---:|---:|",
    ]
    if not iss.empty:
        piv = iss.pivot_table(index="check", columns="severity", values="detail",
                              aggfunc="count", fill_value=0)
        for check, r in piv.iterrows():
            lines.append(f"| {check} | {r.get('error', 0)} | {r.get('warn', 0)} | {r.get('info', 0)} |")
    lines += ["", "## Details", ""]
    for check, grp in iss.groupby("check"):
        lines.append(f"### {check} ({len(grp)})")
        lines.append("")
        for r in grp.head(40).itertuples():
            lines.append(f"- **{r.severity}** `{r.subject}`: {r.detail}")
        if len(grp) > 40:
            lines.append(f"- ... {len(grp) - 40} more in `data/clean/issues.csv`")
        lines.append("")
    path.write_text("\n".join(lines))
