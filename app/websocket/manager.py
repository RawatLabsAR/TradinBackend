"""
Frontend WebSocket manager.

Manages all active frontend client connections and fans out
live ticker data received from the Coinbase WebSocket client.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # client_id → WebSocket
        self._clients: dict[str, WebSocket] = {}
        # product_id → set of client_ids
        self._subscriptions: dict[str, set[str]] = {}
        # client_id → set of product_ids
        self._client_products: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        client_id = str(uuid.uuid4())
        async with self._lock:
            self._clients[client_id] = websocket
            self._client_products[client_id] = set()
        logger.info("Client connected: %s (total: %d)", client_id, len(self._clients))
        return client_id

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            ws = self._clients.pop(client_id, None)
            subscribed = self._client_products.pop(client_id, set())
            for product_id in subscribed:
                if product_id in self._subscriptions:
                    self._subscriptions[product_id].discard(client_id)
                    if not self._subscriptions[product_id]:
                        del self._subscriptions[product_id]
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("Client disconnected: %s (total: %d)", client_id, len(self._clients))

    async def subscribe(self, client_id: str, product_ids: list[str]) -> None:
        async with self._lock:
            if client_id not in self._clients:
                return
            for product_id in product_ids:
                if product_id not in self._subscriptions:
                    self._subscriptions[product_id] = set()
                self._subscriptions[product_id].add(client_id)
                self._client_products[client_id].add(product_id)
        logger.debug(
            "Client %s subscribed to %s",
            client_id,
            product_ids,
        )

    async def unsubscribe(self, client_id: str, product_ids: list[str]) -> None:
        async with self._lock:
            for product_id in product_ids:
                if product_id in self._subscriptions:
                    self._subscriptions[product_id].discard(client_id)
                    if not self._subscriptions[product_id]:
                        del self._subscriptions[product_id]
                if client_id in self._client_products:
                    self._client_products[client_id].discard(product_id)

    async def broadcast_signal(
        self, product_id: str, signal: dict
    ) -> None:
        """Broadcast a Pine Script strategy signal to all clients watching this product."""
        async with self._lock:
            client_ids = list(self._subscriptions.get(product_id, set()))

        if not client_ids:
            return

        message = json.dumps({"type": "strategy_signal", "data": signal})
        dead: list[str] = []
        await asyncio.gather(
            *[self._send_to(cid, message, dead) for cid in client_ids],
            return_exceptions=True,
        )
        for cid in dead:
            await self.disconnect(cid)

    async def broadcast_ticker(self, product_id: str, ticker: dict) -> None:
        """Send a ticker update to all clients watching this product."""
        async with self._lock:
            client_ids = list(self._subscriptions.get(product_id, set()))

        if not client_ids:
            return

        message = json.dumps({"type": "ticker", "data": ticker})
        dead_clients: list[str] = []

        await asyncio.gather(
            *[self._send_to(cid, message, dead_clients) for cid in client_ids],
            return_exceptions=True,
        )

        for cid in dead_clients:
            await self.disconnect(cid)

    async def broadcast_all(self, message: dict) -> None:
        """Broadcast a message to ALL connected clients."""
        async with self._lock:
            client_ids = list(self._clients.keys())

        payload = json.dumps(message)
        dead: list[str] = []
        await asyncio.gather(
            *[self._send_to(cid, payload, dead) for cid in client_ids],
            return_exceptions=True,
        )
        for cid in dead:
            await self.disconnect(cid)

    async def _send_to(
        self, client_id: str, message: str, dead_clients: list[str]
    ) -> None:
        ws = self._clients.get(client_id)
        if ws is None:
            return
        try:
            await ws.send_text(message)
        except Exception:
            dead_clients.append(client_id)

    async def send_to_client(self, client_id: str, message: dict) -> None:
        ws = self._clients.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(client_id)

    @property
    def active_connections(self) -> int:
        return len(self._clients)

    @property
    def subscribed_products(self) -> list[str]:
        return list(self._subscriptions.keys())


ws_manager = ConnectionManager()
