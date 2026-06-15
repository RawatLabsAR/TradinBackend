"""Market events from CoinGecko trending + free global data (no API key)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.analytics.http_client import fetch_json
from app.core.cache import cache

logger = logging.getLogger(__name__)


async def _coingecko_trending_events() -> list[dict]:
    try:
        data = await fetch_json("https://api.coingecko.com/api/v3/search/trending")
        coins = data.get("coins", []) if isinstance(data, dict) else []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = []
        for i, entry in enumerate(coins[:10]):
            coin = entry.get("item", entry)
            symbol = (coin.get("symbol") or "?").upper()
            name = coin.get("name") or symbol
            rank = coin.get("market_cap_rank")
            events.append({
                "id": f"cg-trending-{symbol.lower()}-{i}",
                "title": f"Trending: {name} ({symbol})",
                "symbol": symbol,
                "event_type": "trending",
                "date": today,
                "impact": "medium" if rank and rank < 100 else "low",
                "description": f"CoinGecko trending search #{i + 1}. Market cap rank: {rank or 'N/A'}.",
            })
        return events
    except Exception as exc:
        logger.warning("CoinGecko trending fetch failed: %s", exc)
        return []


async def _coingecko_global_event() -> dict | None:
    try:
        data = await fetch_json("https://api.coingecko.com/api/v3/global")
        stats = data.get("data", {}) if isinstance(data, dict) else {}
        cap_change = stats.get("market_cap_change_percentage_24h_usd")
        if cap_change is None:
            return None
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        impact = "high" if abs(float(cap_change)) > 5 else "medium"
        return {
            "id": "cg-global-mcap",
            "title": f"Global Market Cap {'Up' if float(cap_change) >= 0 else 'Down'} {abs(float(cap_change)):.1f}% (24h)",
            "symbol": "BTC",
            "event_type": "market",
            "date": today,
            "impact": impact,
            "description": (
                f"Total crypto market cap change (24h): {float(cap_change):+.2f}%. "
                "Source: CoinGecko free global endpoint."
            ),
        }
    except Exception as exc:
        logger.warning("CoinGecko global fetch failed: %s", exc)
        return None


async def get_events(symbol: str | None = None, limit: int = 20) -> dict:
    cache_key = f"analytics:events:{symbol}:{limit}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    items: list[dict] = []
    global_evt = await _coingecko_global_event()
    if global_evt:
        items.append(global_evt)
    items.extend(await _coingecko_trending_events())

    if symbol:
        sym = symbol.upper()
        items = [e for e in items if e["symbol"] == sym or e["symbol"] == "BTC"]

    items = items[:limit]
    result = {
        "items": items,
        "total": len(items),
        "source": "coingecko.com (free public API)",
    }
    cache.set(cache_key, result, 900)
    return result
