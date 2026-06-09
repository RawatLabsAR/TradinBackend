"""ETL pipeline: Collector → Normalizer → Database → Analytics."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.collectors import (
    DuneCollector,
    DexScreenerOnchainCollector,
    GeckoTerminalCollector,
)
from app.onchain.models.entities import (
    HolderSnapshot,
    LiquidityEvent,
    OnchainOhlcv,
    OnchainTrade,
    TokenMetric,
)
from app.onchain.types import NormalizedLiquidityEvent, NormalizedOhlcv, NormalizedTrade, normalize_address
from app.onchain.analytics.volume_analytics import compute_volume_metrics
from app.onchain.analytics.smart_money_scorer import score_wallet, update_smart_money_registry
from app.onchain.analytics.holder_analytics import compute_holder_growth
from app.onchain.analytics.signal_generator import generate_signals
from app.onchain.analytics.ohlcv_analytics import compute_ohlcv_volume_metrics
from app.core.config import settings

logger = logging.getLogger(__name__)

EVM_CHAINS = {"ethereum", "base", "bsc"}
SOLANA_CHAIN = "solana"


def _get_trade_collectors(chain: str, *, include_dexscreener: bool) -> list:
    collectors: list = [GeckoTerminalCollector()]
    if chain in EVM_CHAINS:
        dune = DuneCollector()
        if dune.is_configured:
            collectors.append(dune)
    if include_dexscreener:
        collectors.append(DexScreenerOnchainCollector())
    return collectors


async def _has_ohlcv_data(db: AsyncSession, chain: str, token_address: str) -> bool:
    result = await db.execute(
        select(func.count(OnchainOhlcv.id)).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
        )
    )
    return int(result.scalar() or 0) > 0


async def _persist_trades(
    db: AsyncSession,
    trades: list[NormalizedTrade],
) -> int:
    inserted = 0
    seen: set[tuple[str, str, str, str, str]] = set()

    for trade in trades:
        dedup_key = (
            trade.chain,
            trade.tx_hash,
            trade.token_address,
            trade.wallet,
            trade.side,
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        existing = await db.execute(
            select(OnchainTrade.id).where(
                OnchainTrade.chain == trade.chain,
                OnchainTrade.tx_hash == trade.tx_hash,
                OnchainTrade.token_address == trade.token_address,
                OnchainTrade.wallet == trade.wallet,
                OnchainTrade.side == trade.side,
            )
        )
        if existing.scalar_one_or_none():
            continue

        try:
            async with db.begin_nested():
                db.add(OnchainTrade(
                    chain=trade.chain,
                    token_address=trade.token_address,
                    wallet=trade.wallet,
                    side=trade.side,
                    amount=trade.amount,
                    usd_value=trade.usd_value,
                    price_usd=trade.price_usd,
                    timestamp=trade.timestamp,
                    dex=trade.dex,
                    tx_hash=trade.tx_hash,
                    block_number=trade.block_number,
                    raw_source=trade.raw_source,
                    metadata_json=trade.metadata,
                ))
                await db.flush()
            inserted += 1
        except IntegrityError:
            continue
    return inserted


async def _persist_ohlcv(
    db: AsyncSession,
    candles: list[NormalizedOhlcv],
) -> int:
    inserted = 0
    for candle in candles:
        existing = await db.execute(
            select(OnchainOhlcv.id).where(
                OnchainOhlcv.chain == candle.chain,
                OnchainOhlcv.token_address == candle.token_address,
                OnchainOhlcv.pool_address == candle.pool_address,
                OnchainOhlcv.timeframe == candle.timeframe,
                OnchainOhlcv.aggregate == candle.aggregate,
                OnchainOhlcv.timestamp == candle.timestamp,
            )
        )
        if existing.scalar_one_or_none():
            continue

        try:
            async with db.begin_nested():
                db.add(OnchainOhlcv(
                    chain=candle.chain,
                    token_address=candle.token_address,
                    pool_address=candle.pool_address,
                    timeframe=candle.timeframe,
                    aggregate=candle.aggregate,
                    timestamp=candle.timestamp,
                    open_usd=candle.open_usd,
                    high_usd=candle.high_usd,
                    low_usd=candle.low_usd,
                    close_usd=candle.close_usd,
                    volume_usd=candle.volume_usd,
                    raw_source=candle.raw_source,
                    metadata_json=candle.metadata,
                ))
                await db.flush()
            inserted += 1
        except IntegrityError:
            continue
    return inserted


async def _persist_liquidity(
    db: AsyncSession,
    events: list[NormalizedLiquidityEvent],
) -> int:
    inserted = 0
    for evt in events:
        existing = await db.execute(
            select(LiquidityEvent.id).where(
                LiquidityEvent.chain == evt.chain,
                LiquidityEvent.tx_hash == evt.tx_hash,
                LiquidityEvent.token_address == evt.token_address,
                LiquidityEvent.event_type == evt.event_type,
            )
        )
        if existing.scalar_one_or_none():
            continue

        db.add(LiquidityEvent(
            chain=evt.chain,
            token_address=evt.token_address,
            pool_address=evt.pool_address,
            event_type=evt.event_type,
            wallet=evt.wallet,
            token_amount=evt.token_amount,
            usd_value=evt.usd_value,
            liquidity_usd=evt.liquidity_usd,
            timestamp=evt.timestamp,
            tx_hash=evt.tx_hash,
            dex=evt.dex,
            metadata_json=evt.metadata,
        ))
        inserted += 1
    return inserted


async def sync_token_ohlcv(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """Fetch and store OHLCV candles from GeckoTerminal for a date range."""
    chain = chain.lower()
    token_address = normalize_address(chain, token_address)
    end = end_date or datetime.utcnow()
    start = start_date or (end - timedelta(days=7))

    if start > end:
        start, end = end, start

    collector = GeckoTerminalCollector()
    await collector.update_checkpoint(
        db, chain, token_address, "ohlcv", status="running",
    )

    try:
        candles = await collector.fetch_ohlcv_range(
            chain, token_address, start=start, end=end,
        )
        inserted = await _persist_ohlcv(db, candles)

        pool = await collector.resolve_pool(chain, token_address)
        if pool and pool.get("pool_address"):
            await collector.update_checkpoint(
                db, chain, token_address, "ohlcv",
                last_cursor=pool["pool_address"],
                last_timestamp=end,
                records_synced=inserted,
                status="idle",
            )

        return {
            "inserted": inserted,
            "candles_fetched": len(candles),
            "pool_address": (pool or {}).get("pool_address", ""),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "source": collector.source_name,
        }
    except Exception as exc:
        logger.exception("OHLCV sync failed %s/%s", chain, token_address)
        await collector.update_checkpoint(
            db, chain, token_address, "ohlcv",
            status="error", error_message=str(exc)[:500],
        )
        raise


async def sync_token_trades(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    max_pages: int = 4,
) -> dict:
    """Sync live trades (GeckoTerminal 24h + optional Dune). Skips DexScreener when OHLCV exists."""
    chain = chain.lower()
    token_address = normalize_address(chain, token_address)
    total_inserted = 0
    sources_used: list[str] = []
    has_ohlcv = await _has_ohlcv_data(db, chain, token_address)

    for collector in _get_trade_collectors(chain, include_dexscreener=not has_ohlcv):
        cp = await collector.get_checkpoint(db, chain, token_address, "trades")
        since = cp.last_timestamp if cp and cp.last_timestamp else None
        cursor = cp.last_cursor if cp else ""
        source_inserted = 0

        await collector.update_checkpoint(
            db, chain, token_address, "trades", status="running",
        )

        try:
            replace_sources = {"dexscreener_onchain", "geckoterminal"}
            if collector.source_name in replace_sources:
                await db.execute(
                    delete(OnchainTrade).where(
                        OnchainTrade.chain == chain,
                        OnchainTrade.token_address == token_address,
                        OnchainTrade.raw_source == (
                            "dexscreener" if collector.source_name == "dexscreener_onchain"
                            else "geckoterminal"
                        ),
                    )
                )

            for _ in range(max_pages):
                trades, next_cursor = await collector.fetch_trades(
                    chain, token_address,
                    since=since, cursor=cursor, limit=200,
                )
                if not trades:
                    break

                inserted = await _persist_trades(db, trades)
                source_inserted += inserted
                total_inserted += inserted

                last_ts = max(t.timestamp for t in trades)
                await collector.update_checkpoint(
                    db, chain, token_address, "trades",
                    last_timestamp=last_ts,
                    last_cursor=next_cursor,
                    records_synced=inserted,
                    status="idle",
                )

                if not next_cursor:
                    break
                cursor = next_cursor

            if source_inserted > 0 or collector.source_name == "geckoterminal":
                sources_used.append(collector.source_name)
            await collector.update_checkpoint(
                db, chain, token_address, "trades",
                records_synced=source_inserted,
                status="idle",
            )
        except Exception as exc:
            logger.exception(
                "Trade sync failed %s/%s via %s",
                chain, token_address, collector.source_name,
            )
            await collector.update_checkpoint(
                db, chain, token_address, "trades",
                status="error", error_message=str(exc)[:500],
            )

    return {"inserted": total_inserted, "sources": sources_used}


async def sync_token_liquidity(
    db: AsyncSession,
    chain: str,
    token_address: str,
) -> dict:
    chain = chain.lower()
    token_address = normalize_address(chain, token_address)
    total_inserted = 0

    gecko = GeckoTerminalCollector()
    pool = await gecko.resolve_pool(chain, token_address)
    if pool and pool.get("reserve_in_usd", 0) > 0:
        return {
            "inserted": 0,
            "liquidity_usd": pool["reserve_in_usd"],
            "source": "geckoterminal",
        }

    for collector in _get_trade_collectors(chain, include_dexscreener=True):
        if collector.source_name == "geckoterminal":
            continue
        cp = await collector.get_checkpoint(db, chain, token_address, "liquidity")
        since = cp.last_timestamp if cp and cp.last_timestamp else None

        events, _ = await collector.fetch_liquidity_events(
            chain, token_address, since=since, limit=100,
        )
        inserted = await _persist_liquidity(db, events)
        total_inserted += inserted

        if events:
            last_ts = max(e.timestamp for e in events)
            await collector.update_checkpoint(
                db, chain, token_address, "liquidity",
                last_timestamp=last_ts,
                records_synced=inserted,
            )

    return {"inserted": total_inserted}


async def sync_token_holders(
    db: AsyncSession,
    chain: str,
    token_address: str,
) -> dict:
    chain = chain.lower()
    token_address = normalize_address(chain, token_address)

    for collector in _get_trade_collectors(chain, include_dexscreener=True):
        if collector.source_name == "geckoterminal":
            continue
        snapshot = await collector.fetch_holder_snapshot(chain, token_address)
        if snapshot:
            db.add(HolderSnapshot(
                chain=snapshot.chain,
                token_address=snapshot.token_address,
                holder_count=snapshot.holder_count,
                top10_pct=snapshot.top10_pct,
                top50_pct=snapshot.top50_pct,
                snapshot_at=snapshot.snapshot_at,
                metadata_json=snapshot.metadata,
            ))
            return {"holder_count": snapshot.holder_count}

    return {"holder_count": 0}


async def run_analytics_pipeline(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    hours: int = 24,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    """Run full analytics after ingestion."""
    chain = chain.lower()
    token_address = normalize_address(chain, token_address)

    if since is None and until is None:
        since = datetime.utcnow() - timedelta(hours=hours)
        until = datetime.utcnow()

    result = await db.execute(
        select(OnchainTrade.wallet).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
        ).distinct().limit(200)
    )
    wallets = [row[0] for row in result.all()]
    for wallet in wallets:
        await score_wallet(db, chain, wallet)

    await update_smart_money_registry(db, chain, token_address)

    ohlcv_count = await db.execute(
        select(func.count(OnchainOhlcv.id)).where(
            OnchainOhlcv.chain == chain,
            OnchainOhlcv.token_address == token_address,
            OnchainOhlcv.timestamp >= since,
            OnchainOhlcv.timestamp <= until,
        )
    )
    has_ohlcv = int(ohlcv_count.scalar() or 0) > 0

    if has_ohlcv:
        volume = await compute_ohlcv_volume_metrics(
            db, chain, token_address, since=since, until=until,
        )
    else:
        volume = await compute_volume_metrics(
            db, chain, token_address,
            since=since, until=until,
            whale_threshold_usd=settings.WHALE_THRESHOLD_USD,
        )
        volume["data_source"] = "trades"

    holder = await compute_holder_growth(db, chain, token_address)

    gecko = GeckoTerminalCollector()
    pool = await gecko.resolve_pool(chain, token_address)
    liquidity_usd = float((pool or {}).get("reserve_in_usd") or 0)

    db.add(TokenMetric(
        chain=chain,
        token_address=token_address,
        buy_volume_usd=volume["buy_volume_usd"],
        sell_volume_usd=volume["sell_volume_usd"],
        net_flow_usd=volume["net_flow_usd"],
        unique_wallets=volume.get("unique_wallets", 0),
        unique_buyers=volume.get("unique_buyers", 0),
        unique_sellers=volume.get("unique_sellers", 0),
        whale_buy_volume_usd=volume.get("whale_buy_volume_usd", 0),
        whale_sell_volume_usd=volume.get("whale_sell_volume_usd", 0),
        holder_count=holder["holder_count"],
        holder_growth_pct=holder["holder_growth_pct"],
        liquidity_usd=liquidity_usd,
        period_start=volume["period_start"],
        period_end=volume["period_end"],
        computed_at=datetime.utcnow(),
        metadata_json={
            "data_source": volume.get("data_source", "trades"),
            "candle_count": volume.get("candle_count", 0),
        },
    ))

    signals = await generate_signals(
        db, chain, token_address, since=since, until=until,
    )

    return {
        "volume": volume,
        "holder": holder,
        "signals": [s.model_dump() for s in signals],
        "wallets_scored": len(wallets),
        "liquidity_usd": liquidity_usd,
    }


async def run_full_etl(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """Complete ETL: OHLCV sync → live trades → analytics."""
    end = end_date or datetime.utcnow()
    start = start_date or (end - timedelta(days=7))
    if start > end:
        start, end = end, start

    ohlcv_result = await sync_token_ohlcv(
        db, chain, token_address, start_date=start, end_date=end,
    )
    trades_result = await sync_token_trades(db, chain, token_address)
    liq_result = await sync_token_liquidity(db, chain, token_address)
    holder_result = await sync_token_holders(db, chain, token_address)
    analytics = await run_analytics_pipeline(
        db, chain, token_address, since=start, until=end,
    )

    return {
        "ohlcv": ohlcv_result,
        "trades": trades_result,
        "liquidity": liq_result,
        "holders": holder_result,
        "analytics": analytics,
    }
