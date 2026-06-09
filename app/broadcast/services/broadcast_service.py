"""
Core broadcast service.

Orchestrates:
  1. Creating BroadcastMessage rows
  2. Resolving target channels
  3. Enqueuing to BroadcastQueue
  4. Dispatching via TelegramDispatcher (called by queue worker)
  5. Persisting delivery logs
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.broadcast import (
    BroadcastMessage,
    BroadcastTemplate,
    BroadcastLog,
    ScheduledBroadcast,
    SignalBroadcastHistory,
    TelegramChannel,
)
from app.integrations.telegram.telegram_service import get_telegram_service
from app.broadcast.dispatchers.telegram_dispatcher import TelegramDispatcher
from app.broadcast.queue.broadcast_queue import BroadcastQueue, QueueItem, make_dedup_key
from app.broadcast.templates.template_engine import template_engine

logger = logging.getLogger(__name__)


class BroadcastService:
    def __init__(self) -> None:
        self._queue: Optional[BroadcastQueue] = None
        self._dispatcher: Optional[TelegramDispatcher] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, cooldown_seconds: int = 30) -> None:
        from app.integrations.telegram.telegram_service import get_telegram_service
        svc = get_telegram_service()
        self._dispatcher = TelegramDispatcher(svc)
        self._queue = BroadcastQueue(cooldown_seconds=cooldown_seconds)
        await self._queue.start(self._process_queue_item)
        logger.info("BroadcastService started")

    async def stop(self) -> None:
        if self._queue:
            await self._queue.stop()
        logger.info("BroadcastService stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    async def send_manual(
        self,
        db: AsyncSession,
        content: str,
        title: Optional[str] = None,
        parse_mode: str = "Markdown",
        channel_ids: Optional[list[int]] = None,
        template_id: Optional[int] = None,
        template_variables: Optional[dict[str, Any]] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> BroadcastMessage:
        """
        Create a manual broadcast message row and flush it.
        The caller MUST call db.commit() and then enqueue_committed_message()
        so the queue worker sees the committed row.
        """
        final_content = content
        if template_id and template_variables:
            tpl = await template_engine.get_template(db, template_id)
            if tpl:
                final_content = template_engine.render(tpl.content, template_variables)

        message = BroadcastMessage(
            title=title,
            content=final_content,
            parse_mode=parse_mode,
            message_type="scheduled" if scheduled_at else "manual",
            status="pending",
            template_id=template_id,
            template_variables=template_variables,
            target_channel_ids=channel_ids or [],
            scheduled_at=scheduled_at,
        )
        db.add(message)
        await db.flush()

        if scheduled_at:
            sched = ScheduledBroadcast(
                message_id=message.id,
                scheduled_at=scheduled_at,
                status="pending",
            )
            db.add(sched)
            await db.flush()

        return message

    async def enqueue_committed_message(self, message: BroadcastMessage, dedup_key: Optional[str] = None) -> None:
        """
        Enqueue a message that has already been committed to the DB.
        Call this AFTER db.commit() to avoid the queue worker reading an
        uncommitted row.
        """
        await self._enqueue(message, dedup_key=dedup_key)

    async def send_signal_broadcast(
        self,
        db: AsyncSession,
        symbol: str,
        signal_type: str,
        strategy: str,
        timeframe: str,
        price: Optional[float] = None,
        reason: Optional[str] = None,
        sentiment: Optional[str] = None,
        ai_commentary: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> Optional[BroadcastMessage]:
        """Format and broadcast a strategy signal to signal-enabled channels."""
        from app.core.config import settings
        if not settings.ENABLE_SIGNAL_BROADCAST:
            logger.debug("Signal broadcasting disabled via ENABLE_SIGNAL_BROADCAST")
            return None

        from app.integrations.telegram.message_formatter import format_signal_alert
        content = format_signal_alert(
            symbol=symbol,
            signal_type=signal_type,
            strategy=strategy,
            timeframe=timeframe,
            price=price,
            reason=reason,
            sentiment=sentiment,
            ai_commentary=ai_commentary,
        )

        dedup_key = f"signal:{symbol}:{signal_type}:{strategy}:{timeframe}"
        if self._queue and self._queue._is_duplicate(dedup_key):
            logger.debug("Duplicate signal broadcast suppressed: %s", dedup_key)
            return None

        message = BroadcastMessage(
            title=f"{signal_type.upper()} Signal — {symbol}",
            content=content,
            parse_mode="Markdown",
            message_type="signal",
            status="pending",
            dedup_hash=hashlib.sha256(dedup_key.encode()).hexdigest(),
            target_channel_ids=[],   # [] = all signal channels
        )
        db.add(message)
        await db.flush()

        sig_hist = SignalBroadcastHistory(
            message_id=message.id,
            symbol=symbol,
            signal_type=signal_type,
            strategy=strategy,
            timeframe=timeframe,
            price=price,
            sentiment=sentiment,
            reason=reason,
            ai_commentary=ai_commentary,
            extra_data=extra_data or {},
        )
        db.add(sig_hist)
        await db.flush()

        # Do NOT enqueue here — caller must commit first, then call enqueue_committed_message()
        return message

    async def send_ai_broadcast(
        self,
        db: AsyncSession,
        symbol: str,
        summary: str,
        sentiment: Optional[str] = None,
        confidence: Optional[float] = None,
        drivers: Optional[list[str]] = None,
    ) -> BroadcastMessage:
        """Broadcast an AI insight to ai-enabled channels."""
        from app.integrations.telegram.message_formatter import format_ai_insight
        content = format_ai_insight(
            symbol=symbol,
            summary=summary,
            sentiment=sentiment,
            confidence=confidence,
            drivers=drivers,
        )

        message = BroadcastMessage(
            title=f"AI Insight — {symbol}",
            content=content,
            parse_mode="Markdown",
            message_type="ai_insight",
            status="pending",
            target_channel_ids=[],
        )
        db.add(message)
        await db.flush()

        # Do NOT enqueue here — caller must commit first, then call enqueue_committed_message()
        return message

    async def dispatch_message_id(self, db: AsyncSession, message_id: int) -> None:
        """Re-dispatch a message by id (used by scheduled processor)."""
        result = await db.execute(
            select(BroadcastMessage).where(BroadcastMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg:
            await self._enqueue(msg)

    async def get_history(
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        message_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        from sqlalchemy import func

        # Build base filter conditions
        conditions = []
        if message_type:
            conditions.append(BroadcastMessage.message_type == message_type)
        if status:
            conditions.append(BroadcastMessage.status == status)

        # Count
        count_stmt = select(func.count(BroadcastMessage.id))
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar_one()

        # Paged data
        data_stmt = select(BroadcastMessage).order_by(desc(BroadcastMessage.created_at))
        if conditions:
            data_stmt = data_stmt.where(*conditions)
        offset = (page - 1) * page_size
        data_stmt = data_stmt.limit(page_size).offset(offset)
        result = await db.execute(data_stmt)
        items = list(result.scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    # ── Private ───────────────────────────────────────────────────────────────

    async def _enqueue(
        self, message: BroadcastMessage, dedup_key: Optional[str] = None
    ) -> None:
        if not self._queue:
            logger.warning("BroadcastQueue not started — message %d dropped", message.id)
            return
        item = QueueItem(
            message_id=message.id,
            content=message.content,
            parse_mode=message.parse_mode,
            channel_ids=message.target_channel_ids or [],
            dedup_key=dedup_key,
        )
        message.status = "queued"
        enqueued = await self._queue.enqueue(item)
        if not enqueued:
            message.status = "failed"
            message.last_error = "Duplicate suppressed or queue full"

    async def _process_queue_item(self, item: QueueItem) -> None:
        """
        Called by the queue worker for each item.
        Opens its own DB session (queue worker runs in background).
        """
        if self._dispatcher is None:
            logger.error("Dispatcher not initialised — cannot process queue item")
            return

        async with AsyncSessionLocal() as db:
            try:
                # Reload message
                result = await db.execute(
                    select(BroadcastMessage).where(BroadcastMessage.id == item.message_id)
                )
                message = result.scalar_one_or_none()
                if not message:
                    logger.warning("BroadcastMessage id=%d not found", item.message_id)
                    return

                # Resolve target channels
                channels = await self._resolve_channels(db, message)
                if not channels:
                    message.status = "failed"
                    message.last_error = "No active target channels"
                    await db.commit()
                    return

                await self._dispatcher.dispatch_message(db, message, channels)
                await db.commit()

            except Exception:
                await db.rollback()
                logger.exception("Error processing broadcast queue item id=%d", item.message_id)

    async def _resolve_channels(
        self, db: AsyncSession, message: BroadcastMessage
    ) -> list[TelegramChannel]:
        """
        Return the list of TelegramChannel rows to deliver to.
        - If target_channel_ids is non-empty, use those specific channels.
        - If empty: signal messages → signal channels; ai_insight → ai channels; others → all active.
        """
        if message.target_channel_ids:
            result = await db.execute(
                select(TelegramChannel).where(
                    TelegramChannel.id.in_(message.target_channel_ids),
                    TelegramChannel.is_active == True,  # noqa: E712
                )
            )
            return list(result.scalars().all())

        if message.message_type == "signal":
            result = await db.execute(
                select(TelegramChannel).where(
                    TelegramChannel.is_active == True,  # noqa: E712
                    TelegramChannel.send_signals == True,  # noqa: E712
                )
            )
        elif message.message_type == "ai_insight":
            result = await db.execute(
                select(TelegramChannel).where(
                    TelegramChannel.is_active == True,  # noqa: E712
                    TelegramChannel.send_ai == True,  # noqa: E712
                )
            )
        else:
            result = await db.execute(
                select(TelegramChannel).where(TelegramChannel.is_active == True)  # noqa: E712
            )
        return list(result.scalars().all())


# Module-level singleton
broadcast_service = BroadcastService()
