"""Funding rates & OI from Gate.io + OKX public APIs (free, no keys)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.analytics.gate_futures import (
    contract_multiplier_map,
    enrich_ticker_oi,
    fetch_futures_tickers,
)
from app.analytics.http_client import fetch_json
from app.core.cache import cache

logger = logging.getLogger(__name__)

_DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "LINK", "ADA"]


async def _gate_funding(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        contracts = [f"{sym}_USDT" for sym in symbols]
        mult_map, ticker_map = await asyncio.gather(
            contract_multiplier_map(),
            fetch_futures_tickers(contracts),
        )
        tasks = []
        sym_contracts: list[tuple[str, str, dict]] = []
        for sym in symbols:
            contract = f"{sym}_USDT"
            ticker = ticker_map.get(contract)
            if ticker:
                sym_contracts.append((sym, contract, ticker))
                tasks.append(enrich_ticker_oi(contract, ticker, mult_map=mult_map))

        enriched = await asyncio.gather(*tasks) if tasks else []
        for (sym, _contract, _ticker), data in zip(sym_contracts, enriched):
            mark = float(data.get("mark_price") or data.get("last") or 0)
            out[sym] = {
                "symbol": sym,
                "product_id": f"{sym}-USD",
                "funding_rate": float(data.get("funding_rate") or 0),
                "mark_price": mark,
                "open_interest": data.get("open_interest"),
                "open_interest_usd": data.get("open_interest_usd"),
                "next_funding_time": data.get("funding_next_apply"),
                "source": "gate.io",
            }
    except Exception as exc:
        logger.warning("Gate funding fetch failed: %s", exc)
    return out


async def _okx_funding_one(sym: str) -> tuple[str, dict | None]:
    try:
        data = await fetch_json(
            "https://www.okx.com/api/v5/public/funding-rate",
            params={"instId": f"{sym}-USDT-SWAP"},
            timeout_sec=8,
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        if not rows:
            return sym, None
        row = rows[0]
        return sym, {
            "symbol": sym,
            "product_id": f"{sym}-USD",
            "funding_rate": float(row.get("fundingRate") or 0),
            "mark_price": None,
            "open_interest": None,
            "open_interest_usd": None,
            "next_funding_time": row.get("nextFundingTime"),
            "source": "okx.com",
        }
    except Exception:
        return sym, None


async def _okx_funding(symbols: list[str]) -> dict[str, dict]:
    results = await asyncio.gather(*[_okx_funding_one(sym) for sym in symbols])
    return {sym: data for sym, data in results if data is not None}


async def get_funding_rates(symbols: list[str] | None = None) -> dict:
    cache_key = "analytics:funding:free"
    cached = cache.get(cache_key)
    if cached:
        return cached

    syms = [s.upper().replace("-USD", "") for s in (symbols or _DEFAULT_SYMBOLS)]
    gate_data, okx_data = await asyncio.gather(_gate_funding(syms), _okx_funding(syms))

    items = []
    for sym in syms:
        primary = gate_data.get(sym) or okx_data.get(sym)
        if not primary:
            continue
        rate = primary["funding_rate"]
        secondary_rate = None
        if sym in gate_data and sym in okx_data:
            secondary_rate = okx_data[sym]["funding_rate"] if primary["source"] == "gate.io" else gate_data[sym]["funding_rate"]

        items.append({
            **primary,
            "funding_rate_pct": round(rate * 100, 4),
            "index_price": None,
            "secondary_funding_rate_pct": round(secondary_rate * 100, 4) if secondary_rate is not None else None,
            "secondary_source": "okx.com" if primary["source"] == "gate.io" and secondary_rate is not None else (
                "gate.io" if secondary_rate is not None else None
            ),
        })

    result = {
        "items": items,
        "source": "gate.io + okx.com (free public APIs)",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(cache_key, result, 120)
    return result
