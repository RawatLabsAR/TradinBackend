"""
Telegram dispatcher.

Delivers a BroadcastMessage to one or more TelegramChannel rows,
writes per-channel BroadcastLog entries, and updates the parent
BroadcastMessage status.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broadcast.dispatchers.base_dispatcher import BaseBroadcaster
from app.integrations.telegram.telegram_service import TelegramService
from app.integrations.telegram.telegram_client import TelegramAPIError
from app.models.broadcast import (
    BroadcastMessage,
    BroadcastLog,
    TelegramChannel,
)

logger = logging.getLogger(__name__)

# Telegram allows ~30 messages/second globally; per-chat limit is 1/sec.
_PER_CHAT_DELAY = 0.05  # 50 ms inter-message gap


class TelegramDispatcher(BaseBroadcaster):
    def __init__(self, service: TelegramService) -> None:
        self._service = service

    async def start(self) -> None:
        await self._service.start()

    async def stop(self) -> None:
        await self._service.stop()

    async def send(
        self,
        destination: str,
        content: str,
        parse_mode: str = "Markdown",
        **kwargs,
    ) -> dict:
        try:
            result = await self._service.send_raw(destination, content, parse_mode)
            return {
                "ok": True,
                "message_id": result.get("message_id"),
                "error": None,
            }
        except TelegramAPIError as exc:
            logger.error("TelegramDispatcher.send to %s failed: %s", destination, exc)
            return {"ok": False, "message_id": None, "error": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected error dispatching to %s", destination)
            return {"ok": False, "message_id": None, "error": str(exc)}

    # ── Dispatch a full BroadcastMessage ─────────────────────────────────────

    async def dispatch_message(
        self,
        db: AsyncSession,
        message: BroadcastMessage,
        channels: list[TelegramChannel],
    ) -> None:
        """
        Send *message* to each channel in *channels*, writing a BroadcastLog per channel.
        Updates message.status when done.
        """
        if not channels:
            message.status = "failed"
            message.last_error = "No target channels"
            return

        sent = 0
        failed = 0
        now = datetime.now(timezone.utc)
        message.attempt_count += 1

        for channel in channels:
            log = await self._get_or_create_log(db, message.id, channel.id)
            log.attempt_count += 1

            try:
                result = await self._service.send_raw(
                    channel.chat_id,
                    message.content,
                    message.parse_mode,
                )
                log.status = "sent"
                log.telegram_msg_id = result.get("message_id")
                log.sent_at = now
                log.error_message = None
                sent += 1
                logger.info(
                    "Broadcast msg=%d → channel=%s sent (tg_msg_id=%s)",
                    message.id, channel.chat_id, log.telegram_msg_id,
                )
            except TelegramAPIError as exc:
                log.status = "failed"
                log.error_message = str(exc)
                failed += 1
                logger.warning(
                    "Broadcast msg=%d → channel=%s failed: %s",
                    message.id, channel.chat_id, exc,
                )
            except Exception as exc:
                log.status = "failed"
                log.error_message = str(exc)
                failed += 1
                logger.exception(
                    "Unexpected error broadcasting msg=%d → channel=%s",
                    message.id, channel.chat_id,
                )
            finally:
                await asyncio.sleep(_PER_CHAT_DELAY)

        # Update parent message status
        if sent == len(channels):
            message.status = "sent"
            message.sent_at = now
        elif sent > 0:
            message.status = "partial"
            message.sent_at = now
        else:
            message.status = "failed"
            if message.attempt_count >= message.max_attempts:
                message.last_error = f"All {failed} channel(s) failed after max attempts"

        await db.flush()

    async def _get_or_create_log(
        self, db: AsyncSession, message_id: int, channel_id: int
    ) -> BroadcastLog:
        result = await db.execute(
            select(BroadcastLog).where(
                BroadcastLog.message_id == message_id,
                BroadcastLog.channel_id == channel_id,
            )
        )
        log = result.scalar_one_or_none()
        if log is None:
            log = BroadcastLog(message_id=message_id, channel_id=channel_id)
            db.add(log)
            await db.flush()
        return log


def _dedup_hash(content: str, channel_ids: list[int]) -> str:
    key = content + "|" + ",".join(str(c) for c in sorted(channel_ids))
    return hashlib.sha256(key.encode()).hexdigest()
