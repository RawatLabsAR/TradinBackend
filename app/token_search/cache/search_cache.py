"""In-memory search and token metadata cache."""

from __future__ import annotations

from typing import Optional

from app.core.cache import cache
from app.core.config import settings
from app.token_search.types import NormalizedToken, TokenSearchResult


def _normalize_query(query: str) -> str:
    return query.strip().lower()[:128]


def _memory_key(query: str) -> str:
    return f"token_search:{_normalize_query(query)}"


def _metadata_key(chain: str, address: str) -> str:
    return f"token_meta:{chain.lower()}:{address.lower()}"


async def get_cached_search(query: str) -> Optional[TokenSearchResult]:
    key = _memory_key(query)
    cached = cache.get(key)
    if cached and isinstance(cached, dict):
        items = [NormalizedToken(**t) for t in cached.get("items", [])]
        return TokenSearchResult(
            query=query,
            total=len(items),
            items=items,
            sources_used=cached.get("sources_used", []),
            cached=True,
        )
    return None


async def set_cached_search(
    query: str,
    result: TokenSearchResult,
) -> None:
    ttl = settings.TOKEN_SEARCH_CACHE_MINUTES * 60
    cache.set(
        _memory_key(query),
        {
            "items": [t.model_dump() for t in result.items],
            "sources_used": result.sources_used,
        },
        ttl,
    )


async def get_cached_metadata(
    chain: str,
    contract_address: str,
) -> Optional[NormalizedToken]:
    cached = cache.get(_metadata_key(chain, contract_address))
    if cached and isinstance(cached, dict):
        return NormalizedToken(**cached)
    return None


async def set_cached_metadata(token: NormalizedToken) -> None:
    ttl = settings.TOKEN_SEARCH_CACHE_MINUTES * 60 * 2
    cache.set(_metadata_key(token.chain, token.contract_address), token.model_dump(), ttl)
