"""Aggregate on-chain trades into heatmap time buckets."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import OnchainTrade


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


async def compute_trade_heatmap(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    since: datetime,
    until: datetime,
) -> dict:
    result = await db.execute(
        select(
            OnchainTrade.timestamp,
            OnchainTrade.side,
            OnchainTrade.usd_value,
        ).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.timestamp >= since,
            OnchainTrade.timestamp <= until,
        )
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
    for timestamp, side, usd_value in rows:
        ts = timestamp.timestamp() if isinstance(timestamp, datetime) else since_ts
        if ts < since_ts or ts > until.timestamp():
            continue
        idx = min(int((ts - since_ts) / bucket_seconds), bucket_count - 1)
        value = float(usd_value or 0)
        if side == "BUY":
            buckets[idx]["buy_usd"] += value
        else:
            buckets[idx]["sell_usd"] += value
        buckets[idx]["total_usd"] += value

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
        "buckets": buckets,
    }
