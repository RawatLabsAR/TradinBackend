"""GeckoTerminal trending pools across networks."""

from __future__ import annotations

import logging

from app.discovery.normalizers.gecko_pool_normalizer import (
    _network_from_pool,
    normalize_gecko_pool,
)
from app.discovery.providers.base_discovery_provider import BaseDiscoveryProvider
from app.discovery.types import DiscoveryToken
from app.onchain.collectors.base import api_request
from app.onchain.collectors.gecko_terminal_collector import GECKO_API_BASE, GECKO_HEADERS

logger = logging.getLogger(__name__)


class GeckoTrendingProvider(BaseDiscoveryProvider):
    name = "geckoterminal_trending"
    category = "trending"

    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        url = f"{GECKO_API_BASE}/networks/trending_pools"
        resp = await api_request(
            "GET",
            url,
            source="geckoterminal",
            headers=GECKO_HEADERS,
            params={"page": 1, "include": "base_token,quote_token,dex"},
            cache_key="discovery:gecko:trending_pools",
            cache_ttl=600,
            min_interval_ms=1200,
        )

        if not isinstance(resp, dict):
            return []

        pools = resp.get("data") or []
        included = resp.get("included") or []
        tokens: list[DiscoveryToken] = []
        seen: set[str] = set()

        for pool in pools:
            network = _network_from_pool(pool, included)
            token = normalize_gecko_pool(
                pool,
                network=network,
                included=included,
                category=self.category,
            )
            if not token:
                continue
            key = token.identity_key()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(token)

        tokens.sort(key=lambda t: t.volume_24h, reverse=True)
        return tokens[:limit]
