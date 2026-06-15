"""Global market overview from CoinGecko free API."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.http_client import fetch_json
from app.core.cache import cache


async def get_global_overview() -> dict:
    cache_key = "analytics:global:coingecko"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = await fetch_json("https://api.coingecko.com/api/v3/global")
    stats = data.get("data", {}) if isinstance(data, dict) else {}

    result = {
        "total_market_cap_usd": stats.get("total_market_cap", {}).get("usd"),
        "total_volume_24h_usd": stats.get("total_volume", {}).get("usd"),
        "btc_dominance_pct": stats.get("market_cap_percentage", {}).get("btc"),
        "eth_dominance_pct": stats.get("market_cap_percentage", {}).get("eth"),
        "market_cap_change_24h_pct": stats.get("market_cap_change_percentage_24h_usd"),
        "active_cryptocurrencies": stats.get("active_cryptocurrencies"),
        "markets": stats.get("markets"),
        "source": "coingecko.com (free)",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(cache_key, result, 300)
    return result
