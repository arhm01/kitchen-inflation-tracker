"""Load the cleaned CSVs into DuckDB and build the analysis views.

The CSVs in ``data/clean`` are the durable, diff-able record committed to git;
the DuckDB file is a disposable build artefact rebuilt from them every run.
"""

from __future__ import annotations

import logging

import duckdb

from . import config

log = logging.getLogger(__name__)

CLEAN = config.DATA / "clean"
DATE_COLS = {"week_end", "first_week", "last_week", "uploaded", "week_hint", "content_week"}
NUMERIC_COLS = {"weight", "contrib_pp", "pbs_yoy", "price", "price_min", "price_avg", "price_max",
                "nat_min", "nat_avg", "nat_max", "spi", "spi_prev_week", "spi_year_ago",
                "wow_pct", "yoy_pct", "weight_q1", "weight_combined", "impact_q1", "impact_combined",
                "cells", "mismatches", "unmatched_keys", "missing_weeks"}


def build() -> duckdb.DuckDBPyConnection:
    config.DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(config.DB_PATH))
    for csv in sorted(CLEAN.glob("*.csv")):
        header = csv.open().readline().strip().split(",")
        types = {c: "DATE" for c in header if c in DATE_COLS}
        # Pin numeric columns so an empty table (e.g. no complete 52-week
        # window yet) still has the right types for the views.
        types |= {c: "DOUBLE" for c in header if c in NUMERIC_COLS}
        con.execute(
            f"CREATE OR REPLACE TABLE {csv.stem} AS "
            # Explicit quote/escape: item names contain inches marks
            # ('Long Cloth 57" Gul Ahmed'), which pandas writes as "" and
            # DuckDB's sniffer otherwise misreads.
            f"SELECT * FROM read_csv('{csv.as_posix()}', header=true, auto_detect=true, "
            f"quote='\"', escape='\"', types={types!r})"
        )
        log.info("duckdb %-14s %7d rows", csv.stem, con.execute(f"SELECT count(*) FROM {csv.stem}").fetchone()[0])
    con.execute((config.ROOT / "sql" / "views.sql").read_text())
    return con
