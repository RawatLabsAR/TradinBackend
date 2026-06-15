"""Discovery background scan scheduler — in-memory only, no database."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.discovery.services.discovery_service import discovery_service

logger = logging.getLogger(__name__)


async def discovery_scan_job() -> None:
    try:
        await discovery_service.run_full_scan()
    except Exception as exc:
        logger.exception("Discovery scan job failed: %s", exc)


def attach_discovery_scheduler(scheduler) -> None:
    hour = settings.DISCOVERY_SCAN_HOUR
    minute = settings.DISCOVERY_SCAN_MINUTE
    scheduler.add_job(
        discovery_scan_job,
        "cron",
        hour=hour,
        minute=minute,
        id="discovery_scan",
        replace_existing=True,
    )
    logger.info("Discovery scheduler attached (daily at %02d:%02d UTC, in-memory cache)", hour, minute)
