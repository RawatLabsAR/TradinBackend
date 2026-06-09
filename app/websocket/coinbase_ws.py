"""
Coinbase Advanced Trade WebSocket client.

Connects to wss://advanced-trade-ws.coinbase.com and subscribes to:
  - ticker_batch (price updates every 5 seconds, no auth required)
  - heartbeats   (keep connection alive, no auth required)

On every ticker update, the callback `on_ticker` is invoked with
the normalised ticker dict so the frontend manager can fan it out.

Reconnect strategy: exponential backoff, capped at 60 s.
"""

import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.config import settings

logger = logging.getLogger(__name__)

OnTickerCallback = Callable[[dict], Awaitable[None]]

_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_BACKOFF_FACTOR = 2.0


class CoinbaseWSClient:
    def __init__(self, on_ticker: OnTickerCallback) -> None:
        self._on_ticker = on_ticker
        self._subscribed_products: set[str] = set(settings.default_product_list)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._pending_subscriptions: set[str] = set()
        self._pending_unsubscriptions: set[str] = set()
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        logger.info("Coinbase WS client started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        logger.info("Coinbase WS client stopped")

    def add_products(self, product_ids: list[str]) -> None:
        new = set(product_ids) - self._subscribed_products
        if new:
            self._subscribed_products.update(new)
            self._pending_subscriptions.update(new)

    def remove_products(self, product_ids: list[str]) -> None:
        remove = set(product_ids) & self._subscribed_products
        if remove:
            self._subscribed_products -= remove
            self._pending_unsubscriptions.update(remove)

    async def _run_forever(self) -> None:
        backoff = _INITIAL_BACKOFF
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = _INITIAL_BACKOFF  # reset on clean exit
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "Coinbase WS disconnected: %s — reconnecting in %.1fs",
                    exc,
                    backoff,
                )
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)

    async def _connect_and_listen(self) -> None:
        logger.info("Connecting to Coinbase WS: %s", settings.COINBASE_WS_URL)
        async with websockets.connect(
            settings.COINBASE_WS_URL,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
        ) as ws:
            self._ws = ws
            logger.info("Coinbase WS connected")

            await self._send_subscribe(ws, list(self._subscribed_products))

            async for raw in ws:
                if not self._running:
                    break
                await self._handle_message(ws, raw)

    async def _send_subscribe(
        self, ws: websockets.WebSocketClientProtocol, product_ids: list[str]
    ) -> None:
        if not product_ids:
            return
        for channel in ("heartbeats", "ticker_batch"):
            msg: dict = {"type": "subscribe", "channel": channel}
            if channel != "heartbeats":
                msg["product_ids"] = product_ids
            await ws.send(json.dumps(msg))
            logger.debug("Subscribed to channel=%s products=%s", channel, product_ids)

    async def _send_unsubscribe(
        self, ws: websockets.WebSocketClientProtocol, product_ids: list[str]
    ) -> None:
        if not product_ids:
            return
        msg = {
            "type": "unsubscribe",
            "channel": "ticker_batch",
            "product_ids": product_ids,
        }
        await ws.send(json.dumps(msg))

    async def _handle_message(
        self, ws: websockets.WebSocketClientProtocol, raw: str
    ) -> None:
        # Process pending subscribe/unsubscribe requests
        if self._pending_subscriptions:
            products = list(self._pending_subscriptions)
            self._pending_subscriptions.clear()
            await self._send_subscribe(ws, products)

        if self._pending_unsubscriptions:
            products = list(self._pending_unsubscriptions)
            self._pending_unsubscriptions.clear()
            await self._send_unsubscribe(ws, products)

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        channel = msg.get("channel", "")

        if channel in ("ticker", "ticker_batch"):
            for event in msg.get("events", []):
                for ticker in event.get("tickers", []):
                    await self._on_ticker(ticker)

        elif channel == "heartbeats":
            pass  # keep-alive acknowledged

        elif msg.get("type") == "error":
            logger.error("Coinbase WS error: %s", msg.get("message", "unknown"))

        elif msg.get("type") == "subscriptions":
            logger.info("Coinbase WS subscriptions confirmed")


coinbase_ws_client: Optional[CoinbaseWSClient] = None


def get_coinbase_ws_client() -> Optional[CoinbaseWSClient]:
    return coinbase_ws_client
