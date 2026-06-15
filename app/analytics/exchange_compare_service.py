"""Compare prices across exchanges (Coinbase + Gate.io free public APIs)."""

from __future__ import annotations

import logging

from app.analytics.http_client import fetch_json
from app.core.cache import cache
from app.core.config import settings
from app.services import market_service

logger = logging.getLogger(__name__)


async def _gate_price(base: str) -> dict | None:
    pair = f"{base}_USDT"
    try:
        data = await fetch_json(
            f"{settings.GATE_API_BASE_URL}/spot/tickers",
            params={"currency_pair": pair},
        )
        t = data[0] if isinstance(data, list) and data else data
        if not t:
            return None
        return {
            "exchange": "gate.io",
            "product_id": f"{base}-USD",
            "price": float(t.get("last", 0)),
            "volume_24h": float(t.get("quote_volume", 0) or 0),
            "change_24h_pct": float(t.get("change_percentage", 0) or 0),
        }
    except Exception as exc:
        logger.debug("Gate price fetch failed: %s", exc)
        return None


async def _coinbase_price(product_id: str) -> dict | None:
    try:
        data = await fetch_json(
            f"{settings.COINBASE_API_BASE_URL}/market/products/{product_id}/ticker"
        )
        trades = data.get("trades", [{}])
        price = float(trades[0].get("price", 0)) if trades else 0
        return {
            "exchange": "coinbase",
            "product_id": product_id,
            "price": price,
            "volume_24h": None,
            "change_24h_pct": None,
        }
    except Exception as exc:
        logger.debug("Coinbase price fetch failed: %s", exc)
        return None


async def compare_exchanges(symbol: str) -> dict:
    symbol = symbol.upper().replace("-USD", "")
    product_id = f"{symbol}-USD"
    cache_key = f"analytics:compare:{symbol}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    items = []
    cb = await _coinbase_price(product_id)
    if cb:
        items.append(cb)
    gate = await _gate_price(symbol)
    if gate:
        items.append(gate)

    if not items:
        detail = await market_service.get_product_detail(product_id)
        if detail:
            items.append({
                "exchange": settings.DATA_PROVIDER,
                "product_id": product_id,
                "price": float(detail.get("price", 0) or 0),
                "volume_24h": float(detail.get("volume_24h", 0) or 0),
                "change_24h_pct": float(detail.get("price_percentage_change_24h", 0) or 0),
            })

    spread_pct = 0.0
    arb = False
    if len(items) >= 2:
        prices = [i["price"] for i in items if i["price"]]
        if prices:
            min_p, max_p = min(prices), max(prices)
            mid = (min_p + max_p) / 2
            spread_pct = round((max_p - min_p) / mid * 100, 4) if mid else 0
            arb = spread_pct > 0.15

    result = {
        "symbol": symbol,
        "items": items,
        "spread_pct": spread_pct,
        "arb_opportunity": arb,
        "source": "coinbase.com + gate.io (free public APIs)",
    }
    cache.set(cache_key, result, 30)
    return result
