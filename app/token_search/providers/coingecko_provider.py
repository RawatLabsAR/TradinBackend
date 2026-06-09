"""CoinGecko token search — verified metadata + market cap."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.onchain.collectors.base import api_request
from app.token_search.normalizers.token_normalizer import normalize_coingecko_coin
from app.token_search.providers.base_provider import BaseTokenProvider
from app.token_search.types import NormalizedToken

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
MAX_DETAIL_COINS = 2


class CoinGeckoProvider(BaseTokenProvider):
    name = "coingecko"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
        return headers

    async def _fetch_coin_detail(self, coin_id: str) -> list[NormalizedToken]:
        detail_url = f"{COINGECKO_BASE}/coins/{coin_id}"
        detail = await api_request(
            "GET", detail_url,
            source="coingecko",
            headers=self._headers(),
            cache_key=f"coingecko:coin:{coin_id}",
            cache_ttl=settings.TOKEN_SEARCH_CACHE_MINUTES * 60 * 2,
            min_interval_ms=300,
        )
        if isinstance(detail, dict):
            return normalize_coingecko_coin(detail)
        return []

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedToken]:
        if not query.strip():
            return []

        url = f"{COINGECKO_BASE}/search"
        resp = await api_request(
            "GET", url,
            source="coingecko",
            params={"query": query.strip()},
            headers=self._headers(),
            cache_key=f"coingecko:search:{query.lower()[:64]}",
            cache_ttl=settings.TOKEN_SEARCH_CACHE_MINUTES * 60,
            min_interval_ms=300,
        )

        if not isinstance(resp, dict):
            return []

        coins = resp.get("coins") or []
        coin_ids = [c.get("id") for c in coins[:MAX_DETAIL_COINS] if c.get("id")]
        if not coin_ids:
            return []

        detail_results = await asyncio.gather(
            *[self._fetch_coin_detail(coin_id) for coin_id in coin_ids],
            return_exceptions=True,
        )

        tokens: list[NormalizedToken] = []
        for result in detail_results:
            if isinstance(result, Exception):
                logger.debug("CoinGecko detail failed: %s", result)
                continue
            tokens.extend(result)

        return tokens[:limit]
