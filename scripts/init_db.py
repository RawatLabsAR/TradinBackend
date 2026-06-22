"""Create all ORM tables and run idempotent schema patches."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.models  # noqa: F401 — register models before create_all
from app.db.database import create_tables, dispose_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Creating tables on %s", ROOT / ".env")
    await create_tables()
    await dispose_engine()
    logger.info("Database ready")


if __name__ == "__main__":
    asyncio.run(main())
