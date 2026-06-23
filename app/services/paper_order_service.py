"""Evaluate pending limit orders and SL/TP on live tickers."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.paper_trade import PaperTrade
from app.services.paper_trade_service import compute_closed_pnl

logger = logging.getLogger(__name__)


def _limit_should_fill(trade: PaperTrade, price: float) -> bool:
    limit = trade.limit_price or trade.entry_price
    if trade.side == "long":
        return price <= limit
    return price >= limit


def _stop_hit(trade: PaperTrade, price: float) -> bool:
    if not trade.stop_loss:
        return False
    if trade.side == "long":
        return price <= trade.stop_loss
    return price >= trade.stop_loss


def _tp_hit(trade: PaperTrade, price: float) -> bool:
    if not trade.take_profit:
        return False
    if trade.side == "long":
        return price >= trade.take_profit
    return price >= trade.take_profit


async def check_paper_orders_for_ticker(ticker: dict) -> None:
    """Fill pending limits and trigger SL/TP for open paper trades."""
    if AsyncSessionLocal is None:
        return

    product_id = str(ticker.get("product_id", "")).upper()
    price_raw = ticker.get("price")
    if not product_id or price_raw is None:
        return

    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return
    if price <= 0:
        return

    async with AsyncSessionLocal() as db:
        try:
            q = select(PaperTrade).where(
                PaperTrade.product_id == product_id,
                PaperTrade.closed_at.is_(None),
            )
            result = await db.execute(q)
            trades = list(result.scalars().all())
            changed = False

            for trade in trades:
                if trade.is_pending:
                    if _limit_should_fill(trade, price):
                        trade.is_pending = 0
                        trade.entry_price = trade.limit_price or price
                        changed = True
                    continue

                exit_price = None
                if _stop_hit(trade, price):
                    exit_price = trade.stop_loss
                elif _tp_hit(trade, price):
                    exit_price = trade.take_profit

                if exit_price is not None:
                    pnl, pnl_pct = compute_closed_pnl(
                        trade.side,
                        trade.entry_price,
                        exit_price,
                        trade.quantity,
                        trade.fee_pct,
                    )
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.pnl_pct = round(pnl_pct, 4)
                    from datetime import datetime, timezone
                    trade.closed_at = datetime.now(timezone.utc)
                    changed = True

            if changed:
                await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Paper order check failed for %s", product_id)
