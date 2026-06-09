"""
High-level Telegram service.

Provides a single entry point that wires together the client,
formatter, and channel manager.  Import this in broadcast code.
"""
from __future__ import annotations

import logging
from typing import Optional, Any

from app.integrations.telegram.telegram_client import TelegramClient, TelegramAPIError
from app.integrations.telegram.message_formatter import (
    format_signal_alert,
    format_ai_insight,
    format_custom_message,
    render_template,
    format_system_notification,
)
from app.integrations.telegram.channel_manager import ChannelManager

logger = logging.getLogger(__name__)


class TelegramService:
    """
    Facade that combines client + formatter + channel manager.

    Lifecycle managed by the FastAPI lifespan (start/stop).
    """

    def __init__(self, token: str) -> None:
        self._client = TelegramClient(token)
        self.channel_manager = ChannelManager(self._client)

    async def start(self) -> None:
        await self._client.start()
        logger.info("TelegramService started")

    async def stop(self) -> None:
        await self._client.stop()
        logger.info("TelegramService stopped")

    # ── Send helpers ──────────────────────────────────────────────────────────

    async def send_raw(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        """Send a pre-formatted message directly."""
        return await self._client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
        )

    async def send_signal(
        self,
        chat_id: str | int,
        symbol: str,
        signal_type: str,
        strategy: str,
        timeframe: str,
        price: Optional[float] = None,
        reason: Optional[str] = None,
        sentiment: Optional[str] = None,
        ai_commentary: Optional[str] = None,
    ) -> dict[str, Any]:
        text = format_signal_alert(
            symbol=symbol,
            signal_type=signal_type,
            strategy=strategy,
            timeframe=timeframe,
            price=price,
            reason=reason,
            sentiment=sentiment,
            ai_commentary=ai_commentary,
        )
        return await self.send_raw(chat_id, text)

    async def send_ai_insight(
        self,
        chat_id: str | int,
        symbol: str,
        summary: str,
        sentiment: Optional[str] = None,
        confidence: Optional[float] = None,
        drivers: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        text = format_ai_insight(
            symbol=symbol,
            summary=summary,
            sentiment=sentiment,
            confidence=confidence,
            drivers=drivers,
        )
        return await self.send_raw(chat_id, text)

    async def send_template(
        self,
        chat_id: str | int,
        template_content: str,
        variables: dict[str, Any],
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        rendered = render_template(template_content, variables)
        return await self.send_raw(chat_id, rendered, parse_mode)

    async def test_connection(self) -> dict[str, Any]:
        """Verify bot token is valid and return bot info."""
        try:
            bot_info = await self._client.get_me()
            return {
                "ok": True,
                "bot_username": bot_info.get("username"),
                "bot_name": bot_info.get("first_name"),
                "bot_id": bot_info.get("id"),
            }
        except TelegramAPIError as exc:
            return {"ok": False, "error": str(exc)}

    async def validate_channel(self, chat_id: str) -> dict[str, Any]:
        return await self.channel_manager.validate_chat(chat_id)

    async def get_recent_updates(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent Telegram updates for chat discovery."""
        return await self._client.get_updates(limit=limit, timeout=0)

    @property
    def client(self) -> TelegramClient:
        return self._client


# ── Module-level singleton (initialised in lifespan) ─────────────────────────

_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    if _telegram_service is None:
        raise RuntimeError(
            "TelegramService not initialised. "
            "Call init_telegram_service() during app startup."
        )
    return _telegram_service


def init_telegram_service(token: str) -> TelegramService:
    global _telegram_service
    _telegram_service = TelegramService(token)
    return _telegram_service
