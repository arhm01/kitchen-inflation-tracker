"""Polite HTTP: one session, a fixed delay between requests, retries with backoff.

Downloaded files are cached in ``data/raw`` and never re-downloaded, so a weekly
run only fetches the handful of new files.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

log = logging.getLogger(__name__)

_session: requests.Session | None = None
_last_request = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers["User-Agent"] = config.USER_AGENT
        retry = Retry(
            total=config.MAX_RETRIES,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


def get(url: str, **kwargs) -> requests.Response:
    """GET with a minimum gap between consecutive requests."""
    global _last_request
    wait = config.REQUEST_DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        resp = session().get(url, timeout=config.TIMEOUT_S, **kwargs)
    finally:
        _last_request = time.monotonic()
    return resp


def download_many(jobs: list[tuple[str, Path]], workers: int = 3) -> dict[str, str]:
    """Download several files with a small worker pool.

    Used for the one-off historical backfill: the PBS server serves a single
    connection slowly, and three polite workers (each pausing between its own
    requests) roughly triple throughput. Returns {url: "ok" | error}.
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(job: tuple[str, Path]) -> tuple[str, str]:
        url, dest = job
        if dest.exists() and dest.stat().st_size > 0:
            return url, "ok"
        try:
            s = requests.Session()
            s.headers["User-Agent"] = config.USER_AGENT
            r = s.get(url, timeout=config.TIMEOUT_S * 3)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.rename(dest)
            log.info("downloaded %s (%d KB)", dest.name, len(r.content) // 1024)
            time.sleep(config.REQUEST_DELAY_S)
            return url, "ok"
        except Exception as exc:
            return url, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, jobs))


def download(url: str, dest: Path) -> Path:
    """Download ``url`` to ``dest`` unless it is already cached."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = get(url)
    resp.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.rename(dest)
    log.info("downloaded %s (%d KB)", dest.name, len(resp.content) // 1024)
    return dest
