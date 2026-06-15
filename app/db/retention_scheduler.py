"""Attach DB retention jobs to the shared APScheduler."""

from __future__ import annotations

import logging

from app.db.database import AsyncSessionLocal
from app.db.retention import run_retention_cleanup

logger = logging.getLogger(__name__)


async def retention_cleanup_job() -> None:
    if AsyncSessionLocal is None:
        return
    async with AsyncSessionLocal() as db:
        try:
            await run_retention_cleanup(db)
            await db.commit()
        except Exception as exc:
            logger.exception("Retention cleanup failed: %s", exc)
            await db.rollback()


def attach_retention_scheduler(scheduler) -> None:
    scheduler.add_job(
        retention_cleanup_job,
        "cron",
        hour=2,
        minute=30,
        id="db_retention",
        replace_existing=True,
    )
    logger.info("DB retention scheduler attached (daily 02:30 UTC)")
