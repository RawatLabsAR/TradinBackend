"""Runtime data-provider selection (Coinbase vs Gate.io)."""

from app.providers.registry import (
    build_ws_client,
    close_market_session,
    get_market_provider,
    is_gate_provider,
)

__all__ = [
    "build_ws_client",
    "close_market_session",
    "get_market_provider",
    "is_gate_provider",
]
