"""Scheduled DB retention — keeps Postgres storage lean."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_summary import AISummary
from app.models.broadcast import BroadcastLog, SignalBroadcastHistory
from app.models.market_insight import MarketInsight
from app.models.news_article import NewsArticle
from app.models.script import BacktestResult, SignalHistory, StrategyRun
from app.onchain.models.entities import (
    HolderSnapshot,
    LiquidityEvent,
    OnchainOhlcv,
    OnchainTrade,
    TokenMetric,
    WhaleWallet,
)
from app.token_search.models.entities import SearchHistory

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC — matches TIMESTAMP WITHOUT TIME ZONE columns in this schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _delete_count(db: AsyncSession, stmt) -> int:
    result = await db.execute(stmt)
    return result.rowcount or 0


async def cleanup_news(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_NEWS_DAYS)
    return await _delete_count(
        db, delete(NewsArticle).where(NewsArticle.published_at < cutoff)
    )


async def cleanup_ai_summaries(db: AsyncSession) -> int:
    """Remove expired summaries; keep at most one row per symbol."""
    now = _utcnow()
    expired = await _delete_count(
        db, delete(AISummary).where(AISummary.expires_at < now)
    )

    cutoff = _utcnow() - timedelta(days=settings.RETENTION_AI_SUMMARIES_DAYS)
    stale = await _delete_count(
        db, delete(AISummary).where(AISummary.created_at < cutoff)
    )

    await _delete_count(
        db,
        delete(MarketInsight).where(
            MarketInsight.expires_at.isnot(None),
            MarketInsight.expires_at < now,
        ),
    )
    await _delete_count(
        db,
        delete(MarketInsight).where(MarketInsight.created_at < cutoff),
    )
    return expired + stale


async def cleanup_onchain_trades(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_ONCHAIN_TRADES_DAYS)
    return await _delete_count(
        db, delete(OnchainTrade).where(OnchainTrade.timestamp < cutoff)
    )


async def cleanup_onchain_ohlcv(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_ONCHAIN_OHLCV_DAYS)
    return await _delete_count(
        db, delete(OnchainOhlcv).where(OnchainOhlcv.timestamp < cutoff)
    )


async def cleanup_onchain_snapshots(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_ONCHAIN_SNAPSHOTS_DAYS)
    return await _delete_count(
        db, delete(HolderSnapshot).where(HolderSnapshot.snapshot_at < cutoff)
    )


async def cleanup_onchain_events(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_ONCHAIN_EVENTS_DAYS)
    liq = await _delete_count(
        db, delete(LiquidityEvent).where(LiquidityEvent.timestamp < cutoff)
    )
    whales = await _delete_count(
        db, delete(WhaleWallet).where(WhaleWallet.detected_at < cutoff)
    )
    return liq + whales


async def cleanup_onchain_metrics(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_ONCHAIN_METRICS_DAYS)
    return await _delete_count(
        db, delete(TokenMetric).where(TokenMetric.period_end < cutoff)
    )


async def cleanup_search_history(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_SEARCH_HISTORY_DAYS)
    return await _delete_count(
        db, delete(SearchHistory).where(SearchHistory.searched_at < cutoff)
    )


async def cleanup_broadcast_logs(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_BROADCAST_LOGS_DAYS)
    logs = await _delete_count(
        db, delete(BroadcastLog).where(BroadcastLog.created_at < cutoff)
    )
    signals = await _delete_count(
        db,
        delete(SignalBroadcastHistory).where(SignalBroadcastHistory.created_at < cutoff),
    )
    return logs + signals


async def cleanup_strategy_runs(db: AsyncSession) -> int:
    cutoff = _utcnow() - timedelta(days=settings.RETENTION_STRATEGY_RUNS_DAYS)
    old_run_ids = select(StrategyRun.id).where(StrategyRun.created_at < cutoff)

    await _delete_count(
        db, delete(SignalHistory).where(SignalHistory.run_id.in_(old_run_ids))
    )
    await _delete_count(
        db, delete(BacktestResult).where(BacktestResult.run_id.in_(old_run_ids))
    )
    return await _delete_count(
        db, delete(StrategyRun).where(StrategyRun.created_at < cutoff)
    )


async def run_retention_cleanup(db: AsyncSession) -> dict[str, int]:
    """Run all retention jobs. Returns per-table deletion counts."""
    stats: dict[str, int] = {}

    if settings.ENABLE_NEWS_PERSISTENCE:
        stats["news_articles"] = await cleanup_news(db)

    if settings.ENABLE_AI_PERSISTENCE:
        stats["ai_summaries"] = await cleanup_ai_summaries(db)

    if settings.ENABLE_ONCHAIN_PERSISTENCE:
        stats["onchain_trades"] = await cleanup_onchain_trades(db)
        stats["onchain_ohlcv"] = await cleanup_onchain_ohlcv(db)
        stats["onchain_snapshots"] = await cleanup_onchain_snapshots(db)
        stats["onchain_events"] = await cleanup_onchain_events(db)
        stats["onchain_metrics"] = await cleanup_onchain_metrics(db)

    if settings.ENABLE_TOKEN_SEARCH_DB:
        stats["search_history"] = await cleanup_search_history(db)

    stats["broadcast_logs"] = await cleanup_broadcast_logs(db)
    stats["strategy_runs"] = await cleanup_strategy_runs(db)

    total = sum(stats.values())
    logger.info(
        "Retention cleanup complete — removed %d rows (%s)",
        total,
        ", ".join(f"{k}={v}" for k, v in stats.items() if v),
    )
    return stats
