#!/usr/bin/env python3
"""One-shot database cleanup: retention purge + drop obsolete tables."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal, engine
from app.db.retention import run_retention_cleanup
from app.models.ai_summary import AISummary

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Tables replaced by in-memory caches or never used by the app.
DROP_TABLES = (
    "token_search_cache",
    "token_metadata",
    "trending_tokens",
    "indicator_cache",
)

ONCHAIN_TABLES = (
    "onchain_trades",
    "onchain_ohlcv_candles",
    "wallet_stats",
    "holder_snapshots",
    "liquidity_events",
    "whale_wallets",
    "smart_money_wallets",
    "token_metrics",
    "sync_checkpoints",
)


async def dedupe_ai_summaries(db: AsyncSession) -> int:
    """Keep only the latest row per symbol in ai_summaries."""
    symbols_result = await db.execute(select(AISummary.symbol).distinct())
    symbols = [row[0] for row in symbols_result.all()]
    removed = 0

    for symbol in symbols:
        latest_result = await db.execute(
            select(AISummary.id)
            .where(AISummary.symbol == symbol)
            .order_by(desc(AISummary.created_at))
            .limit(1)
        )
        keep_id = latest_result.scalar_one_or_none()
        if keep_id is None:
            continue

        result = await db.execute(
            delete(AISummary).where(
                AISummary.symbol == symbol,
                AISummary.id != keep_id,
            )
        )
        removed += result.rowcount or 0

    return removed


async def drop_obsolete_tables(db: AsyncSession) -> list[str]:
    dropped: list[str] = []
    for table in DROP_TABLES:
        exists = await db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": table},
        )
        if not exists.scalar():
            logger.info("Table %s does not exist — skipping", table)
            continue

        await db.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
        dropped.append(table)
        logger.info("Dropped table: %s", table)

    return dropped


async def truncate_onchain_data(db: AsyncSession) -> dict[str, int]:
    """Wipe all on-chain analytics rows and reset sequences."""
    before: dict[str, int] = {}
    for table in ONCHAIN_TABLES:
        exists = await db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": table},
        )
        if not exists.scalar():
            continue
        count_result = await db.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
        before[table] = count_result.scalar() or 0

    if not before:
        return before

    tables_sql = ", ".join(f'"{t}"' for t in before)
    await db.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))
    return before


async def list_public_tables(db: AsyncSession) -> list[str]:
    result = await db.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
    )
    return [row[0] for row in result.all()]


async def main() -> None:
    if AsyncSessionLocal is None:
        logger.error("DATABASE_URL is not configured")
        sys.exit(1)

    logger.info("Connecting to database…")

    async with AsyncSessionLocal() as db:
        logger.info("=== Step 1: Retention cleanup ===")
        stats = await run_retention_cleanup(db)
        await db.commit()
        total = sum(stats.values())
        logger.info("Retention removed %d rows", total)

        logger.info("=== Step 2: Deduplicate AI summaries ===")
        deduped = await dedupe_ai_summaries(db)
        await db.commit()
        logger.info("Removed %d duplicate ai_summaries rows", deduped)

        logger.info("=== Step 3: Drop obsolete tables ===")
        dropped = await drop_obsolete_tables(db)
        await db.commit()
        logger.info("Dropped %d tables: %s", len(dropped), ", ".join(dropped) or "(none)")

        logger.info("=== Step 4: Truncate on-chain data ===")
        onchain_before = await truncate_onchain_data(db)
        await db.commit()
        total_onchain = sum(onchain_before.values())
        logger.info(
            "Truncated %d on-chain rows across %d tables",
            total_onchain,
            len(onchain_before),
        )
        for table, count in onchain_before.items():
            if count:
                logger.info("  %-30s %8d rows removed", table, count)

        logger.info("=== Remaining public tables ===")
        tables = await list_public_tables(db)
        for name in tables:
            count_result = await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))
            count = count_result.scalar()
            logger.info("  %-30s %8d rows", name, count)

    if engine is not None:
        await engine.dispose()

    logger.info("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
