"""Orchestrate daily whale scan job."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models.whale_scan import WhaleScanRun
from app.onchain.collectors.base import close_session as close_onchain_session
from app.providers.registry import close_market_session
from app.whale_scanner.discover import discover_raw_candidates, select_scan_batch, upsert_candidates
from app.whale_scanner.notify import send_digest
from app.whale_scanner import progress
from app.whale_scanner.scan import rank_results, scan_candidates
from app.whale_scanner.settings import whale_scan_settings

logger = logging.getLogger(__name__)


def _build_engine():
    url = whale_scan_settings.DATABASE_URL.strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for whale scanner")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    connect_args: dict = {}
    if ":6543" in url:
        connect_args["statement_cache_size"] = 0
    if "supabase.co" in url:
        connect_args["ssl"] = "require"

    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        connect_args=connect_args,
    )


async def run_daily(*, limit: int | None = None, track_progress: bool = False) -> dict:
    """Full pipeline: discover → scan → notify."""
    if limit is not None:
        whale_scan_settings.MAX_TOKENS_PER_RUN = limit

    engine = _build_engine()
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    stats: dict = {}
    run_id: int | None = None

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            run = WhaleScanRun(started_at=datetime.now(timezone.utc), status="running")
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        if track_progress:
            await progress.set_run_id(run_id)

        logger.info("Whale scan run #%d starting (dry_run=%s)", run_id, whale_scan_settings.DRY_RUN)

        raw = await discover_raw_candidates()
        stats["discovered"] = len(raw)

        async with session_factory() as db:
            await upsert_candidates(db, raw)
            await db.commit()
            batch = await select_scan_batch(db)
            stats["candidates_in_batch"] = len(batch)

        if track_progress:
            await progress.set_discovered(len(raw), len(batch))

        async def _on_scan_progress(**kwargs) -> None:
            await progress.tick_scan(**kwargs)

        results = await scan_candidates(
            session_factory,
            batch,
            on_progress=_on_scan_progress if track_progress else None,
        )
        hits = rank_results(results)
        stats["tokens_scanned"] = len(results)
        stats["whale_hits"] = len(hits)
        stats["whale_events"] = sum(len(h.events) for h in hits)

        if track_progress:
            await progress.set_notifying()

        async with session_factory() as db:
            messages = await send_digest(
                db,
                hits,
                run_id=run_id,
                scanned_count=len(results),
            )
            run = await db.get(WhaleScanRun, run_id)
            if run:
                run.finished_at = datetime.now(timezone.utc)
                run.candidates_found = len(raw)
                run.tokens_scanned = len(results)
                run.whales_detected = len(hits)
                run.messages_sent = messages
                run.status = "ok"
                await db.commit()

        stats["messages_sent"] = messages
        stats["run_id"] = run_id
        logger.info("Whale scan run #%d complete: %s", run_id, stats)

        if track_progress:
            await progress.finish_ok(stats=stats)

    except Exception as exc:
        logger.exception("Whale scan failed: %s", exc)
        stats["error"] = str(exc)
        if track_progress:
            await progress.finish_failed(str(exc))
        if run_id is not None:
            try:
                async with session_factory() as db:
                    run = await db.get(WhaleScanRun, run_id)
                    if run and run.status == "running":
                        run.finished_at = datetime.now(timezone.utc)
                        run.status = "failed"
                        run.error = str(exc)
                        await db.commit()
            except Exception:
                logger.exception("Failed to mark whale scan run #%s as failed", run_id)
        raise
    finally:
        await engine.dispose()
        await close_onchain_session()
        await close_market_session()

    return stats
