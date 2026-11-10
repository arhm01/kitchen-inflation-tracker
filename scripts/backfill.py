"""One-off historical backfill: download every SPI annex/summary file listed in
the catalog, smallest-and-most-useful first.

    uv run python scripts/backfill.py            # summaries, then annex PDFs
    uv run python scripts/backfill.py --all      # also duplicates and XLSX

The weekly pipeline downloads new files itself; this script only exists so the
first run on a slow connection can be split up and resumed.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from kitchen_inflation import config, fetch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)

ap = argparse.ArgumentParser()
ap.add_argument("--all", action="store_true", help="include duplicate uploads and XLSX files")
ap.add_argument("--workers", type=int, default=3)
args = ap.parse_args()

cat = pd.read_csv(config.INTERIM / "catalog.csv", dtype=str)
cat = cat[cat["kind"].isin(["annex", "summary"])]
if not args.all:
    cat = cat[cat["ext"] == "pdf"]
    # One file per (kind, hinted week): the latest upload. Files without a
    # hint are always kept, since their week is only known from the content.
    hinted = cat[cat["week_hint"].notna()].sort_values("uploaded")
    hinted = hinted.groupby(["kind", "week_hint"]).tail(1)
    cat = pd.concat([hinted, cat[cat["week_hint"].isna()]])
# Summaries first (small, give quintiles + national prices), newest first.
cat = cat.assign(_k=cat["kind"].map({"summary": 0, "annex": 1}))
cat = cat.sort_values(["_k", "week_hint"], ascending=[True, False])
jobs = [(u, config.RAW / f) for u, f in zip(cat["url"], cat["filename"])]
todo = [j for j in jobs if not j[1].exists()]
logging.info("%d files wanted, %d to download", len(jobs), len(todo))
res = fetch.download_many(todo, workers=args.workers)
bad = {u: e for u, e in res.items() if e != "ok"}
logging.info("done: %d ok, %d failed", len(res) - len(bad), len(bad))
for u, e in bad.items():
    logging.warning("FAILED %s: %s", u, e)
