"""
Telegram channel manager.

Handles CRUD operations for TelegramChannel DB rows and
validation against the live Telegram Bot API.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broadcast import TelegramChannel
from app.integrations.telegram.telegram_client import TelegramClient, TelegramAPIError

logger = logging.getLogger(__name__)


class ChannelManager:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def list_channels(
        self, db: AsyncSession, active_only: bool = True
    ) -> list[TelegramChannel]:
        stmt = select(TelegramChannel)
        if active_only:
            stmt = stmt.where(TelegramChannel.is_active == True)  # noqa: E712
        stmt = stmt.order_by(TelegramChannel.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_channel(
        self, db: AsyncSession, channel_id: int
    ) -> Optional[TelegramChannel]:
        result = await db.execute(
            select(TelegramChannel).where(TelegramChannel.id == channel_id)
        )
        return result.scalar_one_or_none()

    async def get_channel_by_chat_id(
        self, db: AsyncSession, chat_id: str
    ) -> Optional[TelegramChannel]:
        result = await db.execute(
            select(TelegramChannel).where(TelegramChannel.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def create_channel(
        self,
        db: AsyncSession,
        chat_id: str,
        name: str,
        channel_type: str = "group",
        description: Optional[str] = None,
        send_signals: bool = True,
        send_ai: bool = True,
        send_news: bool = False,
        cooldown_sec: Optional[int] = None,
    ) -> TelegramChannel:
        channel = TelegramChannel(
            chat_id=chat_id,
            name=name,
            channel_type=channel_type,
            description=description,
            send_signals=send_signals,
            send_ai=send_ai,
            send_news=send_news,
            cooldown_sec=cooldown_sec,
        )
        db.add(channel)
        await db.flush()
        logger.info("Created Telegram channel %s (%s)", name, chat_id)
        return channel

    async def update_channel(
        self, db: AsyncSession, channel_id: int, **fields: Any
    ) -> Optional[TelegramChannel]:
        channel = await self.get_channel(db, channel_id)
        if not channel:
            return None
        for k, v in fields.items():
            if hasattr(channel, k):
                setattr(channel, k, v)
        await db.flush()
        return channel

    async def delete_channel(self, db: AsyncSession, channel_id: int) -> bool:
        channel = await self.get_channel(db, channel_id)
        if not channel:
            return False
        await db.delete(channel)
        await db.flush()
        logger.info("Deleted Telegram channel id=%d", channel_id)
        return True

    # ── Live Telegram validation ──────────────────────────────────────────────

    async def validate_chat(self, chat_id: str) -> dict[str, Any]:
        """
        Fetch chat info from Telegram to verify the bot has access.
        Returns a dict with type, title, member_count.
        """
        try:
            info = await self._client.get_chat(chat_id)
            chat_type = info.get("type", "unknown")
            title = info.get("title") or info.get("first_name", "Unknown")
            member_count: int = 0
            try:
                member_count = await self._client.get_chat_member_count(chat_id)
            except TelegramAPIError:
                pass
            return {
                "valid": True,
                "chat_id": chat_id,
                "type": chat_type,
                "title": title,
                "member_count": member_count,
            }
        except TelegramAPIError as exc:
            logger.warning("Channel validation failed for %s: %s", chat_id, exc)
            return {"valid": False, "chat_id": chat_id, "error": str(exc)}

    async def get_signal_channels(self, db: AsyncSession) -> list[TelegramChannel]:
        result = await db.execute(
            select(TelegramChannel).where(
                TelegramChannel.is_active == True,  # noqa: E712
                TelegramChannel.send_signals == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_ai_channels(self, db: AsyncSession) -> list[TelegramChannel]:
        result = await db.execute(
            select(TelegramChannel).where(
                TelegramChannel.is_active == True,  # noqa: E712
                TelegramChannel.send_ai == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())
