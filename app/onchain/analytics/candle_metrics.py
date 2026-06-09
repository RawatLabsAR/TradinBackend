"""Compute metrics and heatmaps from in-memory OHLCV candles."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from app.onchain.types import NormalizedOhlcv


def _split_volume(open_usd: float, close_usd: float, volume_usd: float) -> tuple[float, float]:
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


def metrics_from_candles(
    candles: Sequence[NormalizedOhlcv],
    *,
    since: datetime,
    until: datetime,
    liquidity_usd: float = 0.0,
    chain: str = "",
    token_address: str = "",
) -> dict:
    filtered = [
        c for c in candles
        if since <= c.timestamp <= until
    ]
    if not filtered:
        filtered = list(candles)

    buy_vol = 0.0
    sell_vol = 0.0
    total_vol = 0.0
    first_open = None
    last_close = None
    high = 0.0
    low = float("inf")

    for c in filtered:
        buy, sell = _split_volume(c.open_usd, c.close_usd, c.volume_usd)
        buy_vol += buy
        sell_vol += sell
        total_vol += c.volume_usd
        if first_open is None:
            first_open = c.open_usd
        last_close = c.close_usd
        high = max(high, c.high_usd)
        low = min(low, c.low_usd)

    price_change_pct = 0.0
    if first_open and last_close and first_open > 0:
        price_change_pct = ((last_close - first_open) / first_open) * 100

    return {
        "chain": chain,
        "token_address": token_address,
        "buy_volume_usd": round(buy_vol, 2),
        "sell_volume_usd": round(sell_vol, 2),
        "net_flow_usd": round(buy_vol - sell_vol, 2),
        "total_volume_usd": round(total_vol, 2),
        "whale_buy_volume_usd": 0.0,
        "whale_sell_volume_usd": 0.0,
        "unique_wallets": 0,
        "unique_buyers": 0,
        "unique_sellers": 0,
        "smart_money_score_avg": 0.0,
        "holder_count": 0,
        "holder_growth_pct": 0.0,
        "liquidity_usd": round(liquidity_usd, 2),
        "liquidity_change_pct": 0.0,
        "early_buyer_count": 0,
        "sniper_count": 0,
        "price_open_usd": round(first_open or 0, 8),
        "price_close_usd": round(last_close or 0, 8),
        "price_high_usd": round(high if high > 0 else 0, 8),
        "price_low_usd": round(low if low != float("inf") else 0, 8),
        "price_change_pct": round(price_change_pct, 2),
        "candle_count": len(filtered),
        "data_source": "geckoterminal",
        "period_start": since,
        "period_end": until,
        "computed_at": datetime.utcnow(),
    }


def _resolve_bucket_plan(since: datetime, until: datetime) -> tuple[int, str]:
    span_days = max(1, int((until - since).total_seconds() // 86400) + 1)
    if span_days <= 2:
        return min(span_days * 24, 48), "hourly"
    if span_days <= 14:
        return min(span_days * 4, 56), "six_hourly"
    return min(span_days, 60), "daily"


def heatmap_from_candles(
    candles: Sequence[NormalizedOhlcv],
    *,
    since: datetime,
    until: datetime,
    chain: str = "",
    token_address: str = "",
) -> dict:
    filtered = sorted(
        [c for c in candles if since <= c.timestamp <= until],
        key=lambda c: c.timestamp,
    )

    bucket_count, mode = _resolve_bucket_plan(since, until)
    span = (until - since).total_seconds() or 1
    bucket_seconds = span / bucket_count

    buckets = [
        {
            "label": (since + timedelta(seconds=span * i / bucket_count)).isoformat(),
            "buy_usd": 0.0,
            "sell_usd": 0.0,
            "total_usd": 0.0,
        }
        for i in range(bucket_count)
    ]

    since_ts = since.timestamp()
    for c in filtered:
        ts = c.timestamp.timestamp()
        idx = min(int((ts - since_ts) / bucket_seconds), bucket_count - 1)
        buy, sell = _split_volume(c.open_usd, c.close_usd, c.volume_usd)
        buckets[idx]["buy_usd"] += buy
        buckets[idx]["sell_usd"] += sell
        buckets[idx]["total_usd"] += c.volume_usd

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
        "trade_count": len(filtered),
        "data_source": "geckoterminal",
        "buckets": buckets,
    }


def candles_to_dict(candles: Sequence[NormalizedOhlcv]) -> list[dict]:
    return [
        {
            "timestamp": c.timestamp,
            "open_usd": c.open_usd,
            "high_usd": c.high_usd,
            "low_usd": c.low_usd,
            "close_usd": c.close_usd,
            "volume_usd": c.volume_usd,
            "timeframe": c.timeframe,
            "aggregate": c.aggregate,
        }
        for c in sorted(candles, key=lambda x: x.timestamp)
    ]
