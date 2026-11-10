"""Turn per-file parse output into tidy tables, applying (and logging) every
cleaning rule. Rules are numbered; docs/methods.md explains each one.

C1  Zero prices mean "not collected in this city" (e.g. IRRI rice in
    Gujranwala); they become NULL, never 0.
C2  Item identity is the SPI serial number (1-51), which PBS has kept fixed
    for the 2015-16 basket. Descriptions are kept per week as published.
C3  Item *specification* (description + unit) is normalised and versioned.
    A new version starts whenever the normalised spec text changes; whether
    it is a real unit change is decided in validation (price jump test).
C4  Summary item rows are linked to item numbers by matching their price to
    the annex national average of the same week (exact to the paisa), with a
    fuzzy-name fallback.
C5  Where several cities' prices are 0 for an item in a week, the city
    comparison simply drops that item for that week (see sql/views.sql,
    kitchen_complete); nothing is imputed.
"""

from __future__ import annotations

import difflib
import re

import numpy as np
import pandas as pd

from . import config, validate

CLEAN = config.DATA / "clean"


# C3a: label aliases. PBS alternates between these wordings week to week at
# an unchanged price, so they are the same specification, not a unit change.
SPEC_ALIASES = [
    (r"gas charges upto 3\.3719 mmbtu", "gas charges for q1"),
]


def norm_spec(name: str, unit: str) -> str:
    s = f"{name} | {unit}".lower()
    s = re.sub(r"[^a-z0-9.|/ ]+", " ", s)
    s = re.sub(r"\b(per minut)\b", "per minute", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in SPEC_ALIASES:
        s = re.sub(pat, rep, s)
    return s


def build_tables(catalog: pd.DataFrame, chosen: dict, parsed: dict) -> tuple[dict, list]:
    issues: list[dict] = []
    fname = dict(zip(catalog["url"], catalog["filename"]))

    # --- prices (annex PDFs) ------------------------------------------------
    frames, nat_frames = [], []
    for (kind, week), url in chosen.items():
        if kind != "annex":
            continue
        p = parsed[url]
        df = pd.DataFrame(p["rows"])
        if df.empty:
            issues.append(validate.issue("error", "empty_parse", fname[url], f"no rows for {week}"))
            continue
        df["week_end"] = week
        df["source_file"] = fname[url]
        frames.append(df)
        for w in p.get("warnings", []):
            issues.append(validate.issue("warn", "parser_warning", fname[url], w))
        if p.get("national"):
            nd = pd.DataFrame(p["national"])
            nd["week_end"] = week
            nat_frames.append(nd)
    prices = pd.concat(frames, ignore_index=True)
    prices["week_end"] = pd.to_datetime(prices["week_end"]).dt.date

    # C1: zeros -> NULL
    for col in ("price_min", "price_avg", "price_max"):
        z = prices[col] == 0
        prices.loc[z, col] = np.nan
    n_missing = int(prices["price_avg"].isna().sum())
    issues.append(validate.issue("info", "zero_as_missing", "prices",
                                 f"{n_missing} city-item-weeks reported as 0.00 -> NULL (C1)"))

    # C3: spec versions per item
    prices["spec"] = [norm_spec(n, u) for n, u in zip(prices["item_name"], prices["unit"])]
    prices = prices.sort_values(["item_no", "week_end", "city_code"]).reset_index(drop=True)
    spec_week = (prices.groupby(["item_no", "week_end"])["spec"]
                 .agg(lambda s: s.mode().iat[0]).reset_index())
    spec_week["spec_version"] = spec_week.groupby("item_no")["spec"].transform(
        lambda s: (s != s.shift()).cumsum())
    prices = prices.drop(columns="spec").merge(spec_week, on=["item_no", "week_end"])

    items = (prices.groupby(["item_no", "spec_version"])
             .agg(item_name=("item_name", lambda s: s.mode().iat[0]),
                  unit=("unit", lambda s: s.mode().iat[0]),
                  spec=("spec", "first"),
                  first_week=("week_end", "min"), last_week=("week_end", "max"),
                  weeks=("week_end", "nunique"))
             .reset_index())
    latest = items.sort_values("last_week").groupby("item_no").tail(1)
    short = {r.item_no: short_name(r.item_name) for r in latest.itertuples()}
    items["short_name"] = items["item_no"].map(short)
    items["group"] = items["item_no"].map(item_group)
    prices["short_name"] = prices["item_no"].map(short)
    prices["group"] = prices["item_no"].map(item_group)

    national = (pd.concat(nat_frames, ignore_index=True) if nat_frames else pd.DataFrame())
    if not national.empty:
        national["week_end"] = pd.to_datetime(national["week_end"]).dt.date

    # --- summary tables --------------------------------------------------------
    q_frames, si_frames = [], []
    for (kind, week), url in chosen.items():
        if kind != "summary":
            continue
        p = parsed[url]
        for w in p.get("warnings", []):
            issues.append(validate.issue("warn", "parser_warning", fname[url], w))
        if p.get("quintiles"):
            q = pd.DataFrame(p["quintiles"]); q["week_end"] = week; q["source_file"] = fname[url]
            q_frames.append(q)
        if p.get("items"):
            s = pd.DataFrame(p["items"]); s["week_end"] = week; s["source_file"] = fname[url]
            si_frames.append(s)
    quintiles = pd.concat(q_frames, ignore_index=True)
    quintiles["week_end"] = pd.to_datetime(quintiles["week_end"]).dt.date
    summary_items = pd.concat(si_frames, ignore_index=True)
    summary_items["week_end"] = pd.to_datetime(summary_items["week_end"]).dt.date
    summary_items = link_summary_items(summary_items, national, items, issues)

    # --- PDF vs XLSX reference -------------------------------------------------
    xcheck = []
    for (kind, week), url in chosen.items():
        if kind != "annex_xlsx" or ("annex", week) not in chosen:
            continue
        x = pd.DataFrame(parsed[url]["rows"])
        pdf = pd.DataFrame(parsed[chosen[("annex", week)]]["rows"])
        m = pdf.merge(x, on=["item_no", "city_code"], suffixes=("_pdf", "_xlsx"), how="outer",
                      indicator=True)
        n_cmp = 0; n_bad = 0
        for col in ("price_min", "price_avg", "price_max"):
            a, b = m[f"{col}_pdf"].fillna(0), m[f"{col}_xlsx"].fillna(0)
            n_cmp += len(m); n_bad += int(((a - b).abs() > 0.006).sum())
        xcheck.append({"week_end": week, "cells": n_cmp, "mismatches": n_bad,
                       "unmatched_keys": int((m["_merge"] != "both").sum()),
                       "pdf_file": fname[chosen[("annex", week)]], "xlsx_file": fname[url]})
    xcheck = pd.DataFrame(xcheck, columns=["week_end", "cells", "mismatches", "unmatched_keys",
                                           "pdf_file", "xlsx_file"])

    source_files = catalog[["filename", "kind", "ext", "uploaded", "week_hint", "hint_rule",
                            "content_week", "status", "selected", "found_via", "url"]]

    cols = ["week_end", "item_no", "short_name", "group", "spec_version", "item_name", "unit",
            "city", "city_code", "price_min", "price_avg", "price_max", "method", "source_file"]
    tables = {
        # Sorted by week so each weekly run appends lines (small git diffs).
        "prices": prices[cols].sort_values(["week_end", "item_no", "city_code"]),
        "items": items,
        "national": national,
        "quintiles": quintiles,
        "summary_items": summary_items,
        "xlsx_check": xcheck,
        "source_files": source_files,
    }
    return tables, issues


# --- item helpers --------------------------------------------------------------

# Items 1-29 are groceries, 30-32 food bought ready-made, 33-51 non-food.
# The "kitchen basket" used for the city comparison is 1-29.
def item_group(item_no: int) -> str:
    if item_no <= 29:
        return "kitchen"
    if item_no <= 32:
        return "prepared_food"
    return "non_food"


SHORT = [
    (r"wheat flour", "Wheat flour (20kg)"), (r"basmati", "Rice basmati"), (r"irri", "Rice IRRI"),
    (r"bread", "Bread"), (r"^beef", "Beef"), (r"mutton", "Mutton"), (r"chicken", "Chicken"),
    (r"milk fresh", "Milk"), (r"curd", "Curd"), (r"powdered milk", "Powdered milk"),
    (r"eggs", "Eggs (dozen)"), (r"mustard", "Mustard oil"), (r"cooking oil", "Cooking oil (5L)"),
    (r"ghee.*2\.5", "Ghee (2.5kg)"), (r"ghee", "Ghee (1kg)"), (r"banana", "Bananas (dozen)"),
    (r"masoor", "Pulse masoor"), (r"moong", "Pulse moong"), (r"mash", "Pulse mash"),
    (r"pulse gram", "Pulse gram"), (r"potato", "Potatoes"), (r"onion", "Onions"),
    (r"tomato", "Tomatoes"), (r"sugar", "Sugar"), (r"^gur", "Gur"), (r"salt", "Salt"),
    (r"chil", "Chilli powder"), (r"garlic", "Garlic"), (r"tea lipton", "Tea (packet)"),
    (r"cooked beef", "Cooked beef (plate)"), (r"cooked daal", "Cooked daal (plate)"),
    (r"tea prepared", "Tea (cup)"), (r"cigarette", "Cigarettes"), (r"long cloth", "Long cloth"),
    (r"shirting", "Shirting"), (r"lawn", "Lawn"), (r"georgette", "Georgette"),
    (r"gents sandal", "Gents sandal"), (r"chappal", "Gents chappal"),
    (r"ladies sandal", "Ladies sandal"), (r"electricity", "Electricity (Q1)"),
    (r"gas", "Gas (Q1)"), (r"firewood", "Firewood (40kg)"), (r"energy saver", "Energy saver"),
    (r"washing soap", "Washing soap"), (r"match", "Matchbox"), (r"petrol", "Petrol"),
    (r"diesel", "Diesel"), (r"lpg", "LPG cylinder"), (r"telephone", "Phone call"),
    (r"toilet soap", "Toilet soap"),
]


def short_name(name: str) -> str:
    n = name.lower()
    for pat, label in SHORT:
        if re.search(pat, n):
            return label
    return name[:30]


def link_summary_items(si: pd.DataFrame, national: pd.DataFrame, items: pd.DataFrame,
                       issues: list) -> pd.DataFrame:
    """C4: attach item_no to each summary row."""
    names = items.sort_values("last_week").groupby("item_no").tail(1)
    name_map = {norm_spec(r.item_name, ""): r.item_no for r in names.itertuples()}
    out = []
    nat = national.set_index(["week_end", "item_no"])["nat_avg"] if not national.empty else None
    by_week = national.groupby("week_end") if not national.empty else {}
    for week, grp in si.groupby("week_end"):
        cand = by_week.get_group(week) if (not national.empty and week in by_week.groups) else None
        used = set()
        for r in grp.itertuples():
            item_no, how = None, None
            if cand is not None:
                hit = cand[(cand["nat_avg"] - r.price).abs() < 0.011]
                hit = hit[~hit["item_no"].isin(used)]
                if len(hit) == 1:
                    item_no, how = int(hit["item_no"].iat[0]), "price"
            if item_no is None:
                key = norm_spec(r.item_name, "")
                best = difflib.get_close_matches(key, list(name_map), n=1, cutoff=0.6)
                if best:
                    item_no, how = int(name_map[best[0]]), "name"
            if item_no is None:
                issues.append(validate.issue("warn", "summary_item_unlinked", str(week), r.item_name))
            used.add(item_no)
            d = r._asdict(); d.pop("Index"); d["item_no"] = item_no; d["link"] = how
            out.append(d)
    df = pd.DataFrame(out)
    n_name = int((df["link"] == "name").sum())
    issues.append(validate.issue("info", "summary_link", "summary_items",
                                 f"{int((df['link'] == 'price').sum())} rows linked by price, "
                                 f"{n_name} by name (C4)"))
    return df


def write_tables(tables: dict) -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(CLEAN / f"{name}.csv", index=False)
