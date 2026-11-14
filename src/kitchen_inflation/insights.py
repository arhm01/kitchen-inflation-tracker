"""Numbers and series for the case-study page (site/index.html).

The page's prose is hand-written, but every figure in it comes from here and
is recomputed weekly. Each qualitative claim the prose makes ("Punjab has the
cheapest atta", "the poorest basket rose least") is also re-checked here; a
claim that stops holding becomes a validation warning (S1), so the write-up
can't silently go stale.

Conventions:
* The archive effectively starts on 2023-07-06 (one isolated week from
  February 2023 survives); series and "since" figures start there.
* Changes in seasonal prices are compared as 52-week averages, never
  week-to-week endpoints (onions in July vs November is a season, not a trend).
"""

from __future__ import annotations

import re

import duckdb

from .validate import issue

START = "2023-07-06"

PROVINCE = {
    "Islamabad": "Islamabad", "Rawalpindi": "Punjab", "Gujranwala": "Punjab", "Sialkot": "Punjab",
    "Lahore": "Punjab", "Faisalabad": "Punjab", "Sargodha": "Punjab", "Multan": "Punjab",
    "Bahawalpur": "Punjab", "Karachi": "Sindh", "Hyderabad": "Sindh", "Sukkur": "Sindh",
    "Larkana": "Sindh", "Peshawar": "KP", "Bannu": "KP", "Quetta": "Balochistan",
    "Khuzdar": "Balochistan",
}


def _iso_plus(iso: str, days: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()


def _rows(con, sql: str) -> list[dict]:
    from .dashboard import _rows as rows  # same JSON-safe conversion as the dashboard
    return rows(con, sql)


def _one(con, sql: str):
    return con.execute(sql).fetchone()


def build(con: duckdb.DuckDBPyConnection) -> tuple[dict, list[dict]]:
    """Return (story payload, claim-check issues)."""
    values = ", ".join(f"('{c}', '{p}')" for c, p in PROVINCE.items())
    con.execute(f"CREATE OR REPLACE TEMP TABLE province AS SELECT * FROM (VALUES {values}) t(city, province)")
    S = {}

    latest = _one(con, "SELECT max(week_end) FROM prices")[0]
    S["meta"] = _rows(con, f"""
        SELECT max(week_end) AS latest_week, min(week_end) FILTER (WHERE week_end >= DATE '{START}') AS start_week,
               count(DISTINCT week_end) AS weeks, count(*) AS price_rows,
               count(DISTINCT city) AS cities, count(DISTINCT item_no) AS items
        FROM prices""")[0]
    S["meta"].update(_rows(con, """
        SELECT (SELECT coalesce(sum(cells), 0) FROM xlsx_check)       AS xlsx_cells,
               (SELECT coalesce(sum(mismatches), 0) FROM xlsx_check)  AS xlsx_mismatches,
               (SELECT count(*) FROM xlsx_check)                      AS xlsx_weeks,
               (SELECT count(*) FROM source_files)                    AS files_found,
               (SELECT count(*) FROM source_files WHERE selected)     AS files_used,
               (SELECT count(DISTINCT week_end) FROM yoy_contrib)     AS decomposed_weeks""")[0])

    # --- 1. cities -----------------------------------------------------------
    S["cities"] = _rows(con, "SELECT city, mean_idx, pct_weeks_dearest, median_rank FROM city_stability")
    S["twin"] = _rows(con, f"""
        WITH x AS (SELECT week_end, city, idx_weighted v FROM city_index WHERE week_end >= DATE '{START}')
        SELECT round(avg(i.v - r.v), 1) AS gap_pts, round(100 * avg((i.v > r.v)::INT)) AS pct_weeks
        FROM x i JOIN x r USING (week_end) WHERE i.city = 'Islamabad' AND r.city = 'Rawalpindi'""")[0]
    top_city = S["cities"][0]["city"]
    S["premium"] = _rows(con, f"""SELECT short_name AS item, premium_pct FROM city_item_premium
                                  WHERE city = '{top_city}' ORDER BY premium_pct DESC""")

    # --- 2. atta across provinces ---------------------------------------------
    S["atta_week"] = _rows(con, f"""
        SELECT city, province, round(price_avg) AS price FROM prices JOIN province USING (city)
        WHERE item_no = 1 AND week_end = DATE '{latest}' ORDER BY price DESC""")
    S["atta_series"] = _rows(con, f"""
        SELECT week_end AS w, province AS p, round(avg(price_avg)) AS v
        FROM prices JOIN province USING (city)
        WHERE item_no = 1 AND week_end >= DATE '{START}' GROUP BY ALL ORDER BY w, p""")
    # Weeks (in the last 52) in which Punjab was the cheapest province.
    S["atta_punjab"] = _rows(con, f"""
        WITH p AS (SELECT week_end, province, avg(price_avg) v FROM prices JOIN province USING (city)
                   WHERE item_no = 1 AND week_end > DATE '{latest}' - 364 GROUP BY ALL),
             r AS (SELECT week_end, province, rank() OVER (PARTITION BY week_end ORDER BY v) rk FROM p)
        SELECT round(100 * avg((rk = 1)::INT) FILTER (WHERE province = 'Punjab')) AS pct_cheapest_52w,
               count(DISTINCT week_end) AS weeks FROM r""")[0]

    # How much more the other four regions pay than Punjab, weekly.
    S["atta_rest_gap"] = _rows(con, f"""
        WITH p AS (SELECT week_end, province, avg(price_avg) v FROM prices JOIN province USING (city)
                   WHERE item_no = 1 AND week_end >= DATE '{START}' GROUP BY ALL)
        SELECT week_end AS w,
               round(100 * (avg(v) FILTER (WHERE province <> 'Punjab') / avg(v) FILTER (WHERE province = 'Punjab') - 1), 1) AS v
        FROM p GROUP BY 1 ORDER BY 1""")
    g = S["atta_rest_gap"]
    first = [r["v"] for r in g if r["w"] < _iso_plus(START, 364)]
    last = [r["v"] for r in g if r["w"] > _iso_plus(str(latest), -364)]
    S["atta_rest"] = {"first_year": round(sum(first) / len(first), 1), "last_52w": round(sum(last) / len(last), 1)}

    # --- 3. dispersion: one national price vs anything goes --------------------
    S["dispersion"] = _rows(con, f"""
        WITH w AS (SELECT week_end, item_no, any_value(short_name) s, max(price_avg) / min(price_avg) r
                   FROM prices WHERE week_end >= DATE '{START}' AND "group" = 'kitchen'
                   GROUP BY 1, 2 HAVING count(price_avg) = 17)
        SELECT s AS item, round(median(r), 2) AS ratio FROM w GROUP BY s ORDER BY ratio DESC""")
    S["single_market"] = _rows(con, f"""
        WITH c AS (SELECT city, avg((price_max = price_min)::INT) share FROM prices
                   WHERE week_end >= DATE '{START}' AND "group" = 'kitchen' AND price_avg IS NOT NULL GROUP BY 1)
        SELECT count(*) FILTER (WHERE share >= 0.5) AS cities_mostly_one_price,
               string_agg(city, ', ' ORDER BY share DESC) FILTER (WHERE share >= 0.5) AS which FROM c""")[0]

    # --- 4. quintiles: who inflation hit -------------------------------------
    S["quintile_index"] = _rows(con, f"""
        WITH b AS (SELECT "group", spi AS b FROM quintiles WHERE week_end = (SELECT min(week_end) FROM quintiles))
        SELECT q.week_end AS w, q."group" AS g, round(100 * q.spi / b.b, 2) AS v
        FROM quintiles q JOIN b USING ("group") WHERE q."group" IN ('Q1', 'Q5', 'Combined')
        ORDER BY w, g""")
    S["quintile_cum"] = _rows(con, """
        WITH f AS (SELECT "group", spi s0 FROM quintiles WHERE week_end = (SELECT min(week_end) FROM quintiles)),
             l AS (SELECT "group", spi s1 FROM quintiles WHERE week_end = (SELECT max(week_end) FROM quintiles))
        SELECT "group" AS g, round(100 * (s1 / s0 - 1), 1) AS pct FROM f JOIN l USING ("group") ORDER BY g""")
    S["quintile_gap"] = _rows(con, """
        SELECT round(avg(q1 - q5), 1) AS mean_gap, round(100 * avg((q1 > q5)::INT)) AS pct_q1_higher,
               round(min(q1 - q5), 1) AS min_gap, round(max(q1 - q5), 1) AS max_gap, count(*) AS weeks
        FROM quintile_yoy""")[0]
    S["gap_drivers"] = _rows(con, """
        SELECT short_name AS item, round(avg(gap_pp), 2) AS pp FROM gap_contrib
        WHERE item_no > 0 GROUP BY 1 ORDER BY pp""")
    S["weights"] = _rows(con, "SELECT item_no, w_q1, w_combined FROM weights")

    # --- 5. proteins up, staples down (52-week averages) -----------------------
    S["avg_change"] = _rows(con, f"""
        WITH a AS (SELECT item_no, short_name, item_group, price, week_end FROM item_national
                   WHERE week_end >= DATE '{START}')
        SELECT short_name AS item, item_group AS g,
               round(avg(price) FILTER (WHERE week_end < DATE '{START}' + 364), 2) AS first_year,
               round(avg(price) FILTER (WHERE week_end > DATE '{latest}' - 364), 2) AS last_year,
               round(100 * (avg(price) FILTER (WHERE week_end > DATE '{latest}' - 364)
                            / avg(price) FILTER (WHERE week_end < DATE '{START}' + 364) - 1), 1) AS pct
        FROM a GROUP BY ALL ORDER BY pct DESC""")

    # --- 6. tomatoes ------------------------------------------------------------
    S["tomato_series"] = _rows(con, f"""SELECT week_end AS w, round(price, 2) AS v FROM item_national
                                        WHERE item_no = 23 AND week_end >= DATE '{START}' ORDER BY w""")
    S["volatility"] = _rows(con, f"""
        WITH a AS (SELECT item_no, short_name, item_group, week_end, price,
                          lag(price) OVER (PARTITION BY item_no ORDER BY week_end) pp,
                          lag(week_end) OVER (PARTITION BY item_no ORDER BY week_end) pw
                   FROM item_national WHERE week_end >= DATE '{START}')
        SELECT short_name AS item, round(100 * median(abs(price / pp - 1)), 2) AS med_weekly_pct,
               round(max(price) / min(price), 2) AS max_over_min
        FROM a WHERE week_end - pw <= 10 AND item_group = 'kitchen'
        GROUP BY 1 ORDER BY med_weekly_pct DESC""")

    # --- 7. Ramadan ----------------------------------------------------------------
    S["ramadan"] = _rows(con, """SELECT year, short_name AS item, net_effect_pct AS net, chg_pct, clear
                                 FROM ramadan_effect WHERE usable AND item_group = 'kitchen'
                                 ORDER BY item, year""")
    S["ramadan_dates"] = _rows(con, "SELECT * FROM ramadan ORDER BY year")
    S["banana_series"] = _rows(con, f"""SELECT week_end AS w, round(price, 2) AS v FROM item_national
                                        WHERE item_no = 16 AND week_end >= DATE '{START}' ORDER BY w""")

    # --- 8. data-quality anecdotes ---------------------------------------------
    S["issues"] = _rows(con, """SELECT "check", severity, subject, detail FROM issues
                                WHERE "check" IN ('V4_city_outlier', 'V6_possible_unit_change',
                                                  'V11_index_revision', 'V7_missing_weeks')""")
    S["missing_weeks"] = _one(con, """SELECT coalesce(sum(regexp_extract(detail, '(\\d+) week', 1)::INT), 0)
                                      FROM issues WHERE "check" = 'V7_missing_weeks'""")[0]

    return S, check_claims(S)


def check_claims(S: dict) -> list[dict]:
    """S1: the qualitative statements in the write-up, re-tested weekly."""
    by = {r["g"]: r["pct"] for r in S["quintile_cum"]}
    avg = {r["item"]: r["pct"] for r in S["avg_change"]}
    disp = {r["item"]: r["ratio"] for r in S["dispersion"]}
    ram = {}
    for r in S["ramadan"]:
        ram.setdefault(r["item"], []).append(r)
    claims = {
        "Islamabad is the dearest city on average": S["cities"][0]["city"] == "Islamabad",
        "Islamabad is dearer than Rawalpindi in most weeks": S["twin"]["pct_weeks"] >= 75,
        "Punjab has the cheapest atta in most of the last 52 weeks": (S["atta_punjab"]["pct_cheapest_52w"] or 0) >= 75,
        "Atta outside Punjab costs more than three times as much extra in the last 52 weeks as in the first year":
            S["atta_rest"]["last_52w"] > 3 * max(S["atta_rest"]["first_year"], 0.1),
        "Since July 2023 the poorest quintile's SPI rose less than the richest's": by.get("Q1", 0) < by.get("Q5", 0),
        "Beef, mutton and powdered milk rose more than atta, rice and masoor (52-week averages)":
            min(avg.get(k, 0) for k in ("Beef", "Mutton", "Powdered milk"))
            > max(avg.get(k, 0) for k in ("Wheat flour (20kg)", "Rice basmati", "Pulse masoor")),
        "Branded packaged goods vary across cities far less than fresh produce":
            max(disp.get(k, 9) for k in ("Cooking oil (5L)", "Ghee (1kg)", "Tea (packet)"))
            < min(disp.get(k, 0) for k in ("Bananas (dozen)", "Tomatoes", "Potatoes")),
        "Tomatoes are the most volatile kitchen item week to week": S["volatility"][0]["item"] == "Tomatoes",
        "Bananas rose clearly in every Ramadan in the archive":
            bool(ram.get("Bananas (dozen)")) and all(r["clear"] and r["net"] > 0 for r in ram["Bananas (dozen)"]),
    }
    S["claims"] = [{"claim": k, "holds": bool(v)} for k, v in claims.items()]
    return [issue("warn", "S1_story_claim", "site/index.html", f"no longer holds: {k}")
            for k, v in claims.items() if not v]


# --- explorer data (compact, for an inline page) --------------------------------

PROV_ORDER = ["Punjab", "Sindh", "KP", "Balochistan", "Islamabad"]


def _r(v):
    """Round for the page: integers above 100, one decimal below."""
    if v is None:
        return None
    return round(v) if abs(v) >= 100 else round(v, 1)


def explorer(con) -> dict:
    """Province-average price per item per week, plus each item's 17 city
    prices in the latest week. Province average = mean of its cities'
    average prices (Islamabad is a single city)."""
    weeks = [r[0].isoformat() for r in con.execute(
        f"SELECT DISTINCT week_end FROM prices WHERE week_end >= DATE '{START}' ORDER BY 1").fetchall()]
    idx = {w: i for i, w in enumerate(weeks)}
    items = _rows(con, """SELECT item_no AS no, any_value(short_name) AS name, any_value("group") AS g,
                                 arg_max(unit, week_end) AS unit
                          FROM prices GROUP BY 1 ORDER BY 1""")
    prov = {str(it["no"]): {p: [None] * len(weeks) for p in PROV_ORDER} for it in items}
    for no, p, w, v in con.execute(f"""
            SELECT item_no, province, week_end, avg(price_avg) FROM prices JOIN province USING (city)
            WHERE week_end >= DATE '{START}' GROUP BY ALL""").fetchall():
        prov[str(no)][p][idx[w.isoformat()]] = _r(v)
    latest = {}
    for no, city, p, v in con.execute("""
            SELECT item_no, city, province, price_avg FROM prices JOIN province USING (city)
            WHERE week_end = (SELECT max(week_end) FROM prices) ORDER BY item_no, price_avg DESC NULLS LAST""").fetchall():
        latest.setdefault(str(no), []).append([city, p, _r(v)])
    return {"weeks": weeks, "items": items, "provinces": PROV_ORDER, "prov": prov, "latest": latest}


# --- formatted figures for the prose ------------------------------------------------

def _d(iso: str) -> str:
    import datetime as dt
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def _n(v, d=0) -> str:
    return f"{v:,.{d}f}"


PROSE_NAME = {
    "Wheat flour (20kg)": "atta", "Bananas (dozen)": "bananas", "Eggs (dozen)": "eggs",
    "Firewood (40kg)": "firewood", "Electricity (Q1)": "lowest-slab electricity",
    "Gas (Q1)": "lowest-slab gas", "Tea (packet)": "packet tea", "Cooking oil (5L)": "cooking oil",
}


def pn(name: str) -> str:
    """Item name as it reads mid-sentence: 'Bananas (dozen)' -> 'bananas'."""
    if name in PROSE_NAME:
        return PROSE_NAME[name]
    return re.sub(r"\s*\([^)]*\)", "", name).lower()


def facts(S: dict) -> dict:
    """Every number the hand-written prose uses, formatted. Template
    placeholders are {{key}}; a missing key fails the build loudly."""
    m = S["meta"]
    cities = S["cities"]
    atta = S["atta_week"]
    hi, lo = atta[0], atta[-1]
    q = {r["g"]: r["pct"] for r in S["quintile_cum"]}
    qmax = max((r for r in S["quintile_cum"] if r["g"].startswith("Q")), key=lambda r: r["pct"])
    avg = {r["item"]: r for r in S["avg_change"]}
    disp = {r["item"]: r["ratio"] for r in S["dispersion"]}
    vol = {r["item"]: r for r in S["volatility"]}
    drivers = S["gap_drivers"]
    tom = S["tomato_series"]
    tmin = min(tom, key=lambda r: r["v"])
    tmax = max(tom, key=lambda r: r["v"])
    ram = {}
    for r in S["ramadan"]:
        ram.setdefault(r["item"], []).append(r)
    years = sorted({r["year"] for r in S["ramadan"]})
    full = {k: v for k, v in ram.items() if len(v) == len(years)}
    quiet = sum(all(not r["clear"] for r in v) for v in full.values())
    w = {r["item_no"]: r for r in S["weights"]}
    branded = max(disp[k] for k in ("Cooking oil (5L)", "Ghee (1kg)", "Ghee (2.5kg)", "Tea (packet)"))
    prem = [r for r in S["premium"] if r["premium_pct"] > 0][:3]
    signed = lambda v, d=0: ("+" if v > 0 else "−" if v < 0 else "") + _n(abs(v), d)  # noqa: E731
    F = {
        "latest_week": _d(m["latest_week"]), "start_month": "July 2023", "weeks": str(m["weeks"]),
        "price_rows": _n(m["price_rows"]), "files_used": str(m["files_used"]), "files_found": str(m["files_found"]),
        "xlsx_cells": _n(m["xlsx_cells"]), "xlsx_weeks": str(m["xlsx_weeks"]),
        "xlsx_mismatches": _n(m["xlsx_mismatches"]), "missing_weeks": str(S["missing_weeks"]),
        "decomposed_weeks": str(m["decomposed_weeks"]),
        # atta
        "atta_hi_city": hi["city"], "atta_hi_price": _n(hi["price"]),
        "atta_lo_city": lo["city"], "atta_lo_price": _n(lo["price"]),
        "atta_gap_pct": _n(100 * (hi["price"] / lo["price"] - 1)),
        "atta_gap_rs": _n(hi["price"] - lo["price"]),
        "punjab_cheapest_pct": _n(S["atta_punjab"]["pct_cheapest_52w"] or 0),
        "atta_rest_y1": _n(S["atta_rest"]["first_year"], 0), "atta_rest_52w": _n(S["atta_rest"]["last_52w"], 0),
        "atta_w_q1": _n(w[1]["w_q1"], 1), "atta_w_comb": _n(w[1]["w_combined"], 1),
        # cities
        "top_city": cities[0]["city"], "top_city_pct": _n(cities[0]["mean_idx"] - 100, 1),
        "top_city_weeks": _n(cities[0]["pct_weeks_dearest"]),
        "bottom_city": cities[-1]["city"], "bottom_city_pct": _n(100 - cities[-1]["mean_idx"], 1),
        "twin_gap": _n(S["twin"]["gap_pts"], 1), "twin_pct": _n(S["twin"]["pct_weeks"]),
        "prem_1": pn(prem[0]["item"]), "prem_1_pct": _n(prem[0]["premium_pct"]),
        "prem_2": pn(prem[1]["item"]), "prem_2_pct": _n(prem[1]["premium_pct"]),
        "prem_3": pn(prem[2]["item"]), "prem_3_pct": _n(prem[2]["premium_pct"]),
        "single_market_n": str(S["single_market"]["cities_mostly_one_price"]),
        # dispersion
        "banana_ratio": _n(disp["Bananas (dozen)"], 1), "tomato_ratio": _n(disp["Tomatoes"], 1),
        "branded_pct": _n(100 * (branded - 1)),
        # quintiles
        "q1_cum": _n(q["Q1"], 1), "q5_cum": _n(q["Q5"], 1), "comb_cum": _n(q["Combined"], 1),
        "qmax_name": qmax["g"], "qmax_cum": _n(qmax["pct"], 1),
        "gap_mean": signed(S["quintile_gap"]["mean_gap"], 1), "gap_pct_higher": _n(S["quintile_gap"]["pct_q1_higher"]),
        "gap_min": signed(S["quintile_gap"]["min_gap"], 1), "gap_max": signed(S["quintile_gap"]["max_gap"], 1),
        "drv_down_1": pn(drivers[0]["item"]), "drv_down_2": pn(drivers[1]["item"]),
        "drv_down_3": pn(drivers[2]["item"]),
        "drv_up_1": pn(drivers[-1]["item"]), "drv_up_2": pn(drivers[-2]["item"]),
        "drv_up_3": pn(drivers[-3]["item"]),
        "petrol_w_q1": _n(w[47]["w_q1"], 1), "petrol_w_comb": _n(w[47]["w_combined"], 1),
        "elec_w_q1": _n(w[41]["w_q1"], 1), "elec_w_comb": _n(w[41]["w_combined"], 1),
        # staples vs proteins
        "beef_chg": signed(avg["Beef"]["pct"]), "milkp_chg": signed(avg["Powdered milk"]["pct"]),
        "mutton_chg": signed(avg["Mutton"]["pct"]), "atta_chg": signed(avg["Wheat flour (20kg)"]["pct"]),
        "masoor_chg": signed(avg["Pulse masoor"]["pct"]), "potato_chg": signed(avg["Potatoes"]["pct"]),
        "rice_chg": signed(avg["Rice basmati"]["pct"]),
        # tomatoes
        "tom_weekly": _n(vol["Tomatoes"]["med_weekly_pct"], 1), "tom_ratio": _n(vol["Tomatoes"]["max_over_min"], 1),
        "tom_min": _n(tmin["v"]), "tom_min_date": _d(tmin["w"]), "tom_max": _n(tmax["v"]), "tom_max_date": _d(tmax["w"]),
        "onion_weekly": _n(vol["Onions"]["med_weekly_pct"], 1), "atta_weekly": _n(vol["Wheat flour (20kg)"]["med_weekly_pct"], 1),
        # ramadan
        "ram_years": ", ".join(map(str, years[:-1])) + f" and {years[-1]}" if len(years) > 1 else str(years[0]),
        "ram_n": str(len(years)),
        "banana_nets": " / ".join(signed(r["net"]) for r in sorted(ram.get("Bananas (dozen)", []), key=lambda r: r["year"])),
        "potato_nets": " / ".join(signed(r["net"]) for r in sorted(ram.get("Potatoes", []), key=lambda r: r["year"])),
        "ram_quiet": str(quiet), "ram_full": str(len(full)),
    }
    return F
