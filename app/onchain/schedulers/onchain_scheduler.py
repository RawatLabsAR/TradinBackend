"""On-chain ETL scheduler jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.onchain.pipelines.etl_pipeline import run_full_etl
from app.onchain.services.realtime_broadcaster import broadcast_onchain_events
from app.onchain.services.telegram_alerts import broadcast_onchain_telegram_alerts
from app.onchain.tracked_tokens import get_tracked_tokens

logger = logging.getLogger(__name__)


async def onchain_sync_job() -> None:
    """Scheduled job: sync all tracked tokens."""
    if not settings.ENABLE_ONCHAIN_PERSISTENCE:
        return
    if AsyncSessionLocal is None:
        return
    tokens = get_tracked_tokens()
    if not tokens:
        logger.debug("Onchain sync: no tracked tokens configured")
        return

    logger.info("Onchain sync: processing %d tokens", len(tokens))

    async with AsyncSessionLocal() as db:
        for token in tokens:
            chain = token["chain"]
            address = token["token_address"]
            try:
                result = await run_full_etl(db, chain, address)
                await db.commit()

                signals = result.get("analytics", {}).get("signals", [])
                if signals:
                    await broadcast_onchain_events(chain, address, signals)
                    await broadcast_onchain_telegram_alerts(db, chain, address, signals)

                logger.info(
                    "Onchain sync complete %s/%s: +%d trades",
                    chain, address[:10],
                    result.get("trades", {}).get("inserted", 0),
                )
            except Exception as exc:
                logger.exception("Onchain sync failed %s/%s: %s", chain, address, exc)
                await db.rollback()


def attach_onchain_scheduler(scheduler) -> None:
    """Attach on-chain sync job to existing APScheduler."""
    if not settings.ENABLE_ONCHAIN_PERSISTENCE:
        logger.info("On-chain persistence disabled — scheduler not attached")
        return
    interval = settings.ONCHAIN_SYNC_INTERVAL_MINUTES
    scheduler.add_job(
        onchain_sync_job,
        "interval",
        minutes=interval,
        id="onchain_sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info("Onchain scheduler attached (interval=%dm)", interval)
