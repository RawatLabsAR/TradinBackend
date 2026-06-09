"""On-chain query service for API layer."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.onchain.models.entities import (
    HolderSnapshot,
    LiquidityEvent,
    OnchainTrade,
    SmartMoneyWallet,
    TokenMetric,
    WhaleWallet,
    WalletStat,
)
from app.onchain.types import normalize_address
from app.onchain.analytics.signal_generator import generate_signals
from app.onchain.analytics.heatmap_analytics import compute_trade_heatmap
from app.onchain.analytics.volume_analytics import compute_volume_metrics
from app.onchain.analytics.ohlcv_analytics import (
    count_ohlcv_in_range,
    compute_ohlcv_heatmap,
    compute_ohlcv_volume_metrics,
    fetch_ohlcv_candles,
)
from app.onchain.collectors.gecko_terminal_collector import GeckoTerminalCollector
from app.onchain.services.ai_insights import generate_onchain_ai_insight
from app.onchain.utils.time_range import resolve_time_range


def _range_cache_key(prefix: str, chain: str, token: str, since: datetime, until: datetime) -> str:
    return f"{prefix}:{chain}:{token}:{since.isoformat()}:{until.isoformat()}"


class OnchainService:
    async def get_token_overview(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        hours: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)

        cache_key = _range_cache_key("onchain:overview", chain, token_address, since, until)
        cached = cache.get(cache_key)
        if cached:
            return cached

        ohlcv_count = await count_ohlcv_in_range(
            db, chain, token_address, since=since, until=until,
        )
        data_source = "geckoterminal" if ohlcv_count > 0 else "trades"

        if ohlcv_count > 0:
            volume = await compute_ohlcv_volume_metrics(
                db, chain, token_address, since=since, until=until,
            )
        else:
            volume = await compute_volume_metrics(
                db, chain, token_address,
                since=since,
                until=until,
                whale_threshold_usd=settings.WHALE_THRESHOLD_USD,
            )
            volume["data_source"] = "trades"

        gecko = GeckoTerminalCollector()
        pool = await gecko.resolve_pool(chain, token_address)
        liquidity_usd = float((pool or {}).get("reserve_in_usd") or 0)
        txns_h24 = (pool or {}).get("txns_h24") or {}
        h24_data = txns_h24.get("h24") or {}

        metrics = {
            "chain": chain,
            "token_address": token_address,
            **volume,
            "smart_money_score_avg": 0.0,
            "holder_count": 0,
            "holder_growth_pct": 0.0,
            "liquidity_usd": liquidity_usd,
            "liquidity_change_pct": 0.0,
            "early_buyer_count": int(h24_data.get("buyers") or 0),
            "sniper_count": 0,
            "computed_at": datetime.utcnow(),
            "data_source": data_source,
        }

        signals = await generate_signals(
            db, chain, token_address, since=since, until=until,
        )
        ai_insight = await generate_onchain_ai_insight(db, chain, token_address, signals)

        result = {
            "chain": chain,
            "token_address": token_address,
            "metrics": metrics,
            "recent_signals": [s.model_dump() for s in signals[:10]],
            "ai_insight": ai_insight,
            "period_start": since,
            "period_end": until,
            "data_source": data_source,
            "ohlcv_candle_count": ohlcv_count,
        }
        cache.set(cache_key, result, 60)
        return result

    async def get_trades(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        page: int = 1,
        page_size: int = 50,
        side: Optional[str] = None,
        min_usd: Optional[float] = None,
        hours: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)

        filters = [
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.timestamp >= since,
            OnchainTrade.timestamp <= until,
        ]
        if side:
            filters.append(OnchainTrade.side == side.upper())
        if min_usd is not None:
            filters.append(OnchainTrade.usd_value >= min_usd)

        count_q = await db.execute(select(func.count(OnchainTrade.id)).where(*filters))
        total = int(count_q.scalar() or 0)

        offset = (page - 1) * page_size
        result = await db.execute(
            select(OnchainTrade).where(*filters)
            .order_by(desc(OnchainTrade.timestamp))
            .offset(offset).limit(page_size)
        )
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    async def get_trade_heatmap(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        hours: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)
        ohlcv_count = await count_ohlcv_in_range(
            db, chain, token_address, since=since, until=until,
        )
        if ohlcv_count > 0:
            return await compute_ohlcv_heatmap(
                db, chain, token_address, since=since, until=until,
            )
        return await compute_trade_heatmap(
            db, chain, token_address, since=since, until=until,
        )

    async def get_ohlcv(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        hours: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)

        candles = await fetch_ohlcv_candles(
            db, chain, token_address, since=since, until=until, limit=limit,
        )

        return {
            "chain": chain,
            "token_address": token_address,
            "period_start": since,
            "period_end": until,
            "candle_count": len(candles),
            "data_source": "geckoterminal" if candles else "none",
            "candles": [
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
                for c in candles
            ],
        }

    async def get_holders(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        limit: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)

        filters = [
            HolderSnapshot.chain == chain,
            HolderSnapshot.token_address == token_address,
        ]
        if start_date:
            filters.append(HolderSnapshot.snapshot_at >= start_date)
        if end_date:
            filters.append(HolderSnapshot.snapshot_at <= end_date)

        result = await db.execute(
            select(HolderSnapshot).where(*filters)
            .order_by(desc(HolderSnapshot.snapshot_at)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_whales(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        page: int = 1,
        page_size: int = 50,
        hours: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        since, until = resolve_time_range(start=start_date, end=end_date, hours=hours)

        filters = [
            WhaleWallet.chain == chain,
            WhaleWallet.token_address == token_address,
            WhaleWallet.detected_at >= since,
            WhaleWallet.detected_at <= until,
        ]

        count_q = await db.execute(select(func.count(WhaleWallet.id)).where(*filters))
        total = int(count_q.scalar() or 0)
        offset = (page - 1) * page_size

        result = await db.execute(
            select(WhaleWallet).where(*filters)
            .order_by(desc(WhaleWallet.detected_at))
            .offset(offset).limit(page_size)
        )
        items = list(result.scalars().all())

        # Fallback: large trades in range when whale registry is empty
        if not items and page == 1:
            trade_result = await db.execute(
                select(OnchainTrade).where(
                    OnchainTrade.chain == chain,
                    OnchainTrade.token_address == token_address,
                    OnchainTrade.timestamp >= since,
                    OnchainTrade.timestamp <= until,
                    OnchainTrade.usd_value >= settings.WHALE_THRESHOLD_USD,
                ).order_by(desc(OnchainTrade.timestamp)).limit(page_size)
            )
            for trade in trade_result.scalars().all():
                items.append({
                    "id": -int(trade.id),
                    "chain": chain,
                    "wallet": trade.wallet,
                    "token_address": token_address,
                    "event_type": "LARGE_BUY" if trade.side == "BUY" else "LARGE_SELL",
                    "usd_value": trade.usd_value,
                    "description": (
                        f"{'Whale buy' if trade.side == 'BUY' else 'Whale sell'} "
                        f"${trade.usd_value:,.0f} on {trade.dex or 'DEX'}"
                    ),
                    "tx_hash": trade.tx_hash,
                    "detected_at": trade.timestamp,
                    "metadata_json": {"side": trade.side, "dex": trade.dex, "source": "trade"},
                })
            total = len(items)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_liquidity(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        hours: Optional[int] = None,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        effective_hours = hours
        if effective_hours is None and start_date is None and end_date is None:
            effective_hours = 168
        since, until = resolve_time_range(
            start=start_date, end=end_date, hours=effective_hours,
        )

        result = await db.execute(
            select(LiquidityEvent).where(
                LiquidityEvent.chain == chain,
                LiquidityEvent.token_address == token_address,
                LiquidityEvent.timestamp >= since,
                LiquidityEvent.timestamp <= until,
            ).order_by(desc(LiquidityEvent.timestamp)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_smart_money(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        min_score: Optional[float] = None,
        limit: int = 50,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        threshold = min_score or settings.SMART_MONEY_MIN_SCORE

        filters = [
            SmartMoneyWallet.chain == chain,
            SmartMoneyWallet.token_address == token_address,
            SmartMoneyWallet.score >= threshold,
        ]
        if start_date:
            filters.append(SmartMoneyWallet.last_trade_at >= start_date)
        if end_date:
            filters.append(SmartMoneyWallet.last_trade_at <= end_date)

        result = await db.execute(
            select(SmartMoneyWallet).where(*filters)
            .order_by(desc(SmartMoneyWallet.score)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_metrics(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        *,
        limit: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)

        filters = [
            TokenMetric.chain == chain,
            TokenMetric.token_address == token_address,
        ]
        if start_date:
            filters.append(TokenMetric.period_end >= start_date)
        if end_date:
            filters.append(TokenMetric.period_start <= end_date)

        result = await db.execute(
            select(TokenMetric).where(*filters)
            .order_by(desc(TokenMetric.computed_at)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_wallet_stats(
        self,
        db: AsyncSession,
        chain: str,
        wallet: str,
    ) -> Optional[WalletStat]:
        chain = chain.lower()
        wallet = normalize_address(chain, wallet)

        result = await db.execute(
            select(WalletStat).where(
                WalletStat.chain == chain,
                WalletStat.wallet == wallet,
            )
        )
        return result.scalar_one_or_none()


onchain_service = OnchainService()
