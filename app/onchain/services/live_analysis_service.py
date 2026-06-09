"""Live on-chain analysis — fetch directly from GeckoTerminal, no DB sync required."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.core.cache import cache
from app.onchain.analytics.candle_metrics import (
    candles_to_dict,
    heatmap_from_candles,
    metrics_from_candles,
)
from app.onchain.collectors.gecko_terminal_collector import GeckoTerminalCollector
from app.onchain.types import NormalizedTrade, normalize_address
from app.onchain.utils.time_range import resolve_time_range

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes


def _cache_key(chain: str, token: str, since: datetime, until: datetime) -> str:
    return f"live_analysis:{chain}:{token}:{since.date()}:{until.date()}"


class LiveAnalysisService:
    async def analyze(
        self,
        chain: str,
        token_address: str,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hours: Optional[int] = None,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)

        key = _cache_key(chain, token_address, since, until)
        cached = cache.get(key)
        if cached:
            return cached

        collector = GeckoTerminalCollector()
        pool = await collector.resolve_pool(chain, token_address)

        if not pool or not pool.get("pool_address"):
            return {
                "chain": chain,
                "token_address": token_address,
                "period_start": since,
                "period_end": until,
                "data_source": "none",
                "error": "No DEX pool found for this token on GeckoTerminal.",
                "pool": None,
                "metrics": None,
                "candles": [],
                "heatmap": heatmap_from_candles([], since=since, until=until, chain=chain, token_address=token_address),
                "live_trades": [],
            }

        candles = await collector.fetch_ohlcv_live(
            chain, token_address, start=since, end=until, pool=pool,
        )

        txns = pool.get("txns_h24") or {}
        h24 = txns.get("h24") or {}

        metrics = metrics_from_candles(
            candles,
            since=since,
            until=until,
            liquidity_usd=float(pool.get("reserve_in_usd") or 0),
            chain=chain,
            token_address=token_address,
        )
        metrics["early_buyer_count"] = int(h24.get("buyers") or 0)
        metrics["price_usd"] = float(pool.get("price_usd") or metrics.get("price_close_usd") or 0)

        heatmap = heatmap_from_candles(
            candles, since=since, until=until, chain=chain, token_address=token_address,
        )

        live_trades: list[dict] = []
        if until.date() >= datetime.utcnow().date() - timedelta(days=1):
            trades, _ = await collector.fetch_trades(
                chain, token_address, limit=50, pool=pool,
            )
            live_trades = [_trade_to_dict(t) for t in trades[:50]]

        result = {
            "chain": chain,
            "token_address": token_address,
            "period_start": since,
            "period_end": until,
            "data_source": "geckoterminal" if candles else "none",
            "error": None if candles else "No OHLCV data for this date range. Try a shorter range or different token.",
            "pool": {
                "address": pool.get("pool_address"),
                "dex": pool.get("dex"),
                "liquidity_usd": pool.get("reserve_in_usd"),
                "volume_h24_usd": pool.get("volume_h24_usd"),
                "price_usd": pool.get("price_usd"),
            },
            "metrics": metrics,
            "candles": candles_to_dict(candles),
            "heatmap": heatmap,
            "live_trades": live_trades,
        }

        if candles:
            cache.set(key, result, CACHE_TTL)
        return result


def _trade_to_dict(trade: NormalizedTrade) -> dict:
    return {
        "id": hash(trade.tx_hash) % 1_000_000,
        "chain": trade.chain,
        "token_address": trade.token_address,
        "wallet": trade.wallet,
        "side": trade.side,
        "amount": trade.amount,
        "usd_value": trade.usd_value,
        "price_usd": trade.price_usd,
        "timestamp": trade.timestamp,
        "dex": trade.dex,
        "tx_hash": trade.tx_hash,
        "raw_source": trade.raw_source,
    }


live_analysis_service = LiveAnalysisService()
