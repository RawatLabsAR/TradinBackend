"""Discovery background scan scheduler — optional Supabase persistence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.discovery.services.discovery_service import discovery_service

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


async def discovery_scan_job() -> None:
    if not settings.ENABLE_DISCOVERY_SCHEDULER:
        return
    if _lock.locked():
        logger.info("Discovery scan job skipped — previous run still in progress")
        return

    async with _lock:
        try:
            await discovery_service.run_full_scan()
        except Exception as exc:
            logger.exception("Discovery scan job failed: %s", exc)


def attach_discovery_scheduler(scheduler) -> None:
    if not settings.ENABLE_DISCOVERY_SCHEDULER:
        logger.info("Discovery scheduler disabled (ENABLE_DISCOVERY_SCHEDULER=false)")
        return

    interval = settings.DISCOVERY_SCAN_INTERVAL_MINUTES
    scheduler.add_job(
        discovery_scan_job,
        "interval",
        minutes=interval,
        id="discovery_scan",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Discovery scheduler attached (every %dm, runs on startup, persistence=%s)",
        interval,
        settings.ENABLE_DISCOVERY_PERSISTENCE,
    )
