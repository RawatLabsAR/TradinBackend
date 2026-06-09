"""
Provider-agnostic WebSocket client registry.

main.py stores whichever WS client is active here on startup.
routes/ws.py reads from here to forward subscribe/unsubscribe calls
without knowing which exchange is behind it.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.websocket.coinbase_ws import CoinbaseWSClient
    from app.websocket.gate_ws import GateWSClient

_active_client = None


def set_active_ws_client(client) -> None:
    global _active_client
    _active_client = client


def get_active_ws_client():
    """Return the currently active exchange WS client (Coinbase or Gate)."""
    return _active_client
