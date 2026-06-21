"""Background whale scan runner for the web API."""

from __future__ import annotations

import asyncio
import logging

from app.whale_scanner import progress
from app.whale_scanner.service import run_daily
from app.whale_scanner.settings import whale_scan_settings

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def background_task_running() -> bool:
    return _task is not None and not _task.done()


async def start_background_scan(*, limit: int | None = None, dry_run: bool = False) -> None:
    global _task

    if background_task_running() or progress.is_running():
        raise RuntimeError("A whale scan is already running")

    if dry_run:
        whale_scan_settings.DRY_RUN = True

    if not await progress.try_start(run_id=0):
        raise RuntimeError("A whale scan is already running")

    _task = asyncio.create_task(_run(limit=limit))
    _task.add_done_callback(_clear_task)


def _clear_task(_: asyncio.Task) -> None:
    global _task
    _task = None


async def _run(*, limit: int | None) -> None:
    try:
        await run_daily(limit=limit, track_progress=True)
    except Exception as exc:
        logger.exception("Background whale scan failed: %s", exc)
        await progress.finish_failed(str(exc))
