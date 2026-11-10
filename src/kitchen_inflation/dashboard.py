"""Build the static dashboard in ``site/`` from the DuckDB views.

The page is a single self-contained HTML file: the data is inlined as JSON
and the charts are drawn with plain SVG, so it works from GitHub Pages, from
a local file, and offline. Small CSV extracts are written next to it for
download.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import shutil
from importlib import resources

import duckdb

from . import config

log = logging.getLogger(__name__)


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    df = con.execute(sql).df()
    out = []
    for rec in df.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if isinstance(v, (dt.date, dt.datetime)):
                v = v.isoformat()[:10]
            elif hasattr(v, "isoformat"):
                v = str(v)[:10]
            elif isinstance(v, float) and math.isnan(v):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            clean[k] = v
        out.append(clean)
    return out


def payload(con: duckdb.DuckDBPyConnection) -> dict:
    q = lambda s: _rows(con, s)  # noqa: E731
    meta = q("""
        SELECT (SELECT max(week_end) FROM prices)    AS latest_week,
               (SELECT min(week_end) FROM prices)    AS first_week,
               (SELECT count(DISTINCT week_end) FROM prices)    AS price_weeks,
               (SELECT count(DISTINCT week_end) FROM quintiles) AS quintile_weeks,
               (SELECT count(*) FROM source_files)   AS files_found,
               (SELECT count(*) FROM source_files WHERE selected) AS files_used,
               (SELECT count(*) FROM prices)         AS price_rows
    """)[0]
    meta["generated"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "meta": meta,
        "city_index": q("""SELECT week_end AS w, city AS c, round(idx_weighted, 2) AS v, rank_dear AS r
                           FROM city_rank ORDER BY week_end, city"""),
        "city_stability": q("SELECT * FROM city_stability"),
        "city_premium": q("""SELECT city, short_name, premium_pct FROM city_item_premium
                             ORDER BY city, premium_pct DESC"""),
        "quintiles": q("""SELECT week_end AS w, q1, q2, q3, q4, q5, combined FROM quintile_yoy
                          ORDER BY week_end"""),
        "gap": q("""SELECT week_end AS w, short_name AS item, round(q1_pp, 3) AS q1,
                           round(combined_pp, 3) AS comb, round(gap_pp, 3) AS gap
                    FROM gap_contrib ORDER BY week_end, item"""),
        "weights": q("""SELECT w.item_no, i.short_name AS item, w_q1, w_combined
                        FROM weights w JOIN (SELECT item_no, any_value(short_name) AS short_name
                                             FROM items GROUP BY 1) i USING (item_no)
                        ORDER BY item_no"""),
        "ramadan": q("""SELECT year, item_no, short_name AS item, item_group AS g, chg_pct, runup_pct,
                               peak_pct, spi_chg_pct, typical_pct, typical_iqr_pp AS iqr, net_effect_pct AS net, clear, n_base, n_ramadan
                        FROM ramadan_effect WHERE usable ORDER BY item_no, year"""),
        "ramadan_dates": q("SELECT * FROM ramadan ORDER BY year"),
        "quality": q("""SELECT "check", severity, count(*) AS n FROM issues
                        GROUP BY ALL ORDER BY "check", severity"""),
        "xlsx_check": q("""SELECT count(*) AS weeks, coalesce(sum(cells), 0) AS cells,
                                  coalesce(sum(mismatches), 0) AS mismatches FROM xlsx_check""")[0],
    }


def build(con: duckdb.DuckDBPyConnection) -> None:
    site = config.SITE
    site.mkdir(parents=True, exist_ok=True)
    data = payload(con)
    template = resources.files("kitchen_inflation").joinpath("templates/index.html").read_text()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    (site / "index.html").write_text(template.replace("/*__DATA__*/null", blob))

    # Downloadable extracts (the full price table lives in the repo's data/clean).
    dl = site / "data"
    dl.mkdir(exist_ok=True)
    for name, sql in {
        "city_index": "SELECT * FROM city_rank ORDER BY week_end, city",
        "quintile_yoy": "SELECT * FROM quintile_yoy",
        "ramadan_effect": "SELECT * FROM ramadan_effect ORDER BY year, item_no",
        "gap_contrib": "SELECT * FROM gap_contrib ORDER BY week_end, item_no",
    }.items():
        con.execute(f"COPY ({sql}) TO '{(dl / (name + '.csv')).as_posix()}' (HEADER)")
    for src in (config.ROOT / "docs" / "methods.md", config.REPORTS / "validation.md"):
        if src.exists():
            shutil.copy(src, site / src.name)
    log.info("dashboard written to %s (%d KB)", site / "index.html",
             (site / "index.html").stat().st_size // 1024)
