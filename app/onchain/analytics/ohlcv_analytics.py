"""Volume, price, and heatmap analytics from GeckoTerminal OHLCV candles."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import OnchainOhlcv


def _split_volume(open_usd: float, close_usd: float, volume_usd: float) -> tuple[float, float]:
    """Approximate buy/sell split from candle direction."""
    if volume_usd <= 0:
        return 0.0, 0.0
    if close_usd > open_usd:
        buy_ratio = 0.55 + min((close_usd - open_usd) / max(open_usd, 1e-9), 1.0) * 0.15
    elif close_usd < open_usd:
        buy_ratio = 0.45 - min((open_usd - close_usd) / max(open_usd, 1e-9), 1.0) * 0.15
    else:
        buy_ratio = 0.5
    buy = volume_usd * buy_ratio
    return buy, volume_usd - buy


async def count_ohlcv_in_range(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    since: datetime,
    until: datetime,
) -> int:
    result = await db.execute(
        select(func.count(OnchainOhlcv.id)).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
            OnchainOhlcv.timestamp >= since,
            OnchainOhlcv.timestamp <= until,
        )
    )
    return int(result.scalar() or 0)


async def compute_ohlcv_volume_metrics(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    since: datetime,
    until: datetime,
) -> dict:
    result = await db.execute(
        select(
            OnchainOhlcv.open_usd,
            OnchainOhlcv.close_usd,
            OnchainOhlcv.volume_usd,
            OnchainOhlcv.high_usd,
            OnchainOhlcv.low_usd,
        ).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
            OnchainOhlcv.timestamp >= since,
            OnchainOhlcv.timestamp <= until,
        ).order_by(OnchainOhlcv.timestamp)
    )
    rows = result.all()

    buy_vol = 0.0
    sell_vol = 0.0
    total_vol = 0.0
    first_open = None
    last_close = None
    high = 0.0
    low = float("inf")

    for open_usd, close_usd, volume_usd, row_high, row_low in rows:
        buy, sell = _split_volume(float(open_usd), float(close_usd), float(volume_usd))
        buy_vol += buy
        sell_vol += sell
        total_vol += float(volume_usd)
        if first_open is None:
            first_open = float(open_usd)
        last_close = float(close_usd)
        high = max(high, float(row_high))
        low = min(low, float(row_low))

    price_change_pct = 0.0
    if first_open and last_close and first_open > 0:
        price_change_pct = ((last_close - first_open) / first_open) * 100

    return {
        "buy_volume_usd": round(buy_vol, 2),
        "sell_volume_usd": round(sell_vol, 2),
        "net_flow_usd": round(buy_vol - sell_vol, 2),
        "total_volume_usd": round(total_vol, 2),
        "whale_buy_volume_usd": 0.0,
        "whale_sell_volume_usd": 0.0,
        "unique_wallets": 0,
        "unique_buyers": 0,
        "unique_sellers": 0,
        "price_open_usd": round(first_open or 0, 6),
        "price_close_usd": round(last_close or 0, 6),
        "price_high_usd": round(high if high > 0 else 0, 6),
        "price_low_usd": round(low if low != float("inf") else 0, 6),
        "price_change_pct": round(price_change_pct, 2),
        "candle_count": len(rows),
        "data_source": "geckoterminal",
        "period_start": since,
        "period_end": until,
    }


def _resolve_bucket_plan(since: datetime, until: datetime) -> tuple[int, str]:
    span = until - since
    span_days = max(1, int(span.total_seconds() // 86400) + 1)
    if span_days <= 2:
        return min(span_days * 24, 48), "hourly"
    if span_days <= 14:
        return min(span_days * 4, 56), "six_hourly"
    return min(span_days, 60), "daily"


def _bucket_start(since: datetime, until: datetime, bucket_count: int, idx: int) -> datetime:
    span = (until - since).total_seconds() or 1
    offset = span * idx / bucket_count
    return since + timedelta(seconds=offset)


async def compute_ohlcv_heatmap(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    since: datetime,
    until: datetime,
) -> dict:
    result = await db.execute(
        select(
            OnchainOhlcv.timestamp,
            OnchainOhlcv.open_usd,
            OnchainOhlcv.close_usd,
            OnchainOhlcv.volume_usd,
        ).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
            OnchainOhlcv.timestamp >= since,
            OnchainOhlcv.timestamp <= until,
        ).order_by(OnchainOhlcv.timestamp)
    )
    rows = result.all()

    bucket_count, mode = _resolve_bucket_plan(since, until)
    span = (until - since).total_seconds() or 1
    bucket_seconds = span / bucket_count

    buckets = [
        {
            "label": _bucket_start(since, until, bucket_count, i).isoformat(),
            "buy_usd": 0.0,
            "sell_usd": 0.0,
            "total_usd": 0.0,
        }
        for i in range(bucket_count)
    ]

    since_ts = since.timestamp()
    for timestamp, open_usd, close_usd, volume_usd in rows:
        ts = timestamp.timestamp() if isinstance(timestamp, datetime) else since_ts
        idx = min(int((ts - since_ts) / bucket_seconds), bucket_count - 1)
        buy, sell = _split_volume(float(open_usd), float(close_usd), float(volume_usd))
        buckets[idx]["buy_usd"] += buy
        buckets[idx]["sell_usd"] += sell
        buckets[idx]["total_usd"] += float(volume_usd)

    for b in buckets:
        b["buy_usd"] = round(b["buy_usd"], 2)
        b["sell_usd"] = round(b["sell_usd"], 2)
        b["total_usd"] = round(b["total_usd"], 2)

    active = sum(1 for b in buckets if b["total_usd"] > 0)

    return {
        "chain": chain,
        "token_address": token_address,
        "period_start": since,
        "period_end": until,
        "bucket_mode": mode,
        "bucket_count": bucket_count,
        "active_buckets": active,
        "trade_count": len(rows),
        "data_source": "geckoterminal",
        "buckets": buckets,
    }


async def fetch_ohlcv_candles(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    since: datetime,
    until: datetime,
    limit: int = 1000,
) -> list[OnchainOhlcv]:
    result = await db.execute(
        select(OnchainOhlcv).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
            OnchainOhlcv.timestamp >= since,
            OnchainOhlcv.timestamp <= until,
        ).order_by(OnchainOhlcv.timestamp).limit(limit)
    )
    return list(result.scalars().all())
