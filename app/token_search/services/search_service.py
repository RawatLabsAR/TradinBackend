"""Core token search orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.token_search.cache.search_cache import (
    get_cached_metadata,
    get_cached_search,
    set_cached_metadata,
    set_cached_search,
)
from app.token_search.models.entities import SearchHistory, TokenRegistry
from app.token_search.providers.coingecko_provider import CoinGeckoProvider
from app.token_search.providers.dexscreener_provider import DexScreenerProvider
from app.token_search.ranking.rank_engine import compute_rank_score, rank_tokens
from app.token_search.types import NormalizedToken, TokenSearchResult, TrendingTokenEntry, normalize_contract

logger = logging.getLogger(__name__)

PROVIDER_TIMEOUT_SECONDS = 8.0


def _db_enabled(db: AsyncSession | None) -> bool:
    return db is not None and settings.ENABLE_TOKEN_SEARCH_DB


def _get_providers():
    return [
        DexScreenerProvider(),
        CoinGeckoProvider(),
    ]


async def _provider_search(provider, query: str, *, limit: int) -> list[NormalizedToken]:
    try:
        return await asyncio.wait_for(
            provider.search(query, limit=limit),
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Provider %s timed out after %.0fs", provider.name, PROVIDER_TIMEOUT_SECONDS)
        return []
    except Exception as exc:
        logger.warning("Provider %s failed: %s", provider.name, exc)
        return []


class TokenSearchService:
    async def search(
        self,
        db: AsyncSession | None,
        query: str,
        *,
        limit: int = 20,
        chain: Optional[str] = None,
        use_cache: bool = True,
    ) -> TokenSearchResult:
        query = query.strip()
        if len(query) < 1:
            return TokenSearchResult(query=query, total=0, items=[])

        t0 = time.monotonic()

        if use_cache:
            mem = await get_cached_search(query)
            if mem:
                mem.took_ms = round((time.monotonic() - t0) * 1000, 2)
                if chain:
                    mem.items = [t for t in mem.items if t.chain == chain.lower()]
                    mem.total = len(mem.items)
                return mem

        providers = _get_providers()
        results = await asyncio.gather(
            *[_provider_search(p, query, limit=limit * 2) for p in providers],
        )

        all_tokens: list[NormalizedToken] = []
        sources_used: list[str] = []

        for provider, result in zip(providers, results):
            if result:
                sources_used.append(provider.name)
                all_tokens.extend(result)

        ranked = rank_tokens(all_tokens, query, limit=limit * 2)

        if chain:
            ranked = [t for t in ranked if t.chain == chain.lower()]

        ranked = ranked[:limit]

        search_result = TokenSearchResult(
            query=query,
            total=len(ranked),
            items=ranked,
            sources_used=sources_used,
            cached=False,
            took_ms=round((time.monotonic() - t0) * 1000, 2),
        )

        await set_cached_search(query, search_result)

        if _db_enabled(db):
            try:
                await self._upsert_registry(db, ranked)
                await db.commit()
            except Exception as exc:
                logger.warning("Registry upsert failed: %s", exc)
                await db.rollback()

        return search_result

    async def resolve_symbol(
        self,
        db: AsyncSession | None,
        symbol: str,
        *,
        chain: Optional[str] = None,
        limit: int = 10,
    ) -> TokenSearchResult:
        return await self.search(db, symbol, limit=limit, chain=chain)

    async def get_token_detail(
        self,
        db: AsyncSession | None,
        chain: str,
        contract_address: str,
    ) -> Optional[NormalizedToken]:
        chain = chain.lower()
        contract_address = normalize_contract(chain, contract_address)

        cached = await get_cached_metadata(chain, contract_address)
        if cached:
            return cached

        token: Optional[NormalizedToken] = None
        for provider in _get_providers():
            try:
                token = await provider.get_token(chain, contract_address)
                if token:
                    break
            except Exception as exc:
                logger.debug("get_token %s failed: %s", provider.name, exc)

        if not token and _db_enabled(db):
            reg = await self._get_registry(db, chain, contract_address)
            if reg:
                token = NormalizedToken(
                    token_name=reg.token_name,
                    symbol=reg.symbol,
                    chain=chain,
                    contract_address=contract_address,
                    logo_url=reg.logo_url,
                    verified=reg.verified,
                    dex=reg.primary_dex,
                )

        if token:
            await set_cached_metadata(token)
            if _db_enabled(db):
                try:
                    await self._upsert_registry(db, [token])
                    await db.commit()
                except Exception as exc:
                    logger.warning("Token registry upsert failed: %s", exc)
                    await db.rollback()

        return token

    async def get_trending(
        self,
        db: AsyncSession | None,
        *,
        limit: int = 20,
        chain: Optional[str] = None,
    ) -> list[TrendingTokenEntry]:
        if not _db_enabled(db):
            return []

        reg_q = select(TokenRegistry).order_by(desc(TokenRegistry.search_count)).limit(limit)
        if chain:
            reg_q = reg_q.where(TokenRegistry.chain == chain.lower())

        result = await db.execute(reg_q)
        entries: list[TrendingTokenEntry] = []
        for r in result.scalars().all():
            token = NormalizedToken(
                token_name=r.token_name,
                symbol=r.symbol,
                chain=r.chain,
                contract_address=r.contract_address,
                logo_url=r.logo_url,
                verified=r.verified,
                dex=r.primary_dex,
            )
            entries.append(
                TrendingTokenEntry(
                    token_name=r.token_name,
                    symbol=r.symbol,
                    chain=r.chain,
                    contract_address=r.contract_address,
                    logo_url=r.logo_url,
                    search_count=r.search_count,
                    trend_score=compute_rank_score(token, r.symbol or ""),
                    dex=r.primary_dex,
                    verified=r.verified,
                )
            )
        return entries

    async def record_search(
        self,
        db: AsyncSession | None,
        *,
        session_id: str,
        query: str,
        selected: Optional[NormalizedToken] = None,
    ) -> None:
        if not _db_enabled(db) or not settings.ENABLE_SEARCH_HISTORY:
            return

        db.add(SearchHistory(
            session_id=session_id or "anonymous",
            query=query[:128],
            selected_chain=selected.chain if selected else "",
            selected_address=selected.contract_address if selected else "",
            selected_symbol=selected.symbol if selected else "",
        ))

        if selected:
            await db.execute(
                update(TokenRegistry)
                .where(
                    TokenRegistry.chain == selected.chain,
                    TokenRegistry.contract_address == selected.contract_address,
                )
                .values(search_count=TokenRegistry.search_count + 1)
            )
        await db.commit()

    async def get_recent_searches(
        self,
        db: AsyncSession | None,
        session_id: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        if not _db_enabled(db) or not settings.ENABLE_SEARCH_HISTORY:
            return []

        result = await db.execute(
            select(SearchHistory)
            .where(SearchHistory.session_id == session_id)
            .order_by(desc(SearchHistory.searched_at))
            .limit(limit)
        )
        return [
            {
                "query": h.query,
                "chain": h.selected_chain,
                "contract_address": h.selected_address,
                "symbol": h.selected_symbol,
                "searched_at": h.searched_at.isoformat(),
            }
            for h in result.scalars().all()
            if h.selected_address
        ]

    async def _get_registry(
        self,
        db: AsyncSession,
        chain: str,
        address: str,
    ) -> Optional[TokenRegistry]:
        result = await db.execute(
            select(TokenRegistry).where(
                TokenRegistry.chain == chain,
                TokenRegistry.contract_address == address,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_registry(
        self,
        db: AsyncSession,
        tokens: list[NormalizedToken],
    ) -> None:
        for token in tokens:
            existing = await self._get_registry(db, token.chain, token.contract_address)
            if existing:
                existing.token_name = token.token_name or existing.token_name
                existing.symbol = token.symbol or existing.symbol
                existing.logo_url = token.logo_url or existing.logo_url
                existing.verified = token.verified or existing.verified
                existing.primary_dex = token.dex or existing.primary_dex
                existing.last_seen_at = datetime.utcnow()
            else:
                db.add(TokenRegistry(
                    chain=token.chain,
                    contract_address=token.contract_address,
                    token_name=token.token_name,
                    symbol=token.symbol,
                    logo_url=token.logo_url,
                    verified=token.verified,
                    primary_dex=token.dex,
                ))


token_search_service = TokenSearchService()
