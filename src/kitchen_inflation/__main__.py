"""Command line entry point.

    uv run python -m kitchen_inflation run              # weekly: discover new files, parse, publish
    uv run python -m kitchen_inflation run --full-scan  # re-list the whole WordPress media library
    uv run python -m kitchen_inflation run --offline    # no network: rebuild from data/raw
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import pipeline


def main() -> None:
    ap = argparse.ArgumentParser(prog="kitchen_inflation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the full pipeline")
    r.add_argument("--full-scan", action="store_true")
    r.add_argument("--offline", action="store_true")
    r.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    if args.cmd == "run":
        sys.exit(pipeline.run(full_scan=args.full_scan, offline=args.offline))


if __name__ == "__main__":
    main()
