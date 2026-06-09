"""
Gate.io WebSocket client for spot, perpetual swap, and delivery futures.

Maintains one connection per market type:
  - spot.tickers     on wss://api.gateio.ws/ws/v4/
  - futures.tickers  on wss://fx-ws.gateio.ws/v4/ws/usdt          (perp/swap)
  - futures.tickers  on wss://fx-ws.gateio.ws/v4/ws/delivery/usdt  (delivery)

All incoming ticker events are normalised to the same dict shape that the
Coinbase WS client produces so the frontend manager receives identical data
regardless of which provider or market type is active.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

import websockets

from app.core.config import settings
from app.services.gate_service import _parse_product_id, _contract_to_product_id

logger = logging.getLogger(__name__)

OnTickerCallback = Callable[[dict], Awaitable[None]]

_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_BACKOFF_FACTOR = 2.0
_PING_INTERVAL = 15.0  # seconds


def _norm_spot_ws_ticker(result: dict) -> dict:
    """Gate spot.tickers WS result → Coinbase-shaped TickerData dict."""
    pair = result.get("currency_pair", "")
    base = pair.split("_")[0] if "_" in pair else pair
    product_id = f"{base}-USD"
    return _build_ticker(product_id, result)


def _norm_derivative_ws_ticker(result: dict, product_type: str) -> dict:
    """Gate futures.tickers WS result → Coinbase-shaped TickerData dict."""
    contract = result.get("contract", "")
    product_id = _contract_to_product_id(contract, product_type)
    return _build_ticker(product_id, result, is_derivative=True)


def _build_ticker(product_id: str, result: dict, is_derivative: bool = False) -> dict:
    volume = (
        str(result.get("volume_24h", "0"))
        if is_derivative
        else result.get("base_volume", "0")
    )
    return {
        "product_id": product_id,
        "price": result.get("last", "0"),
        "volume_24_h": volume,
        "low_24_h": result.get("low_24h", "0"),
        "high_24_h": result.get("high_24h", "0"),
        "low_52_w": "0",
        "high_52_w": "0",
        "price_percent_chg_24_h": result.get("change_percentage", "0"),
        "best_bid": result.get("highest_bid", ""),
        "best_ask": result.get("lowest_ask", ""),
        "best_bid_quantity": "",
        "best_ask_quantity": "",
    }


@dataclass
class _MarketStream:
    name: str
    url: str
    ticker_channel: str
    ping_channel: str
    product_type: str
    subscribed: dict[str, str] = field(default_factory=dict)  # product_id → contract
    pending_subscribe: dict[str, str] = field(default_factory=dict)
    pending_unsubscribe: dict[str, str] = field(default_factory=dict)


class GateWSClient:
    def __init__(self, on_ticker: OnTickerCallback) -> None:
        self._on_ticker = on_ticker
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._streams: dict[str, _MarketStream] = {
            "spot": _MarketStream(
                name="spot",
                url=settings.GATE_WS_URL,
                ticker_channel="spot.tickers",
                ping_channel="spot.ping",
                product_type="SPOT",
            ),
            "futures": _MarketStream(
                name="futures",
                url=settings.GATE_FUTURES_WS_URL,
                ticker_channel="futures.tickers",
                ping_channel="futures.ping",
                product_type="SWAP",
            ),
            "delivery": _MarketStream(
                name="delivery",
                url=settings.GATE_DELIVERY_WS_URL,
                ticker_channel="futures.tickers",
                ping_channel="futures.ping",
                product_type="FUTURES",
            ),
        }

        for product_id in settings.default_product_list:
            self._queue_subscribe(product_id.upper())

    async def start(self) -> None:
        self._running = True
        for stream in self._streams.values():
            task = asyncio.create_task(self._run_stream_forever(stream))
            self._tasks.append(task)
        logger.info("Gate.io WS client started (spot + futures + delivery)")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Gate.io WS client stopped")

    def add_products(self, product_ids: list[str]) -> None:
        for product_id in product_ids:
            self._queue_subscribe(product_id.upper())

    def remove_products(self, product_ids: list[str]) -> None:
        for product_id in product_ids:
            self._queue_unsubscribe(product_id.upper())

    def _queue_subscribe(self, product_id: str) -> None:
        market, contract, _ = _parse_product_id(product_id)
        stream = self._streams[market]
        if product_id in stream.subscribed:
            return
        stream.pending_unsubscribe.pop(product_id, None)
        stream.pending_subscribe[product_id] = contract

    def _queue_unsubscribe(self, product_id: str) -> None:
        market, _, _ = _parse_product_id(product_id)
        stream = self._streams[market]
        if product_id not in stream.subscribed:
            stream.pending_subscribe.pop(product_id, None)
            return
        stream.pending_unsubscribe[product_id] = stream.subscribed[product_id]

    async def _run_stream_forever(self, stream: _MarketStream) -> None:
        backoff = _INITIAL_BACKOFF
        while self._running:
            try:
                await self._connect_and_listen(stream)
                backoff = _INITIAL_BACKOFF
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "Gate.io %s WS disconnected: %s — reconnecting in %.1fs",
                    stream.name,
                    exc,
                    backoff,
                )
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)

    async def _connect_and_listen(self, stream: _MarketStream) -> None:
        logger.info("Connecting to Gate.io %s WS: %s", stream.name, stream.url)
        async with websockets.connect(
            stream.url,
            ping_interval=None,
            close_timeout=10,
        ) as ws:
            logger.info("Gate.io %s WS connected", stream.name)

            if stream.subscribed:
                await self._send_subscribe(ws, stream, list(stream.subscribed.items()))
            if stream.pending_subscribe:
                products = list(stream.pending_subscribe.items())
                stream.pending_subscribe.clear()
                await self._send_subscribe(ws, stream, products)

            ping_task = asyncio.create_task(self._ping_loop(ws, stream))
            try:
                async for raw in ws:
                    if not self._running:
                        break
                    await self._handle_message(ws, stream, raw)
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

    async def _ping_loop(
        self, ws: websockets.WebSocketClientProtocol, stream: _MarketStream
    ) -> None:
        while self._running:
            await asyncio.sleep(_PING_INTERVAL)
            try:
                await ws.send(json.dumps({
                    "time": int(time.time()),
                    "channel": stream.ping_channel,
                }))
            except Exception:
                break

    async def _send_subscribe(
        self,
        ws: websockets.WebSocketClientProtocol,
        stream: _MarketStream,
        products: list[tuple[str, str]],
    ) -> None:
        if not products:
            return
        contracts = [contract for _, contract in products]
        msg = {
            "time": int(time.time()),
            "channel": stream.ticker_channel,
            "event": "subscribe",
            "payload": contracts,
        }
        await ws.send(json.dumps(msg))
        for product_id, contract in products:
            stream.subscribed[product_id] = contract
        logger.debug("Gate.io %s WS subscribed to %s", stream.name, contracts)

    async def _send_unsubscribe(
        self,
        ws: websockets.WebSocketClientProtocol,
        stream: _MarketStream,
        products: list[tuple[str, str]],
    ) -> None:
        if not products:
            return
        contracts = [contract for _, contract in products]
        msg = {
            "time": int(time.time()),
            "channel": stream.ticker_channel,
            "event": "unsubscribe",
            "payload": contracts,
        }
        await ws.send(json.dumps(msg))
        for product_id, _ in products:
            stream.subscribed.pop(product_id, None)

    async def _handle_message(
        self,
        ws: websockets.WebSocketClientProtocol,
        stream: _MarketStream,
        raw: str,
    ) -> None:
        if stream.pending_subscribe:
            products = list(stream.pending_subscribe.items())
            stream.pending_subscribe.clear()
            await self._send_subscribe(ws, stream, products)

        if stream.pending_unsubscribe:
            products = [
                (product_id, contract)
                for product_id, contract in stream.pending_unsubscribe.items()
            ]
            stream.pending_unsubscribe.clear()
            await self._send_unsubscribe(ws, stream, products)

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        channel = msg.get("channel", "")
        event = msg.get("event", "")

        if channel == stream.ticker_channel and event == "update":
            result = msg.get("result", {})
            items = result if isinstance(result, list) else [result]
            for item in items:
                if stream.name == "spot":
                    if item.get("currency_pair"):
                        await self._on_ticker(_norm_spot_ws_ticker(item))
                elif item.get("contract"):
                    await self._on_ticker(
                        _norm_derivative_ws_ticker(item, stream.product_type)
                    )

        elif channel == stream.ping_channel.replace("ping", "pong"):
            pass

        elif event == "error":
            logger.error("Gate.io %s WS error: %s", stream.name, msg.get("message", msg))


gate_ws_client: Optional[GateWSClient] = None


def get_gate_ws_client() -> Optional[GateWSClient]:
    return gate_ws_client
