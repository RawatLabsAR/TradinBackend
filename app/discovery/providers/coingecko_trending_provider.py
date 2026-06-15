"""CoinGecko trending search + top volume movers."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.discovery.providers.base_discovery_provider import BaseDiscoveryProvider
from app.discovery.types import DiscoveryToken
from app.onchain.collectors.base import api_request
from app.token_search.normalizers.token_normalizer import normalize_coingecko_coin

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoTrendingProvider(BaseDiscoveryProvider):
    name = "coingecko_trending"
    category = "trending"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
        return headers

    async def _fetch_trending(self) -> list[DiscoveryToken]:
        resp = await api_request(
            "GET",
            f"{COINGECKO_BASE}/search/trending",
            source="coingecko",
            headers=self._headers(),
            cache_key="discovery:coingecko:trending",
            cache_ttl=1800,
            min_interval_ms=300,
        )
        if not isinstance(resp, dict):
            return []

        coins = resp.get("coins") or []
        tokens: list[DiscoveryToken] = []
        for entry in coins[:15]:
            item = entry.get("item") or entry
            tokens.append(DiscoveryToken(
                token_name=str(item.get("name") or ""),
                symbol=str(item.get("symbol") or "").upper(),
                chain="",
                contract_address=str(item.get("id") or ""),
                logo_url=str(item.get("thumb") or item.get("small") or ""),
                market_cap=float(item.get("market_cap") or 0),
                price_usd=float(item.get("data", {}).get("price") or 0),
                price_change_24h=float(
                    (item.get("data") or {}).get("price_change_percentage_24h", {}).get("usd") or 0
                ),
                verified=True,
                source="coingecko",
                discovery_category=self.category,
                source_type="cex",
                metadata={"coingecko_id": item.get("id"), "trending_rank": item.get("score")},
            ))
        return tokens

    async def _fetch_volume_movers(self, *, limit: int) -> list[DiscoveryToken]:
        resp = await api_request(
            "GET",
            f"{COINGECKO_BASE}/coins/markets",
            source="coingecko",
            headers=self._headers(),
            params={
                "vs_currency": "usd",
                "order": "volume_desc",
                "per_page": min(limit, 50),
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
            cache_key="discovery:coingecko:volume_movers",
            cache_ttl=900,
            min_interval_ms=300,
        )
        if not isinstance(resp, list):
            return []

        tokens: list[DiscoveryToken] = []
        for coin in resp:
            if float(coin.get("price_change_percentage_24h") or 0) <= 0:
                continue
            normalized = normalize_coingecko_coin({
                "id": coin.get("id"),
                "name": coin.get("name"),
                "symbol": coin.get("symbol"),
                "image": coin.get("image"),
                "market_data": {
                    "market_cap": {"usd": coin.get("market_cap")},
                    "total_volume": {"usd": coin.get("total_volume")},
                    "current_price": {"usd": coin.get("current_price")},
                    "price_change_percentage_24h": coin.get("price_change_percentage_24h"),
                },
            })
            for t in normalized:
                tokens.append(DiscoveryToken(
                    **t.model_dump(),
                    discovery_category=self.category,
                    source_type="dex" if t.contract_address else "cex",
                    metadata={"coingecko_id": coin.get("id")},
                ))
            if not normalized:
                tokens.append(DiscoveryToken(
                    token_name=str(coin.get("name") or ""),
                    symbol=str(coin.get("symbol") or "").upper(),
                    chain="",
                    contract_address=str(coin.get("id") or ""),
                    logo_url=str(coin.get("image") or ""),
                    market_cap=float(coin.get("market_cap") or 0),
                    volume_24h=float(coin.get("total_volume") or 0),
                    price_usd=float(coin.get("current_price") or 0),
                    price_change_24h=float(coin.get("price_change_percentage_24h") or 0),
                    verified=True,
                    source="coingecko",
                    discovery_category=self.category,
                    source_type="cex",
                    metadata={"coingecko_id": coin.get("id")},
                ))
        return tokens

    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        trending, movers = await asyncio.gather(
            self._fetch_trending(),
            self._fetch_volume_movers(limit=limit),
        )

        combined = trending + movers
        seen: set[str] = set()
        unique: list[DiscoveryToken] = []
        for t in combined:
            key = t.identity_key() if t.contract_address and t.chain else t.symbol
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)

        unique.sort(key=lambda t: t.volume_24h or t.market_cap, reverse=True)
        return unique[:limit]
