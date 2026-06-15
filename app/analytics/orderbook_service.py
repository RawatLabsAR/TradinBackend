"""Order book depth and imbalance."""

from __future__ import annotations

import logging

import aiohttp

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)


async def get_orderbook(product_id: str, depth: int = 20) -> dict:
    cache_key = f"analytics:book:{product_id}:{depth}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    product_id = product_id.upper()
    base = product_id.split("-")[0]
    bids: list[dict] = []
    asks: list[dict] = []

    try:
        if settings.DATA_PROVIDER == "gate":
            pair = f"{base}_USDT"
            url = f"{settings.GATE_API_BASE_URL}/spot/order_book"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params={"currency_pair": pair, "limit": depth}) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            bids = [{"price": float(p), "size": float(s)} for p, s in data.get("bids", [])]
            asks = [{"price": float(p), "size": float(s)} for p, s in data.get("asks", [])]
        else:
            url = f"{settings.COINBASE_API_BASE_URL}/market/product_book"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params={"product_id": product_id, "limit": depth}) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            book = data.get("pricebook", data)
            bids = [{"price": float(b["price"]), "size": float(b["size"])} for b in book.get("bids", [])]
            asks = [{"price": float(a["price"]), "size": float(a["size"])} for a in book.get("asks", [])]
    except Exception as exc:
        logger.warning("Order book fetch failed for %s: %s", product_id, exc)
        return {
            "product_id": product_id,
            "bids": [],
            "asks": [],
            "spread": 0,
            "spread_pct": 0,
            "bid_depth_usd": 0,
            "ask_depth_usd": 0,
            "imbalance": 0,
            "mid_price": 0,
            "source": settings.DATA_PROVIDER,
        }

    best_bid = bids[0]["price"] if bids else 0
    best_ask = asks[0]["price"] if asks else 0
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
    spread = best_ask - best_bid if best_bid and best_ask else 0
    spread_pct = (spread / mid * 100) if mid else 0

    bid_depth = sum(b["price"] * b["size"] for b in bids)
    ask_depth = sum(a["price"] * a["size"] for a in asks)
    total = bid_depth + ask_depth
    imbalance = ((bid_depth - ask_depth) / total) if total else 0

    result = {
        "product_id": product_id,
        "bids": bids[:depth],
        "asks": asks[:depth],
        "spread": round(spread, 4),
        "spread_pct": round(spread_pct, 4),
        "bid_depth_usd": round(bid_depth, 2),
        "ask_depth_usd": round(ask_depth, 2),
        "imbalance": round(imbalance, 4),
        "mid_price": round(mid, 4),
        "source": settings.DATA_PROVIDER,
    }
    cache.set(cache_key, result, 15)
    return result
