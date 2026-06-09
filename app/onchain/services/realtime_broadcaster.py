"""WebSocket broadcaster for on-chain realtime events."""

from __future__ import annotations

import logging
from typing import Any

from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


async def broadcast_onchain_events(
    chain: str,
    token_address: str,
    signals: list[dict[str, Any]],
) -> None:
    """Broadcast on-chain signals to all connected WebSocket clients."""
    for signal in signals:
        payload = {
            "type": "onchain_signal",
            "data": {
                "chain": chain,
                "token_address": token_address,
                **signal,
            },
        }
        await ws_manager.broadcast_all(payload)

        # Broadcast whale/large swap events separately
        signal_type = signal.get("signal_type", "")
        if signal_type in (
            "LARGE_BUY", "LARGE_SELL", "WHALE_BUY", "WHALE_SELL",
            "SMART_MONEY_ACCUMULATION", "LIQUIDITY_REMOVAL",
        ):
            await ws_manager.broadcast_all({
                "type": "onchain_whale",
                "data": {
                    "chain": chain,
                    "token_address": token_address,
                    **signal,
                },
            })


async def broadcast_large_swap(
    chain: str,
    token_address: str,
    trade: dict[str, Any],
) -> None:
    await ws_manager.broadcast_all({
        "type": "onchain_trade",
        "data": {
            "chain": chain,
            "token_address": token_address,
            **trade,
        },
    })
