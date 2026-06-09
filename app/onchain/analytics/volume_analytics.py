"""Volume and flow analytics for on-chain trades."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import OnchainTrade


async def compute_volume_metrics(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    hours: int = 24,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    whale_threshold_usd: float = 50_000,
) -> dict:
    if since is None and until is None:
        since = datetime.utcnow() - timedelta(hours=hours)
        until = datetime.utcnow()
    elif since is None:
        since = until - timedelta(hours=hours)  # type: ignore[operator]
    elif until is None:
        until = datetime.utcnow()

    base_filter = (
        OnchainTrade.chain == chain,
        OnchainTrade.token_address == token_address,
        OnchainTrade.timestamp >= since,
        OnchainTrade.timestamp <= until,
    )

    buy_q = await db.execute(
        select(func.coalesce(func.sum(OnchainTrade.usd_value), 0.0)).where(
            *base_filter, OnchainTrade.side == "BUY"
        )
    )
    sell_q = await db.execute(
        select(func.coalesce(func.sum(OnchainTrade.usd_value), 0.0)).where(
            *base_filter, OnchainTrade.side == "SELL"
        )
    )
    whale_buy_q = await db.execute(
        select(func.coalesce(func.sum(OnchainTrade.usd_value), 0.0)).where(
            *base_filter,
            OnchainTrade.side == "BUY",
            OnchainTrade.usd_value >= whale_threshold_usd,
        )
    )
    whale_sell_q = await db.execute(
        select(func.coalesce(func.sum(OnchainTrade.usd_value), 0.0)).where(
            *base_filter,
            OnchainTrade.side == "SELL",
            OnchainTrade.usd_value >= whale_threshold_usd,
        )
    )
    unique_wallets_q = await db.execute(
        select(func.count(distinct(OnchainTrade.wallet))).where(*base_filter)
    )
    unique_buyers_q = await db.execute(
        select(func.count(distinct(OnchainTrade.wallet))).where(
            *base_filter, OnchainTrade.side == "BUY"
        )
    )
    unique_sellers_q = await db.execute(
        select(func.count(distinct(OnchainTrade.wallet))).where(
            *base_filter, OnchainTrade.side == "SELL"
        )
    )

    buy_vol = float(buy_q.scalar() or 0)
    sell_vol = float(sell_q.scalar() or 0)

    return {
        "buy_volume_usd": round(buy_vol, 2),
        "sell_volume_usd": round(sell_vol, 2),
        "net_flow_usd": round(buy_vol - sell_vol, 2),
        "whale_buy_volume_usd": round(float(whale_buy_q.scalar() or 0), 2),
        "whale_sell_volume_usd": round(float(whale_sell_q.scalar() or 0), 2),
        "unique_wallets": int(unique_wallets_q.scalar() or 0),
        "unique_buyers": int(unique_buyers_q.scalar() or 0),
        "unique_sellers": int(unique_sellers_q.scalar() or 0),
        "period_start": since,
        "period_end": until,
    }
