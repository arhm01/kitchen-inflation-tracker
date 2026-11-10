"""Orchestrates: discover -> download -> parse -> consolidate -> clean/validate
-> load -> dashboard.

Every stage writes its output to disk so a failed run can be inspected and a
re-run only redoes what changed:

    data/raw/                  original PBS files (cached, never modified)
    data/interim/catalog.csv   every SPI file ever discovered + its status
    data/interim/parsed/*.json parse output per source file (cache)
    data/clean/*.csv           tidy tables committed to git
    data/spi.duckdb            rebuilt from data/clean each run
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from . import clean, config, discover, fetch, load, validate
from .parse_annex import parse_annex
from .parse_summary import parse_summary
from .parse_xlsx import parse_xlsx

log = logging.getLogger(__name__)

PARSER_VERSION = "4"  # bump to invalidate the parse cache after parser changes
PARSED = config.INTERIM / "parsed"
CATALOG = config.INTERIM / "catalog.csv"


# --- 1. discover -------------------------------------------------------------

def discover_files(full_scan: bool) -> pd.DataFrame:
    """Crawl, then merge with the stored catalog so that a file seen once is
    never forgotten (WordPress listings can change)."""
    first_run = not CATALOG.exists()
    new = discover.crawl(full_media_scan=full_scan or first_run)
    if not first_run:
        old = pd.read_csv(CATALOG, dtype=str)
        new = pd.concat([old, new.astype(str)], ignore_index=True)
        new = new.drop_duplicates("url", keep="first")
    new = new.replace({"nan": None, "None": None})
    return new.reset_index(drop=True)


# --- 2/3. download + parse ---------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _cache_path(path: Path) -> Path:
    return PARSED / f"{path.name}.v{PARSER_VERSION}.json"


def parse_file(kind: str, path: Path) -> dict:
    cp = _cache_path(path)
    if cp.exists():
        return json.loads(cp.read_text())
    out: dict = {"sha": _sha(path), "kind": kind, "file": path.name}
    try:
        if kind == "annex" and path.suffix.lower() == ".pdf":
            r = parse_annex(path)
            out.update(week_end=r.week_end and r.week_end.isoformat(),
                       rows=[asdict(x) for x in r.rows], national=r.national,
                       warnings=r.warnings, pages=r.pages_used)
        elif kind == "annex" and path.suffix.lower() == ".xlsx":
            week, rows = parse_xlsx(path)
            out.update(week_end=week and week.isoformat(), rows=[asdict(x) for x in rows], warnings=[])
        elif kind == "summary":
            r = parse_summary(path)
            out.update(week_end=r.week_end and r.week_end.isoformat(),
                       quintiles=r.quintiles, items=r.items, warnings=r.warnings)
        else:
            return out
    except Exception as exc:  # recorded, surfaced by validation
        out.update(week_end=None, error=f"{type(exc).__name__}: {exc}")
    PARSED.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(out))
    return out


def download_and_parse(catalog: pd.DataFrame, offline: bool = False
                       ) -> tuple[pd.DataFrame, dict[str, dict]]:
    wanted = catalog[
        (catalog["kind"].isin(["annex", "summary"]))
        & (catalog["ext"].isin(["pdf", "xlsx"]))
        & ~((catalog["kind"] == "summary") & (catalog["ext"] != "pdf"))
    ]
    parsed: dict[str, dict] = {}
    status = {}
    # Fetch everything missing up front with a small worker pool. A weekly
    # run only has a couple of new files; a cold cache (first CI run, or a
    # lost cache) has ~450, and the PBS server serves one connection slowly.
    if not offline:
        todo = [(u, config.RAW / f) for u, f in zip(wanted["url"], wanted["filename"])
                if not (config.RAW / f).exists()]
        if todo:
            log.info("downloading %d new files", len(todo))
            for url, err in fetch.download_many(todo, workers=3).items():
                if err != "ok":
                    status[url] = f"download_failed: {err}"
                    log.warning("download failed %s: %s", url.rsplit("/", 1)[-1], err)
    for _, row in wanted.iterrows():
        dest = config.RAW / row["filename"]
        if row["url"] in status:  # download failed above
            continue
        if not dest.exists():
            status[row["url"]] = "not_downloaded"
            continue
        res = parse_file(row["kind"], dest)
        parsed[row["url"]] = res
        if res.get("error"):
            status[row["url"]] = "error"
        elif not (res.get("rows") or res.get("quintiles")):
            # Named like an annex/summary but holds no SPI table (e.g. a trade
            # report called "Annexures-.pdf"). Content decides, not the name.
            status[row["url"]] = "not_spi"
        else:
            status[row["url"]] = "parsed"
    catalog = catalog.copy()
    catalog["status"] = catalog["url"].map(status).fillna("skipped")
    catalog["content_week"] = catalog["url"].map(lambda u: parsed.get(u, {}).get("week_end"))
    catalog["sha"] = catalog["url"].map(lambda u: parsed.get(u, {}).get("sha"))
    return catalog, parsed


# --- 4. consolidate: one annex + one summary per week ------------------------

def consolidate(catalog: pd.DataFrame, parsed: dict[str, dict]) -> dict:
    """Pick one source file per week and kind.

    * The week comes from the PDF content ("PRICES ON ..." / "WEEK ENDED ON"),
      not the file name. Where the content has no readable date we fall back
      to the filename hint and log it.
    * Several files for the same week happen (re-uploads named "-1", "_0",
      corrections). Byte-identical or value-identical copies are collapsed.
      If the values differ, the most recently uploaded file wins (PBS
      corrections are re-uploads) and the conflict is logged.
    """
    issues: list[dict] = []
    chosen: dict[tuple[str, str], str] = {}
    cat = catalog.copy()
    cat["week"] = cat["content_week"].fillna(cat["week_hint"])
    for _, r in cat[cat["content_week"].isna() & (cat["status"] == "parsed")].iterrows():
        issues.append(validate.issue("info", "date_from_filename", r["filename"],
                                     f"no date found inside file; using filename hint {r['week_hint']}"))
    mism = cat[cat["content_week"].notna() & cat["week_hint"].notna()
               & (cat["content_week"] != cat["week_hint"])]
    for _, r in mism.iterrows():
        issues.append(validate.issue("info", "filename_date_mismatch", r["filename"],
                                     f"name says {r['week_hint']}, content says {r['content_week']}"))

    for kind, ext in (("annex", "pdf"), ("summary", "pdf"), ("annex", "xlsx")):
        sub = cat[(cat["kind"] == kind) & (cat["ext"] == ext) & (cat["status"] == "parsed")
                  & cat["week"].notna()]
        for week, grp in sub.groupby("week"):
            grp = grp.sort_values("uploaded", na_position="first")
            pick = grp.iloc[-1]
            if len(grp) > 1:
                sigs = {json.dumps(parsed[u].get("rows") or parsed[u].get("quintiles"), sort_keys=True)
                        for u in grp["url"]}
                if len(sigs) > 1:
                    issues.append(validate.issue(
                        "warn", "conflicting_duplicates", pick["filename"],
                        f"{len(grp)} different {kind} files for week {week}: "
                        f"{', '.join(grp['filename'])}; using latest upload"))
            chosen[(kind + ("_xlsx" if ext == "xlsx" else ""), week)] = pick["url"]
    cat["selected"] = cat["url"].isin(chosen.values())
    return {"catalog": cat, "chosen": chosen, "issues": issues}


# --- run ---------------------------------------------------------------------

def run(full_scan: bool = False, offline: bool = False) -> int:
    for d in (config.RAW, config.INTERIM, config.DATA / "clean", config.REPORTS):
        d.mkdir(parents=True, exist_ok=True)

    if offline:
        catalog = pd.read_csv(CATALOG, dtype=str).replace({"nan": None})
        catalog = catalog.drop(columns=[c for c in ("status", "content_week", "sha", "selected", "week")
                                        if c in catalog.columns])
    else:
        catalog = discover_files(full_scan)
    log.info("catalog: %d SPI files", len(catalog))

    catalog, parsed = download_and_parse(catalog, offline=offline)
    cons = consolidate(catalog, parsed)
    cons["catalog"].to_csv(CATALOG, index=False)

    tables, issues = clean.build_tables(cons["catalog"], cons["chosen"], parsed)
    issues = cons["issues"] + issues
    issues += validate.run_checks(tables)
    tables["yoy_contrib"] = validate.decomposition(tables)
    tables["issues"] = pd.DataFrame(issues, columns=["severity", "check", "subject", "detail"])
    clean.write_tables(tables)
    validate.write_report(tables, config.REPORTS / "validation.md")

    con = load.build()
    from . import dashboard
    dashboard.build(con)

    n_err = int((tables["issues"]["severity"] == "error").sum())
    log.info("done: %d weeks, %d errors, %d warnings", tables["prices"]["week_end"].nunique(),
             n_err, int((tables["issues"]["severity"] == "warn").sum()))
    return 1 if n_err else 0
