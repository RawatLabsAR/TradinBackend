"""Liquidation zones from live price + Gate.io OI (free public APIs)."""

from __future__ import annotations

from app.analytics.gate_futures import fetch_futures_tickers, open_interest_usd
from app.core.cache import cache
from app.services import market_service

_LEVERAGES = [5, 10, 20, 25, 50, 100]


async def _gate_open_interest_usd(symbol: str) -> float | None:
    try:
        ticker_map = await fetch_futures_tickers()
        contract = f"{symbol}_USDT"
        ticker = ticker_map.get(contract)
        if not ticker:
            return None
        _, usd = await open_interest_usd(contract, ticker)
        return usd
    except Exception:
        return None


async def get_liquidation_levels(product_id: str) -> dict:
    cache_key = f"analytics:liq:{product_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    product_id = product_id.upper()
    symbol = product_id.split("-")[0]
    detail = await market_service.get_product_detail(product_id)
    price = float(detail.get("price") or 0) if detail else 0
    oi_usd = await _gate_open_interest_usd(symbol)

    levels = []
    for lev in _LEVERAGES:
        long_liq = price * (1 - 1 / lev * 0.9) if price else 0
        short_liq = price * (1 + 1 / lev * 0.9) if price else 0
        weight = max(101 - lev, 1) / 100
        est_usd = (oi_usd or price * 5000) * weight / len(_LEVERAGES)
        levels.append({
            "price": round(long_liq, 2),
            "side": "long",
            "estimated_usd": round(est_usd, 0),
            "leverage": lev,
        })
        levels.append({
            "price": round(short_liq, 2),
            "side": "short",
            "estimated_usd": round(est_usd, 0),
            "leverage": lev,
        })

    levels.sort(key=lambda x: x["price"])
    result = {
        "product_id": product_id,
        "current_price": price,
        "open_interest_usd": oi_usd,
        "levels": levels,
        "source": "gate.io OI + leverage zones (free public API)",
        "note": "Zones weighted by Gate.io open interest (quanto-adjusted).",
    }
    cache.set(cache_key, result, 120)
    return result
