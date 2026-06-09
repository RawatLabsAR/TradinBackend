"""
Market service — business logic layer over the active data provider.
Handles caching, data normalisation, and timeframe mapping.
Provider (Coinbase or Gate.io) is selected at runtime via DATA_PROVIDER in .env.
"""

import time
import logging
from typing import Optional

from app.core.cache import cache
from app.core.config import settings
from app.schemas.candle import TIMEFRAME_CONFIG, TimeframeType, COINBASE_GRANULARITY_MAP

SHORT_CACHE_TIMEFRAMES = ("1m", "5m", "15m", "1H", "4H", "1D")


def _provider():
    """Return the active data-source service module."""
    from app.providers.registry import get_market_provider
    return get_market_provider()


logger = logging.getLogger(__name__)


async def get_top_products(limit: int = 50) -> list[dict]:
    """Return top SPOT products sorted by 24h volume, with in-memory caching."""
    cache_key = f"top_products:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _provider().get_products(
        limit=limit,
        product_type="SPOT",
    )
    products = [
        p for p in data.get("products", [])
        if p.get("quote_currency_id") == "USD"
        and not p.get("is_disabled", False)
        and not p.get("trading_disabled", False)
        and p.get("status") == "online"
    ]
    cache.set(cache_key, products, settings.CACHE_TTL_PRODUCTS)
    return products


async def search_products(query: str) -> list[dict]:
    """Search products by symbol or name (client-side filtering after fetching).

    Fetches the full spot + swap + futures catalog so every listed market is searchable.
    """
    cache_key = "all_products_v2"
    all_products = cache.get(cache_key)

    if all_products is None:
        data = await _provider().get_products(limit=0, product_type="ALL")
        all_products = [
            p for p in data.get("products", [])
            if not p.get("is_disabled", False)
            and not p.get("trading_disabled", False)
        ]
        cache.set(cache_key, all_products, settings.CACHE_TTL_PRODUCTS)

    if not query:
        return all_products

    q = query.lower()
    return [
        p for p in all_products
        if q in p.get("product_id", "").lower()
        or q in p.get("base_name", "").lower()
        or q in p.get("base_currency_id", "").lower()
        or q in p.get("display_name", "").lower()
        or q in p.get("product_type", "").lower()
    ]


async def get_product_detail(product_id: str) -> Optional[dict]:
    """Get single product with caching."""
    cache_key = f"product:{product_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await _provider().get_product(product_id)
        cache.set(cache_key, data, settings.CACHE_TTL_PRODUCTS)
        return data
    except Exception as exc:
        logger.error("Failed to fetch product %s: %s", product_id, exc)
        return None


def _resolve_granularity(config: dict) -> str:
    """Map internal granularity to a provider-supported value."""
    granularity = config["granularity"]
    return COINBASE_GRANULARITY_MAP.get(granularity, granularity)


async def get_candles(
    product_id: str,
    timeframe: TimeframeType,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Fetch historical candles for a product/timeframe pair.

    Timeframe keys use standard bar intervals: 1m, 5m, 15m, 1H, 4H, 1D, 1W, 1M.
    """
    config = TIMEFRAME_CONFIG[timeframe]
    bar_limit = limit or config["default_bars"]
    interval_seconds = config["interval_seconds"]
    granularity = _resolve_granularity(config)
    gate_interval = config["gate_interval"]

    cache_key = f"candles:{product_id}:{timeframe}:{bar_limit}"
    ttl = (
        settings.CACHE_TTL_CANDLES_SHORT
        if timeframe in SHORT_CACHE_TIMEFRAMES
        else settings.CACHE_TTL_CANDLES_LONG
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    end_ts = int(time.time())
    start_ts = end_ts - (interval_seconds * bar_limit)

    try:
        provider = _provider()
        if settings.DATA_PROVIDER.lower() == "gate":
            data = await provider.get_candles(
                product_id, start_ts, end_ts, granularity, gate_interval=gate_interval
            )
        else:
            data = await provider.get_candles(product_id, start_ts, end_ts, granularity)

        candles = data.get("candles", [])
        candles = list(reversed(candles))
        if len(candles) > bar_limit:
            candles = candles[-bar_limit:]
        cache.set(cache_key, candles, ttl)
        return candles
    except Exception as exc:
        logger.error("Failed to fetch candles for %s/%s: %s", product_id, timeframe, exc)
        return []


async def get_market_trades(product_id: str, limit: int = 25) -> dict:
    """Get recent trades for a product (used for best bid/ask)."""
    cache_key = f"trades:{product_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await _provider().get_market_trades(product_id, limit)
        cache.set(cache_key, data, 10)
        return data
    except Exception as exc:
        logger.error("Failed to fetch trades for %s: %s", product_id, exc)
        return {}
