"""
Signal broadcast integration.

Hooks into the Pine Script strategy engine:
  - called by scripts.py after generating signals
  - fetches AI sentiment if available
  - hands off to BroadcastService
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.broadcast.services.broadcast_service import broadcast_service

logger = logging.getLogger(__name__)


async def broadcast_strategy_signal(
    db: AsyncSession,
    symbol: str,
    signal_type: str,       # "BUY" | "SELL" | "EXIT"
    strategy_name: str,
    timeframe: str,
    price: Optional[float] = None,
    reason: Optional[str] = None,
    script_id: Optional[int] = None,
) -> None:
    """
    Broadcast a strategy signal.
    Fetches AI sentiment from DB cache to enrich the message.
    """
    sentiment: Optional[str] = None
    ai_commentary: Optional[str] = None

    try:
        from sqlalchemy import select
        from app.models.coin_sentiment import CoinSentiment
        sym_clean = symbol.split("-")[0].upper()
        result = await db.execute(
            select(CoinSentiment).where(CoinSentiment.symbol == sym_clean)
        )
        coin_sent = result.scalar_one_or_none()
        if coin_sent:
            sentiment = coin_sent.sentiment

        from app.models.ai_summary import AISummary
        from sqlalchemy import desc
        result2 = await db.execute(
            select(AISummary)
            .where(AISummary.symbol == sym_clean)
            .order_by(desc(AISummary.created_at))
            .limit(1)
        )
        summary_row = result2.scalar_one_or_none()
        if summary_row and summary_row.summary:
            ai_commentary = summary_row.summary[:200]

    except Exception:
        logger.debug("Could not fetch AI context for signal broadcast", exc_info=True)

    try:
        message = await broadcast_service.send_signal_broadcast(
            db=db,
            symbol=symbol,
            signal_type=signal_type,
            strategy=strategy_name,
            timeframe=timeframe,
            price=price,
            reason=reason,
            sentiment=sentiment,
            ai_commentary=ai_commentary,
            extra_data={"script_id": script_id} if script_id else {},
        )
        if message is not None:
            await db.commit()
            dedup_key = f"signal:{symbol}:{signal_type}:{strategy_name}:{timeframe}"
            await broadcast_service.enqueue_committed_message(message, dedup_key=dedup_key)
    except Exception:
        logger.exception("Failed to broadcast signal for %s %s", symbol, signal_type)
