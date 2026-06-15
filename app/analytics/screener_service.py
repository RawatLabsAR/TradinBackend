"""Market screener with filters."""

from __future__ import annotations

from app.core.cache import cache
from app.services import market_service


async def run_screener(
    min_volume_24h: float | None = None,
    max_volume_24h: float | None = None,
    min_change_24h: float | None = None,
    max_change_24h: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_by: str = "volume_24h",
    sort_dir: str = "desc",
    limit: int = 50,
) -> dict:
    cache_key = f"analytics:screener:{min_volume_24h}:{min_change_24h}:{sort_by}:{limit}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    products = await market_service.get_top_products(limit=200)
    items = []

    for p in products:
        price = float(p.get("price", 0) or 0)
        vol = float(p.get("volume_24h", 0) or 0)
        change = float(p.get("price_percentage_change_24h", 0) or 0)

        if min_volume_24h is not None and vol < min_volume_24h:
            continue
        if max_volume_24h is not None and vol > max_volume_24h:
            continue
        if min_change_24h is not None and change < min_change_24h:
            continue
        if max_change_24h is not None and change > max_change_24h:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue

        items.append({
            "product_id": p.get("product_id", ""),
            "base_name": p.get("base_name", p.get("base_currency_id", "")),
            "price": price,
            "change_24h_pct": change,
            "volume_24h": vol,
            "high_24h": float(p.get("high_24_h", 0) or 0) or None,
            "low_24h": float(p.get("low_24_h", 0) or 0) or None,
        })

    reverse = sort_dir == "desc"
    sort_key = sort_by if sort_by in ("volume_24h", "change_24h_pct", "price") else "volume_24h"
    items.sort(key=lambda x: x.get(sort_key, 0) or 0, reverse=reverse)
    items = items[:limit]

    result = {
        "total": len(items),
        "items": items,
        "filters_applied": {
            "min_volume_24h": min_volume_24h,
            "max_volume_24h": max_volume_24h,
            "min_change_24h": min_change_24h,
            "max_change_24h": max_change_24h,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "limit": limit,
        },
    }
    cache.set(cache_key, result, 60)
    return result
