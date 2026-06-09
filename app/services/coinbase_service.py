"""
Coinbase Advanced Trade REST API service.

Public endpoints (no authentication required):
  GET /api/v3/brokerage/market/products
  GET /api/v3/brokerage/market/products/{product_id}
  GET /api/v3/brokerage/market/products/{product_id}/candles
  GET /api/v3/brokerage/market/products/{product_id}/ticker
  GET /api/v3/brokerage/time
"""

import asyncio
import logging
from typing import Any, Optional
import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)

_session: Optional[aiohttp.ClientSession] = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        _session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Bypass the 1-second public endpoint cache
                "Cache-Control": "no-cache",
            },
        )
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _get(
    path: str,
    params: Optional[dict] = None,
    retries: int = 3,
    backoff: float = 1.0,
) -> Any:
    url = f"{settings.COINBASE_API_BASE_URL}{path}"
    session = _get_session()

    for attempt in range(retries):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    wait = backoff * (2 ** attempt)
                    logger.warning("Rate limited by Coinbase, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error("Coinbase API error %d: %s", resp.status, text)
                    resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            if attempt == retries - 1:
                raise
            wait = backoff * (2 ** attempt)
            logger.warning("Coinbase request failed (attempt %d): %s", attempt + 1, exc)
            await asyncio.sleep(wait)

    raise RuntimeError(f"Coinbase API request failed after {retries} attempts: {path}")


async def get_products(
    limit: int = 250,
    offset: int = 0,
    product_type: str = "SPOT",
    product_ids: Optional[list[str]] = None,
) -> dict:
    """List public products. Pass limit=0 to fetch the full catalog."""
    ptype = product_type.upper()
    if ptype in ("SWAP", "FUTURES"):
        return {"products": []}
    if ptype == "ALL":
        return await get_products(
            limit=limit,
            offset=offset,
            product_type="SPOT",
            product_ids=product_ids,
        )

    if limit <= 0:
        page_size = 250
        all_products: list[dict] = []
        page_offset = offset
        while True:
            params: dict[str, Any] = {
                "limit": page_size,
                "offset": page_offset,
                "product_type": product_type,
                "products_sort_order": "PRODUCTS_SORT_ORDER_VOLUME_24H_DESCENDING",
            }
            if product_ids:
                params["product_ids"] = product_ids
            data = await _get("/market/products", params=params)
            batch = data.get("products", [])
            all_products.extend(batch)
            if len(batch) < page_size:
                break
            page_offset += page_size
        return {"products": all_products}

    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "product_type": product_type,
        "products_sort_order": "PRODUCTS_SORT_ORDER_VOLUME_24H_DESCENDING",
    }
    if product_ids:
        params["product_ids"] = product_ids
    return await _get("/market/products", params=params)


async def get_product(product_id: str) -> dict:
    """Get a single public product."""
    return await _get(f"/market/products/{product_id}")


async def get_candles(
    product_id: str,
    start: int,
    end: int,
    granularity: str,
) -> dict:
    """
    Get historical candles for a product.

    granularity options:
      ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE,
      ONE_HOUR, TWO_HOUR, SIX_HOUR, ONE_DAY
    Max 350 candles per request.
    """
    params = {
        "start": str(start),
        "end": str(end),
        "granularity": granularity,
    }
    return await _get(f"/market/products/{product_id}/candles", params=params)


async def get_market_trades(product_id: str, limit: int = 25) -> dict:
    """Get recent market trades for a product."""
    return await _get(
        f"/market/products/{product_id}/ticker", params={"limit": limit}
    )


async def get_server_time() -> dict:
    """Get Coinbase server time."""
    return await _get("/time")
