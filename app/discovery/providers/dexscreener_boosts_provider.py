"""DexScreener token boosts — promoted / trending tokens."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.discovery.providers.base_discovery_provider import BaseDiscoveryProvider
from app.discovery.types import DiscoveryToken
from app.onchain.collectors.base import api_request
from app.token_search.normalizers.token_normalizer import normalize_dexscreener_pair
from app.token_search.types import normalize_chain, normalize_contract

logger = logging.getLogger(__name__)


class DexScreenerBoostsProvider(BaseDiscoveryProvider):
    name = "dexscreener_boosts"
    category = "trending"

    async def _fetch_boost_list(self, endpoint: str) -> list[dict[str, Any]]:
        base = settings.DEXSCREENER_API_URL.rstrip("/")
        resp = await api_request(
            "GET",
            f"{base}/token-boosts/{endpoint}/v1",
            source="dexscreener",
            cache_key=f"discovery:dexscreener:boosts:{endpoint}",
            cache_ttl=600,
            min_interval_ms=300,
        )
        if isinstance(resp, list):
            return resp
        return []

    async def _resolve_token(self, boost: dict[str, Any]) -> DiscoveryToken | None:
        chain = normalize_chain(str(boost.get("chainId") or ""))
        address = str(boost.get("tokenAddress") or "")
        if not chain or not address:
            return None

        address = normalize_contract(chain, address)
        base = settings.DEXSCREENER_API_URL.rstrip("/")
        resp = await api_request(
            "GET",
            f"{base}/latest/dex/tokens/{address}",
            source="dexscreener",
            cache_key=f"discovery:dexscreener:token:{chain}:{address[:20]}",
            cache_ttl=300,
            min_interval_ms=250,
        )

        pairs: list[dict] = []
        if isinstance(resp, dict):
            pairs = resp.get("pairs") or []

        if not pairs:
            return DiscoveryToken(
                token_name=str(boost.get("description") or "")[:64],
                symbol="",
                chain=chain,
                contract_address=address,
                source="dexscreener",
                discovery_category=self.category,
                source_type="dex",
                metadata={"boost": boost},
            )

        best_pair = max(
            pairs,
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
        )
        token = normalize_dexscreener_pair(best_pair)
        if not token:
            return None

        return DiscoveryToken(
            **token.model_dump(),
            discovery_category=self.category,
            source_type="dex",
            metadata={**token.metadata, "boost": boost},
        )

    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        latest, top = await asyncio.gather(
            self._fetch_boost_list("latest"),
            self._fetch_boost_list("top"),
        )

        boosts = latest + top
        seen_addrs: set[str] = set()
        unique_boosts: list[dict] = []
        for b in boosts:
            key = f"{b.get('chainId')}:{b.get('tokenAddress')}"
            if key in seen_addrs:
                continue
            seen_addrs.add(key)
            unique_boosts.append(b)

        results = await asyncio.gather(
            *[self._resolve_token(b) for b in unique_boosts[:limit * 2]],
            return_exceptions=True,
        )

        tokens: list[DiscoveryToken] = []
        seen: set[str] = set()
        for result in results:
            if isinstance(result, Exception) or result is None:
                continue
            key = result.identity_key()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(result)

        tokens.sort(key=lambda t: t.volume_24h, reverse=True)
        return tokens[:limit]
