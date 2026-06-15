"""Entry point: python -m app.whale_scanner [--dry-run] [--limit N]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import app.models  # noqa: F401 — register ORM models before create_all

from app.whale_scanner.service import run_daily
from app.whale_scanner.settings import whale_scan_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tradin daily whale scanner")
    parser.add_argument("--dry-run", action="store_true", help="Scan without Telegram send")
    parser.add_argument("--limit", type=int, default=None, help="Max tokens to scan this run")
    args = parser.parse_args()

    if args.dry_run:
        whale_scan_settings.DRY_RUN = True

    try:
        stats = asyncio.run(run_daily(limit=args.limit))
        logger.info("Done: %s", stats)
        return 0
    except Exception as exc:
        logger.error("Whale scanner failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
