"""Crypto Fear & Greed Index from Alternative.me (free, no API key)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.http_client import fetch_json
from app.core.cache import cache


async def get_fear_greed(limit: int = 30) -> dict:
    cache_key = f"analytics:fng:{limit}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = await fetch_json(
        "https://api.alternative.me/fng/",
        params={"limit": min(limit, 90), "format": "json"},
    )
    rows = data.get("data", []) if isinstance(data, dict) else []
    items = []
    for row in rows:
        items.append({
            "value": int(row.get("value", 0)),
            "classification": row.get("value_classification", ""),
            "timestamp": datetime.fromtimestamp(
                int(row.get("timestamp", 0)), tz=timezone.utc
            ).isoformat()
            if row.get("timestamp")
            else None,
        })

    current = items[0] if items else None
    result = {
        "current": current,
        "history": items,
        "source": "alternative.me (free)",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(cache_key, result, 3600)
    return result
