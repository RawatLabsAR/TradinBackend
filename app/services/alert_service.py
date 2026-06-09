"""Evaluate price alerts against live tickers and dispatch notifications."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.db.database import AsyncSessionLocal
from app.models.price_alert import PriceAlert
from app.broadcast.services.broadcast_service import broadcast_service
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

_LAST_PRICE_TTL = 3600  # 1 hour — enough for cross-detection, survives brief restarts in-process


def _crossed(price: float, target: float, direction: str, prev_price: float | None) -> bool:
    if direction == "above":
        if prev_price is not None:
            return prev_price < target <= price
        return price >= target
    if prev_price is not None:
        return prev_price > target >= price
    return price <= target


def _get_prev_price(product_id: str) -> float | None:
    return cache.get(f"alert:last_price:{product_id}")


def _set_prev_price(product_id: str, price: float) -> None:
    cache.set(f"alert:last_price:{product_id}", price, _LAST_PRICE_TTL)


async def check_alerts_for_ticker(ticker: dict) -> None:
    product_id = ticker.get("product_id")
    price_raw = ticker.get("price")
    if not product_id or not price_raw:
        return

    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return

    product_key = product_id.upper()
    prev = _get_prev_price(product_key)
    _set_prev_price(product_key, price)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PriceAlert).where(
                PriceAlert.product_id == product_key,
                PriceAlert.is_active == True,  # noqa: E712
            )
        )
        alerts = result.scalars().all()
        if not alerts:
            return

        triggered_any = False
        for alert in alerts:
            if not _crossed(price, alert.target_price, alert.direction, prev):
                continue

            alert.is_active = False
            alert.triggered_at = datetime.now(timezone.utc)
            triggered_any = True

            msg = alert.message or (
                f"Price alert: {product_id} crossed {alert.direction} "
                f"${alert.target_price:,.2f} (now ${price:,.2f})"
            )

            await ws_manager.broadcast_all({
                "type": "price_alert",
                "data": {
                    "alert_id": alert.id,
                    "product_id": product_id,
                    "target_price": alert.target_price,
                    "direction": alert.direction,
                    "current_price": price,
                    "message": msg,
                },
            })

            if alert.notify_telegram and broadcast_service._queue is not None:
                try:
                    channel_ids = [alert.channel_id] if alert.channel_id else None
                    message = await broadcast_service.send_manual(
                        db=db,
                        content=f"🔔 *Price Alert*\n\n{msg}",
                        title=f"Alert: {product_id}",
                        channel_ids=channel_ids,
                    )
                    await db.commit()
                    await broadcast_service.enqueue_committed_message(message)
                except Exception as exc:
                    logger.error("Telegram alert dispatch failed: %s", exc)
                    await db.rollback()

        if triggered_any:
            try:
                await db.commit()
            except Exception as exc:
                logger.error("Failed to commit alert triggers: %s", exc)
                await db.rollback()


async def list_alerts(db: AsyncSession, product_id: str | None = None) -> list[PriceAlert]:
    q = select(PriceAlert).order_by(PriceAlert.created_at.desc())
    if product_id:
        q = q.where(PriceAlert.product_id == product_id.upper())
    result = await db.execute(q)
    return list(result.scalars().all())
