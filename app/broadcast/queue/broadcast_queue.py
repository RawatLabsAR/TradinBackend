"""
In-process broadcast queue backed by asyncio.

Architecture:
  enqueue(item) → asyncio.Queue → worker loop → TelegramDispatcher

The worker is started during app lifespan and processes items serially,
applying per-item cooldown and deduplication.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_WORKER_SLEEP = 0.1   # poll interval when queue is empty


@dataclass
class QueueItem:
    message_id: int
    content: str
    parse_mode: str = "Markdown"
    channel_ids: list[int] = field(default_factory=list)
    dedup_key: Optional[str] = None
    priority: int = 5   # lower = higher priority (future use)


class BroadcastQueue:
    """
    Simple asyncio-based broadcast queue.

    - Deduplication: tracks recently dispatched hash keys.
    - Cooldown: minimum gap between two messages to the same channel.
    """

    def __init__(
        self,
        cooldown_seconds: int = 30,
        dedup_window_seconds: int = 300,
        max_queue_size: int = 1000,
    ) -> None:
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=max_queue_size)
        self._cooldown = cooldown_seconds
        self._dedup_window = dedup_window_seconds
        self._recent: dict[str, float] = {}   # hash → sent_at timestamp
        self._channel_last_sent: dict[int, float] = {}  # channel_id → timestamp
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, dispatch_fn) -> None:  # type: ignore[type-arg]
        """
        Start the background worker.
        *dispatch_fn* is an async callable: (item: QueueItem) → None
        """
        if self._running:
            return
        self._running = True
        self._dispatch_fn = dispatch_fn
        self._worker_task = asyncio.create_task(self._worker(), name="broadcast-queue-worker")
        logger.info("BroadcastQueue worker started (cooldown=%ds)", self._cooldown)

    async def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("BroadcastQueue worker stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    async def enqueue(self, item: QueueItem) -> bool:
        """
        Add *item* to the queue.
        Returns False if the item is a duplicate (dedup_key seen recently).
        """
        if item.dedup_key and self._is_duplicate(item.dedup_key):
            logger.debug("Skipping duplicate broadcast key=%s", item.dedup_key)
            return False

        try:
            self._queue.put_nowait(item)
            logger.debug(
                "Enqueued broadcast msg_id=%d (queue size=%d)",
                item.message_id, self._queue.qsize(),
            )
            return True
        except asyncio.QueueFull:
            logger.error("Broadcast queue full — dropping msg_id=%d", item.message_id)
            return False

    @property
    def size(self) -> int:
        return self._queue.qsize()

    # ── Private ───────────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=_WORKER_SLEEP)
            except asyncio.TimeoutError:
                self._cleanup_dedup()
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._dispatch_fn(item)
                if item.dedup_key:
                    self._recent[item.dedup_key] = time.monotonic()
            except Exception:
                logger.exception("Error dispatching queue item msg_id=%d", item.message_id)
            finally:
                self._queue.task_done()

    def _is_duplicate(self, key: str) -> bool:
        sent_at = self._recent.get(key)
        if sent_at is None:
            return False
        return (time.monotonic() - sent_at) < self._dedup_window

    def _cleanup_dedup(self) -> None:
        now = time.monotonic()
        expired = [k for k, t in self._recent.items() if now - t > self._dedup_window]
        for k in expired:
            del self._recent[k]


def make_dedup_key(content: str, channel_ids: list[int]) -> str:
    raw = content[:200] + "|" + ",".join(str(c) for c in sorted(channel_ids))
    return hashlib.sha256(raw.encode()).hexdigest()


# Module-level singleton
broadcast_queue = BroadcastQueue()
