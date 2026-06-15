"""Discovery cache — in-memory with optional Supabase Postgres persistence."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.core.cache import cache
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.discovery.types import DiscoveryResult, DiscoveryToken
from app.discovery.utils import discovery_result_from_payload

_CACHE_PREFIX = "discovery:results:"
_METRICS_PREFIX = "discovery:metrics:"
_lock = asyncio.Lock()


def cache_ttl_seconds() -> int:
    return settings.DISCOVERY_CACHE_TTL_HOURS * 3600


def _cache_key(category: str, chain: Optional[str] = None) -> str:
    if chain:
        return f"{_CACHE_PREFIX}{category}:{chain}"
    return f"{_CACHE_PREFIX}{category}"


async def _load_from_db(category: str, chain: Optional[str] = None) -> Optional[DiscoveryResult]:
    if not settings.ENABLE_DISCOVERY_PERSISTENCE or AsyncSessionLocal is None:
        return None
    from app.discovery.cache.discovery_store import load_snapshot

    async with AsyncSessionLocal() as db:
        result = await load_snapshot(db, category, chain)
        if result:
            cache.set(_cache_key(category, chain), result.to_dict(), ttl=cache_ttl_seconds())
        return result


async def get_cached_discovery(category: str, chain: Optional[str] = None) -> Optional[DiscoveryResult]:
    data = cache.get(_cache_key(category, chain))
    if not data and chain:
        data = cache.get(_cache_key(category))
    if not data:
        return await _load_from_db(category, chain)

    return discovery_result_from_payload(data, category=category, chain=chain, cached=True)


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
        if settings.ENABLE_DISCOVERY_PERSISTENCE and AsyncSessionLocal is not None:
            from app.discovery.cache.discovery_store import save_snapshot

            async with AsyncSessionLocal() as db:
                await save_snapshot(db, result, chain)
                await db.commit()


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
