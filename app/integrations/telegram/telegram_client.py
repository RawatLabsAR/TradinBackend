"""
Low-level async Telegram Bot API HTTP client.

Wraps the Telegram Bot API with:
  - aiohttp sessions (reused across calls)
  - rate-limit handling (429 → Retry-After)
  - exponential back-off retries
  - structured logging
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds


class TelegramAPIError(Exception):
    def __init__(self, code: int, description: str) -> None:
        self.code = code
        self.description = description
        super().__init__(f"Telegram API error {code}: {description}")


class TelegramClient:
    """
    Async HTTP client for the Telegram Bot API.

    Usage:
        client = TelegramClient(token="BOT_TOKEN")
        await client.start()
        result = await client.send_message(chat_id="@channel", text="Hello!")
        await client.stop()
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = f"{TELEGRAM_API_BASE}/bot{token}"

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        logger.debug("TelegramClient session started")

    async def stop(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        logger.debug("TelegramClient session closed")

    async def _request(
        self,
        method: str,
        params: dict[str, Any],
        attempt: int = 0,
    ) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            await self.start()

        url = f"{self._base_url}/{method}"

        try:
            async with self._session.post(url, json=params) as resp:  # type: ignore[union-attr]
                data: dict = await resp.json()

                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning(
                        "Telegram rate-limited on %s — retrying in %ds", method, retry_after
                    )
                    await asyncio.sleep(retry_after)
                    if attempt < MAX_RETRIES:
                        return await self._request(method, params, attempt + 1)
                    raise TelegramAPIError(429, "Rate limit exceeded after retries")

                if not data.get("ok"):
                    code = data.get("error_code", 0)
                    desc = data.get("description", "Unknown error")

                    # Transient errors — retry with backoff
                    if code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
                        backoff = BASE_BACKOFF * (2 ** attempt)
                        logger.warning(
                            "Telegram server error %d on %s — retry %d in %.1fs",
                            code, method, attempt + 1, backoff,
                        )
                        await asyncio.sleep(backoff)
                        return await self._request(method, params, attempt + 1)

                    raise TelegramAPIError(code, desc)

                return data.get("result", {})

        except aiohttp.ClientError as exc:
            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Network error on Telegram %s — retry %d in %.1fs: %s",
                    method, attempt + 1, backoff, exc,
                )
                await asyncio.sleep(backoff)
                return await self._request(method, params, attempt + 1)
            raise

    # ── Public API methods ────────────────────────────────────────────────────

    async def get_me(self) -> dict[str, Any]:
        """Return bot info (useful for testing the token)."""
        return await self._request("getMe", {})

    async def get_updates(
        self,
        limit: int = 100,
        timeout: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch recent bot updates (used for chat discovery)."""
        result = await self._request(
            "getUpdates",
            {"limit": limit, "timeout": timeout},
        )
        return result if isinstance(result, list) else []

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
        disable_notification: bool = False,
        reply_markup: Optional[dict] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
        return await self._request("sendMessage", params)

    async def get_chat(self, chat_id: str | int) -> dict[str, Any]:
        """Fetch Telegram chat metadata (title, type, member count…)."""
        return await self._request("getChat", {"chat_id": chat_id})

    async def get_chat_member_count(self, chat_id: str | int) -> int:
        result = await self._request("getChatMemberCount", {"chat_id": chat_id})
        return int(result) if isinstance(result, int) else 0

    async def send_photo(
        self,
        chat_id: str | int,
        photo_url: str,
        caption: Optional[str] = None,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
            "parse_mode": parse_mode,
        }
        if caption:
            params["caption"] = caption
        return await self._request("sendPhoto", params)

    async def pin_message(self, chat_id: str | int, message_id: int) -> dict[str, Any]:
        return await self._request(
            "pinChatMessage",
            {"chat_id": chat_id, "message_id": message_id, "disable_notification": False},
        )
