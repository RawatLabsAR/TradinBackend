"""In-memory + DB search cache (Redis-ready interface)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.token_search.models.entities import TokenSearchCache
from app.token_search.types import NormalizedToken, TokenSearchResult

logger = logging.getLogger(__name__)


def _normalize_query(query: str) -> str:
    return query.strip().lower()[:128]


def _memory_key(query: str) -> str:
    return f"token_search:{_normalize_query(query)}"


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


async def get_db_cached_search(
    db: AsyncSession,
    query: str,
) -> Optional[TokenSearchResult]:
    nq = _normalize_query(query)
    now = datetime.utcnow()
    row = await db.execute(
        select(TokenSearchCache).where(
            TokenSearchCache.query_normalized == nq,
            TokenSearchCache.expires_at > now,
        ).order_by(TokenSearchCache.created_at.desc()).limit(1)
    )
    entry = row.scalar_one_or_none()
    if not entry:
        return None

    items = [NormalizedToken(**t) for t in (entry.results_json or [])]
    return TokenSearchResult(
        query=query,
        total=entry.result_count,
        items=items,
        sources_used=entry.sources_used or [],
        cached=True,
    )


async def persist_search_cache(
    db: AsyncSession,
    query: str,
    result: TokenSearchResult,
) -> None:
    nq = _normalize_query(query)
    ttl_minutes = settings.TOKEN_SEARCH_CACHE_MINUTES
    expires = datetime.utcnow() + timedelta(minutes=ttl_minutes)

    db.add(TokenSearchCache(
        query_normalized=nq,
        results_json=[t.model_dump(mode="json") for t in result.items],
        result_count=len(result.items),
        sources_used=result.sources_used,
        expires_at=expires,
    ))


async def cleanup_expired_cache(db: AsyncSession) -> int:
    now = datetime.utcnow()
    result = await db.execute(
        delete(TokenSearchCache).where(TokenSearchCache.expires_at < now)
    )
    return result.rowcount or 0
