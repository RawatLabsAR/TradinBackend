"""
Single registry for exchange provider selection.

Used by market_service (REST) and main.py (WebSocket client).
"""

from __future__ import annotations

from typing import Any, Callable

from app.core.config import settings


def is_gate_provider() -> bool:
    return settings.DATA_PROVIDER.lower() == "gate"


def get_market_provider():
    """Return the active REST market data service module."""
    if is_gate_provider():
        import app.services.gate_service as svc
    else:
        import app.services.coinbase_service as svc
    return svc


async def close_market_session() -> None:
    await get_market_provider().close_session()


def build_ws_client(on_ticker: Callable[[dict], Any]):
    """Instantiate the WebSocket client for the configured provider."""
    if is_gate_provider():
        from app.websocket.gate_ws import GateWSClient
        import app.websocket.gate_ws as ws_module

        client = GateWSClient(on_ticker=on_ticker)
        ws_module.gate_ws_client = client
        return client, "gate"

    from app.websocket.coinbase_ws import CoinbaseWSClient
    import app.websocket.coinbase_ws as ws_module

    client = CoinbaseWSClient(on_ticker=on_ticker)
    ws_module.coinbase_ws_client = client
    return client, "coinbase"
