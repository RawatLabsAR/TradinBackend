"""Discovery orchestration — in-memory cache with optional Postgres persistence."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.discovery.cache.discovery_cache import (
    get_cached_discovery,
    get_volume_change_pct,
    record_token_metrics,
    set_cached_discovery,
)
from app.discovery.providers.cex_listing_provider import CexListingProvider
from app.discovery.providers.coingecko_trending_provider import CoinGeckoTrendingProvider
from app.discovery.providers.dexscreener_boosts_provider import DexScreenerBoostsProvider
from app.discovery.providers.gecko_new_pools_provider import GeckoNewPoolsProvider
from app.discovery.providers.gecko_trending_provider import GeckoTrendingProvider
from app.discovery.scoring.growth_scorer import dedupe_tokens, is_surging_candidate, score_token
from app.discovery.types import DiscoveryResult, DiscoveryToken
from app.discovery.utils import filter_tokens_by_chain

logger = logging.getLogger(__name__)

PROVIDER_TIMEOUT = 45.0
DEFAULT_LIMIT = 50


def _empty_result(category: str) -> DiscoveryResult:
    return DiscoveryResult(
        category=category,
        items=[],
        sources_used=[],
        scanned_at="",
        cached=False,
    )


class DiscoveryService:
    def __init__(self) -> None:
        self._new_pools = GeckoNewPoolsProvider()
        self._gecko_trending = GeckoTrendingProvider()
        self._dex_boosts = DexScreenerBoostsProvider()
        self._cg_trending = CoinGeckoTrendingProvider()
        self._cex = CexListingProvider()

    async def _cached_or_empty(
        self,
        category: str,
        chain: Optional[str] = None,
    ) -> Optional[DiscoveryResult]:
        return await get_cached_discovery(category, chain)

    async def _fetch_provider(self, provider, *, limit: int) -> tuple[list[DiscoveryToken], str]:
        try:
            tokens = await asyncio.wait_for(provider.fetch(limit=limit), timeout=PROVIDER_TIMEOUT)
            return tokens, provider.name
        except asyncio.TimeoutError:
            logger.warning("Discovery provider %s timed out", provider.name)
            return [], provider.name
        except Exception as exc:
            logger.warning("Discovery provider %s failed: %s", provider.name, exc)
            return [], provider.name

    async def _score_batch(self, tokens: list[DiscoveryToken]) -> list[DiscoveryToken]:
        scored: list[DiscoveryToken] = []
        for token in tokens:
            vol_change = get_volume_change_pct(token)
            result = score_token(token, volume_change_pct=vol_change)
            if result:
                scored.append(result)
        scored.sort(key=lambda t: t.growth_score, reverse=True)
        return scored

    async def _build_result(
        self,
        *,
        category: str,
        raw_tokens: list[DiscoveryToken],
        sources: list[str],
        chain: Optional[str] = None,
        min_score: float = 0.0,
        limit: int = DEFAULT_LIMIT,
    ) -> DiscoveryResult:
        if chain:
            raw_tokens = filter_tokens_by_chain(raw_tokens, chain)

        deduped = dedupe_tokens(raw_tokens)
        scored = await self._score_batch(deduped)

        if min_score > 0:
            scored = [t for t in scored if t.growth_score >= min_score]

        scored = scored[:limit]
        scanned_at = datetime.now(timezone.utc).isoformat()

        result = DiscoveryResult(
            category=category,
            items=scored,
            sources_used=sources,
            scanned_at=scanned_at,
        )

        await set_cached_discovery(result, chain=None)
        record_token_metrics(scored)
        return result

    def _filter_cached(
        self,
        cached: DiscoveryResult,
        *,
        chain: Optional[str] = None,
        min_score: float = 0.0,
        limit: int = DEFAULT_LIMIT,
    ) -> DiscoveryResult:
        items = list(cached.items)
        if chain:
            items = filter_tokens_by_chain(items, chain)
        if min_score > 0:
            items = [t for t in items if t.growth_score >= min_score]
        return DiscoveryResult(
            category=cached.category,
            items=items[:limit],
            sources_used=cached.sources_used,
            scanned_at=cached.scanned_at,
            cached=True,
        )

    async def scan_new_dex(
        self,
        *,
        chain: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        min_score: float = 0.0,
        use_cache: bool = True,
    ) -> DiscoveryResult:
        if use_cache:
            cached = await self._cached_or_empty("new_dex", chain)
            if cached:
                return self._filter_cached(cached, chain=chain, min_score=min_score, limit=limit)
            return _empty_result("new_dex")

        tokens, source = await self._fetch_provider(self._new_pools, limit=limit * 2)
        for t in tokens:
            t.discovery_category = "new_dex"
        return await self._build_result(
            category="new_dex", raw_tokens=tokens,
            sources=[source], chain=chain, min_score=min_score, limit=limit,
        )

    async def scan_new_cex(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        min_score: float = 0.0,
        use_cache: bool = True,
    ) -> DiscoveryResult:
        if use_cache:
            cached = await self._cached_or_empty("new_cex")
            if cached:
                return self._filter_cached(cached, min_score=min_score, limit=limit)
            return _empty_result("new_cex")

        tokens = await self._cex.fetch_all_recent(max_age_hours=168, limit=limit * 2)
        for t in tokens:
            t.discovery_category = "new_cex"
        return await self._build_result(
            category="new_cex", raw_tokens=tokens,
            sources=[self._cex.name], min_score=min_score, limit=limit,
        )

    async def scan_surging(
        self,
        *,
        chain: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        min_volume_change: float = 50.0,
        use_cache: bool = True,
    ) -> DiscoveryResult:
        if use_cache:
            cached = await self._cached_or_empty("surging", chain)
            if cached:
                return self._filter_cached(cached, chain=chain, limit=limit)
            return _empty_result("surging")

        results = await asyncio.gather(
            self._fetch_provider(self._gecko_trending, limit=limit),
            self._fetch_provider(self._new_pools, limit=limit),
            self._fetch_provider(self._dex_boosts, limit=limit),
        )

        all_tokens: list[DiscoveryToken] = []
        sources: list[str] = []
        for tokens, source in results:
            sources.append(source)
            for t in tokens:
                t.discovery_category = "surging"
                all_tokens.append(t)

        deduped = dedupe_tokens(all_tokens)
        if chain:
            deduped = filter_tokens_by_chain(deduped, chain)

        scored: list[DiscoveryToken] = []
        for token in deduped:
            vol_change = get_volume_change_pct(token)
            token.volume_change_pct = vol_change
            if not is_surging_candidate(token, vol_change, min_volume_change=min_volume_change):
                continue
            result = score_token(token, volume_change_pct=vol_change)
            if result:
                scored.append(result)

        scored.sort(key=lambda t: (t.volume_change_pct, t.growth_score, t.volume_24h), reverse=True)
        scanned_at = datetime.now(timezone.utc).isoformat()
        result = DiscoveryResult(
            category="surging",
            items=scored[:limit],
            sources_used=sources,
            scanned_at=scanned_at,
        )
        await set_cached_discovery(result, chain=None)
        record_token_metrics(scored)
        return result

    async def scan_trending(
        self,
        *,
        chain: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        min_score: float = 0.0,
        use_cache: bool = True,
    ) -> DiscoveryResult:
        if use_cache:
            cached = await self._cached_or_empty("trending", chain)
            if cached:
                return self._filter_cached(cached, chain=chain, min_score=min_score, limit=limit)
            return _empty_result("trending")

        results = await asyncio.gather(
            self._fetch_provider(self._gecko_trending, limit=limit),
            self._fetch_provider(self._dex_boosts, limit=limit),
            self._fetch_provider(self._cg_trending, limit=limit),
        )

        all_tokens: list[DiscoveryToken] = []
        sources: list[str] = []
        for tokens, source in results:
            sources.append(source)
            for t in tokens:
                t.discovery_category = "trending"
                all_tokens.append(t)

        return await self._build_result(
            category="trending", raw_tokens=all_tokens,
            sources=sources, chain=chain, min_score=min_score, limit=limit,
        )

    async def run_full_scan(self) -> None:
        """Background job: refresh all discovery categories sequentially."""
        t0 = time.monotonic()
        logger.info(
            "Discovery scan starting (persistence=%s)…",
            settings.ENABLE_DISCOVERY_PERSISTENCE,
        )

        try:
            await self._cex.fetch(limit=10)
        except Exception as exc:
            logger.warning("CEX catalog baseline failed: %s", exc)

        for name, coro in (
            ("new_dex", self.scan_new_dex(use_cache=False)),
            ("new_cex", self.scan_new_cex(use_cache=False)),
            ("surging", self.scan_surging(use_cache=False)),
            ("trending", self.scan_trending(use_cache=False)),
        ):
            try:
                result = await coro
                logger.info("Discovery scan %s: %d tokens", name, len(result.items))
            except Exception as exc:
                logger.exception("Discovery scan %s failed: %s", name, exc)

        elapsed = round(time.monotonic() - t0, 1)
        logger.info("Discovery scan complete in %.1fs", elapsed)

    async def get_by_category(
        self,
        category: str,
        *,
        chain: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        min_score: float = 0.0,
        min_volume_change: float = 50.0,
        refresh: bool = False,
    ) -> DiscoveryResult:
        use_cache = not refresh
        if category == "new_dex":
            return await self.scan_new_dex(chain=chain, limit=limit, min_score=min_score, use_cache=use_cache)
        if category == "new_cex":
            return await self.scan_new_cex(limit=limit, min_score=min_score, use_cache=use_cache)
        if category == "surging":
            return await self.scan_surging(chain=chain, limit=limit, min_volume_change=min_volume_change, use_cache=use_cache)
        if category == "trending":
            return await self.scan_trending(chain=chain, limit=limit, min_score=min_score, use_cache=use_cache)
        return DiscoveryResult(category=category, items=[], sources_used=[], scanned_at="")


discovery_service = DiscoveryService()
