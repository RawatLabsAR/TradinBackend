"""
Scheduled broadcast processor.

Uses APScheduler (already a project dependency) to poll for
ScheduledBroadcast rows with scheduled_at <= now and status == 'pending',
then hands them to BroadcastService for dispatch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.broadcast import ScheduledBroadcast, BroadcastMessage

logger = logging.getLogger(__name__)


async def _process_scheduled_broadcasts() -> None:
    """Check for due scheduled broadcasts and dispatch them."""
    # Import here to avoid circular imports
    from app.broadcast.services.broadcast_service import broadcast_service

    async with AsyncSessionLocal() as db:
        try:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(ScheduledBroadcast)
                .where(
                    ScheduledBroadcast.status == "pending",
                    ScheduledBroadcast.scheduled_at <= now,
                )
                .limit(20)
            )
            due: list[ScheduledBroadcast] = list(result.scalars().all())

            if not due:
                return

            logger.info("Processing %d due scheduled broadcast(s)", len(due))
            for sched in due:
                sched.status = "sent"
                await db.flush()
                try:
                    await broadcast_service.dispatch_message_id(db, sched.message_id)
                except Exception as exc:
                    logger.exception(
                        "Failed to dispatch scheduled broadcast id=%d: %s", sched.id, exc
                    )
                    sched.status = "failed"
                    await db.flush()

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Error in scheduled broadcast processor")


def attach_broadcast_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Register the scheduled broadcast job onto an existing APScheduler instance.
    Call this after the scheduler is created in main.py.
    """
    scheduler.add_job(
        _process_scheduled_broadcasts,
        trigger="interval",
        minutes=1,
        id="broadcast_scheduler",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    logger.info("Broadcast scheduler job registered (runs every 1 minute)")
