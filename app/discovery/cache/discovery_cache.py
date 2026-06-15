"""In-memory cache for discovery — no database persistence."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.core.cache import cache
from app.core.config import settings
from app.discovery.types import DiscoveryResult, DiscoveryToken

_CACHE_PREFIX = "discovery:results:"
_METRICS_PREFIX = "discovery:metrics:"
_lock = asyncio.Lock()


def cache_ttl_seconds() -> int:
    return settings.DISCOVERY_CACHE_TTL_HOURS * 3600


def _cache_key(category: str, chain: Optional[str] = None) -> str:
    if chain:
        return f"{_CACHE_PREFIX}{category}:{chain}"
    return f"{_CACHE_PREFIX}{category}"


async def get_cached_discovery(category: str, chain: Optional[str] = None) -> Optional[DiscoveryResult]:
    data = cache.get(_cache_key(category, chain))
    if not data:
        if chain:
            data = cache.get(_cache_key(category))
            if not data:
                return None
        else:
            return None

    items = [DiscoveryToken.model_validate(t) for t in data.get("items", [])]
    if chain:
        chain_lower = chain.lower()
        items = [
            t for t in items
            if t.chain == chain_lower or t.source_type == "cex"
        ]

    return DiscoveryResult(
        category=category,
        items=items,
        sources_used=data.get("sources_used", []),
        scanned_at=data.get("scanned_at", ""),
        cached=True,
    )


async def set_cached_discovery(
    result: DiscoveryResult,
    chain: Optional[str] = None,
    ttl: Optional[int] = None,
) -> None:
    async with _lock:
        cache.set(
            _cache_key(result.category, chain),
            result.to_dict(),
            ttl=ttl or cache_ttl_seconds(),
        )


def get_volume_change_pct(token: DiscoveryToken) -> float:
    """Compare current volume to the previous in-memory scan snapshot."""
    if not token.chain or not token.contract_address:
        return 0.0
    prev = cache.get(f"{_METRICS_PREFIX}{token.identity_key()}")
    if not prev or float(prev.get("volume_24h") or 0) <= 0:
        return 0.0
    prev_vol = float(prev["volume_24h"])
    return round(((token.volume_24h - prev_vol) / prev_vol) * 100, 1)


def record_token_metrics(tokens: list[DiscoveryToken]) -> None:
    """Store scan metrics in memory for the next scan's volume-change detection."""
    ttl = cache_ttl_seconds()
    for token in tokens:
        if token.source_type != "dex" or not token.contract_address:
            continue
        cache.set(
            f"{_METRICS_PREFIX}{token.identity_key()}",
            {"volume_24h": token.volume_24h},
            ttl=ttl,
        )
