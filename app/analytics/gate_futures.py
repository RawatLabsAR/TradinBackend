"""Gate.io USDT futures helpers — OI uses contract quanto_multiplier (free public API)."""

from __future__ import annotations

import asyncio
import logging

from app.analytics.http_client import fetch_json
from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)

_MULTIPLIER_TTL = 3600
_TICKER_TTL = 30


async def contract_multiplier_map() -> dict[str, float]:
    return await _contract_multiplier_map()


async def _contract_multiplier_map() -> dict[str, float]:
    cache_key = "gate:mult:all"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        rows = await fetch_json(
            f"{settings.GATE_API_BASE_URL}/futures/usdt/contracts",
            timeout_sec=12,
        )
        out: dict[str, float] = {}
        if isinstance(rows, list):
            for row in rows:
                name = row.get("name") or row.get("contract") or ""
                if not name:
                    continue
                out[name] = float(
                    row.get("quanto_multiplier")
                    or row.get("contract_size")
                    or 1
                )
        cache.set(cache_key, out, _MULTIPLIER_TTL)
        return out
    except Exception as exc:
        logger.debug("Gate contracts list failed: %s", exc)
        return {}


async def _contract_multiplier(contract: str) -> float:
    mult_map = await _contract_multiplier_map()
    if contract in mult_map:
        return mult_map[contract]

    cache_key = f"gate:mult:{contract}"
    cached = cache.get(cache_key)
    if cached is not None:
        return float(cached)

    try:
        data = await fetch_json(
            f"{settings.GATE_API_BASE_URL}/futures/usdt/contracts/{contract}",
            timeout_sec=6,
        )
        mult = float(
            data.get("quanto_multiplier")
            or data.get("contract_size")
            or 1
        )
        cache.set(cache_key, mult, _MULTIPLIER_TTL)
        return mult
    except Exception as exc:
        logger.debug("Gate contract info failed for %s: %s", contract, exc)
        return 1.0


async def open_interest_usd(
    contract: str,
    ticker: dict,
    *,
    mult: float | None = None,
) -> tuple[float | None, float | None]:
    """
    Return (contracts/open interest size, usd value).

    Gate total_size is contract count; USD = total_size * quanto_multiplier * mark.
    """
    mark = float(ticker.get("mark_price") or ticker.get("last") or 0)
    total_size = float(ticker.get("total_size") or 0)
    if not mark or not total_size:
        return None, None

    if mult is None:
        mult = await _contract_multiplier(contract)
    base_amount = total_size * mult
    usd = round(base_amount * mark, 2)
    return base_amount, usd


async def fetch_futures_ticker(contract: str) -> dict | None:
    cache_key = f"gate:ticker:{contract}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await fetch_json(
            f"{settings.GATE_API_BASE_URL}/futures/usdt/tickers",
            params={"contract": contract},
            timeout_sec=8,
        )
        ticker: dict = {}
        if isinstance(data, list) and data:
            ticker = data[0]
        elif isinstance(data, dict):
            ticker = data
        if ticker.get("contract"):
            cache.set(cache_key, ticker, _TICKER_TTL)
            return ticker
    except Exception as exc:
        logger.debug("Gate ticker fetch failed for %s: %s", contract, exc)
    return None


async def fetch_futures_tickers(contracts: list[str] | None = None) -> dict[str, dict]:
    """Contract name → ticker dict. Pass contracts to fetch only what you need."""
    if contracts:
        results = await asyncio.gather(*(fetch_futures_ticker(c) for c in contracts))
        return {c: t for c, t in zip(contracts, results) if t}

    tickers = await fetch_json(
        f"{settings.GATE_API_BASE_URL}/futures/usdt/tickers",
        timeout_sec=20,
    )
    if not isinstance(tickers, list):
        return {}
    return {t.get("contract", ""): t for t in tickers if t.get("contract")}


async def enrich_ticker_oi(
    contract: str,
    ticker: dict,
    *,
    mult_map: dict[str, float] | None = None,
) -> dict:
    """Add normalized open_interest and open_interest_usd to a ticker snapshot."""
    mult = mult_map.get(contract) if mult_map else None
    oi_base, oi_usd = await open_interest_usd(contract, ticker, mult=mult)
    return {
        **ticker,
        "open_interest": oi_base,
        "open_interest_usd": oi_usd,
    }
