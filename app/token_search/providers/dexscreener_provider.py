"""DexScreener token search — EVM + Solana DEX pairs."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.onchain.collectors.base import api_request
from app.token_search.normalizers.token_normalizer import normalize_dexscreener_pair
from app.token_search.providers.base_provider import BaseTokenProvider
from app.token_search.types import NormalizedToken, normalize_chain

logger = logging.getLogger(__name__)


class DexScreenerProvider(BaseTokenProvider):
    name = "dexscreener"

    def __init__(self) -> None:
        self._base_url = settings.DEXSCREENER_API_URL.rstrip("/")

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedToken]:
        if not query.strip():
            return []

        url = f"{self._base_url}/latest/dex/search"
        resp = await api_request(
            "GET", url,
            source="dexscreener",
            params={"q": query.strip()},
            cache_key=f"dexscreener:search:{query.lower()[:64]}",
            cache_ttl=settings.TOKEN_SEARCH_CACHE_MINUTES * 60,
            min_interval_ms=250,
        )

        pairs: list[dict[str, Any]] = []
        if isinstance(resp, dict):
            pairs = resp.get("pairs") or []

        if not pairs:
            return []

        q = query.strip().lower()
        tokens: list[NormalizedToken] = []
        seen: set[str] = set()

        for pair in pairs:
            for token in self._pair_tokens(pair, q):
                key = token.identity_key()
                if key in seen:
                    continue
                seen.add(key)
                tokens.append(token)

        tokens.sort(
            key=lambda t: (t.liquidity, t.volume_24h, t.market_cap),
            reverse=True,
        )
        return tokens[:limit]

    @staticmethod
    def _pair_tokens(pair: dict, query: str) -> list[NormalizedToken]:
        """Extract matching base/quote tokens from a pair."""
        results: list[NormalizedToken] = []

        base = normalize_dexscreener_pair(pair)
        if base and DexScreenerProvider._matches_query(base, query):
            results.append(base)

        quote = pair.get("quoteToken") or {}
        quote_addr = str(quote.get("address") or "")
        if not quote_addr:
            return results

        chain = normalize_chain(str(pair.get("chainId") or ""))
        quote_symbol = str(quote.get("symbol") or "").lower()
        quote_name = str(quote.get("name") or "").lower()

        if query not in quote_symbol and query not in quote_name:
            return results

        # Re-use pair metrics for quote-side token discovery
        flipped = dict(pair)
        flipped["baseToken"] = quote
        flipped["quoteToken"] = pair.get("baseToken") or {}
        quote_token = normalize_dexscreener_pair(flipped)
        if quote_token and DexScreenerProvider._matches_query(quote_token, query):
            existing = {t.identity_key() for t in results}
            if quote_token.identity_key() not in existing:
                results.append(quote_token)

        return results

    @staticmethod
    def _matches_query(token: NormalizedToken, query: str) -> bool:
        q = query.lower()
        return (
            token.symbol.lower() == q
            or q in token.symbol.lower()
            or q in token.token_name.lower()
        )

    async def get_token(
        self,
        chain: str,
        contract_address: str,
    ) -> NormalizedToken | None:
        url = f"{self._base_url}/latest/dex/tokens/{contract_address}"
        resp = await api_request(
            "GET", url,
            source="dexscreener",
            cache_key=f"dexscreener:token:{chain}:{contract_address.lower()}",
            cache_ttl=settings.TOKEN_SEARCH_CACHE_MINUTES * 60,
        )

        pairs: list[dict] = []
        if isinstance(resp, dict):
            pairs = resp.get("pairs") or []

        if not pairs:
            return None

        tokens: list[NormalizedToken] = []
        for pair in pairs:
            token = normalize_dexscreener_pair(pair)
            if token and token.chain == chain:
                tokens.append(token)

        if not tokens:
            for pair in pairs:
                token = normalize_dexscreener_pair(pair)
                if token:
                    tokens.append(token)

        if not tokens:
            return None

        return max(tokens, key=lambda t: (t.liquidity, t.volume_24h))
