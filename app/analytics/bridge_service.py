"""Chain TVL & stablecoin flows from DefiLlama (free, no API key)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.analytics.http_client import fetch_json
from app.core.cache import cache

logger = logging.getLogger(__name__)

_CHAIN_TARGETS = ["Ethereum", "Base", "Arbitrum", "BSC", "Solana", "Polygon"]


async def _chain_tvl_delta(chain_name: str) -> dict | None:
    try:
        history = await fetch_json(
            f"https://api.llama.fi/v2/historicalChainTvl/{chain_name}",
            timeout_sec=20,
        )
        if not isinstance(history, list) or len(history) < 2:
            return None
        prev = float(history[-2].get("tvl", 0) or 0)
        curr = float(history[-1].get("tvl", 0) or 0)
        delta = curr - prev
        return {
            "chain": chain_name.lower(),
            "bridge": "DefiLlama TVL",
            "inflow_usd_24h": max(delta, 0),
            "outflow_usd_24h": max(-delta, 0),
            "net_flow_usd": delta,
            "tvl_usd": curr,
        }
    except Exception as exc:
        logger.debug("Chain TVL delta failed for %s: %s", chain_name, exc)
        return None


async def _stablecoin_net_change() -> float:
    try:
        data = await fetch_json("https://stablecoins.llama.fi/stablecoins", timeout_sec=20)
        assets = data.get("peggedAssets", []) if isinstance(data, dict) else []
        total = sum(float(a.get("circulating", {}).get("peggedUSD", 0) or 0) for a in assets)
        return total
    except Exception:
        return 0.0


async def get_bridge_flows() -> dict:
    cache_key = "analytics:bridges:defillama"
    cached = cache.get(cache_key)
    if cached:
        return cached

    tasks = [_chain_tvl_delta(name) for name in _CHAIN_TARGETS]
    results = await asyncio.gather(*tasks)
    items = [r for r in results if r is not None]

    total_net = sum(i["net_flow_usd"] for i in items)
    stablecoin_mcap = await _stablecoin_net_change()

    result = {
        "items": items,
        "total_net_inflow_usd": total_net,
        "stablecoin_supply_usd": stablecoin_mcap,
        "source": "defillama.com (free)",
        "note": "Net flow = 24h TVL change per chain from DefiLlama public API.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(cache_key, result, 1800)
    return result
