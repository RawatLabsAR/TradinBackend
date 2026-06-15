"""GeckoTerminal new pools — freshly created DEX pools."""

from __future__ import annotations

import asyncio
import logging

from app.discovery.normalizers.gecko_pool_normalizer import (
    NETWORK_TO_GECKO,
    normalize_gecko_pool,
)
from app.discovery.providers.base_discovery_provider import BaseDiscoveryProvider
from app.discovery.types import DiscoveryToken
from app.onchain.collectors.base import api_request
from app.onchain.collectors.gecko_terminal_collector import GECKO_API_BASE, GECKO_HEADERS

logger = logging.getLogger(__name__)

SCAN_NETWORKS = ["ethereum", "base", "solana", "bsc", "arbitrum"]


class GeckoNewPoolsProvider(BaseDiscoveryProvider):
    name = "geckoterminal_new_pools"
    category = "new_dex"

    async def _fetch_network(self, chain: str, *, limit: int) -> list[DiscoveryToken]:
        network = NETWORK_TO_GECKO.get(chain)
        if not network:
            return []

        url = f"{GECKO_API_BASE}/networks/{network}/new_pools"
        resp = await api_request(
            "GET",
            url,
            source="geckoterminal",
            headers=GECKO_HEADERS,
            params={"page": 1, "include": "base_token,quote_token,dex"},
            cache_key=f"discovery:gecko:new_pools:{network}",
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

        return tokens[:limit]

    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        per_network = max(10, limit // len(SCAN_NETWORKS))
        results = await asyncio.gather(
            *[self._fetch_network(chain, limit=per_network) for chain in SCAN_NETWORKS],
            return_exceptions=True,
        )

        all_tokens: list[DiscoveryToken] = []
        for chain, result in zip(SCAN_NETWORKS, results):
            if isinstance(result, Exception):
                logger.warning("Gecko new pools failed for %s: %s", chain, result)
                continue
            all_tokens.extend(result)

        all_tokens.sort(key=lambda t: (t.age_hours, -t.liquidity), reverse=False)
        return all_tokens[:limit]
