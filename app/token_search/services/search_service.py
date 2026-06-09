"""Core token search orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.token_search.cache.search_cache import (
    get_cached_search,
    get_db_cached_search,
    persist_search_cache,
    set_cached_search,
)
from app.token_search.models.entities import (
    SearchHistory,
    TokenMetadata,
    TokenRegistry,
    TrendingToken,
)
from app.token_search.providers.coingecko_provider import CoinGeckoProvider
from app.token_search.providers.dexscreener_provider import DexScreenerProvider
from app.token_search.ranking.rank_engine import rank_tokens
from app.token_search.types import NormalizedToken, TokenSearchResult, TrendingTokenEntry, normalize_contract

logger = logging.getLogger(__name__)

PROVIDER_TIMEOUT_SECONDS = 8.0


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
        db: AsyncSession,
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

            db_cached = await get_db_cached_search(db, query)
            if db_cached:
                await set_cached_search(query, db_cached)
                db_cached.took_ms = round((time.monotonic() - t0) * 1000, 2)
                if chain:
                    db_cached.items = [t for t in db_cached.items if t.chain == chain.lower()]
                    db_cached.total = len(db_cached.items)
                return db_cached

        # Fan out to all providers concurrently (each capped by timeout)
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
        try:
            await persist_search_cache(db, query, search_result)
            await self._upsert_registry(db, ranked)
            await db.commit()
        except Exception as exc:
            logger.warning("Search cache persist failed: %s", exc)
            await db.rollback()

        return search_result

    async def resolve_symbol(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        chain: Optional[str] = None,
        limit: int = 10,
    ) -> TokenSearchResult:
        """Resolve ambiguous symbol to ranked contract addresses."""
        return await self.search(db, symbol, limit=limit, chain=chain)

    async def get_token_detail(
        self,
        db: AsyncSession,
        chain: str,
        contract_address: str,
    ) -> Optional[NormalizedToken]:
        chain = chain.lower()
        contract_address = normalize_contract(chain, contract_address)

        # Check metadata cache
        now = datetime.utcnow()
        meta_row = await db.execute(
            select(TokenMetadata).where(
                TokenMetadata.chain == chain,
                TokenMetadata.contract_address == contract_address,
                TokenMetadata.expires_at > now,
            ).order_by(desc(TokenMetadata.fetched_at)).limit(1)
        )
        meta = meta_row.scalar_one_or_none()
        if meta:
            reg = await self._get_registry(db, chain, contract_address)
            return NormalizedToken(
                token_name=reg.token_name if reg else "",
                symbol=reg.symbol if reg else "",
                chain=chain,
                contract_address=contract_address,
                logo_url=reg.logo_url if reg else "",
                market_cap=meta.market_cap,
                liquidity=meta.liquidity,
                volume_24h=meta.volume_24h,
                price_usd=meta.price_usd,
                price_change_24h=meta.price_change_24h,
                verified=meta.verified or (reg.verified if reg else False),
                dex=meta.dex,
                pair_address=meta.pair_address,
                holder_count=meta.holder_count,
            )

        # Fetch from providers
        token: Optional[NormalizedToken] = None
        for provider in _get_providers():
            try:
                token = await provider.get_token(chain, contract_address)
                if token:
                    break
            except Exception as exc:
                logger.debug("get_token %s failed: %s", provider.name, exc)

        if not token:
            # Try search by registry symbol
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
            await self._persist_metadata(db, token)
            await self._upsert_registry(db, [token])
            await db.commit()

        return token

    async def get_trending(
        self,
        db: AsyncSession,
        *,
        limit: int = 20,
        chain: Optional[str] = None,
    ) -> list[TrendingTokenEntry]:
        q = select(TrendingToken).order_by(desc(TrendingToken.trend_score)).limit(limit)
        if chain:
            q = q.where(TrendingToken.chain == chain.lower())

        result = await db.execute(q)
        rows = result.scalars().all()

        if not rows:
            # Fallback: top searched registry tokens
            reg_q = select(TokenRegistry).order_by(desc(TokenRegistry.search_count)).limit(limit)
            if chain:
                reg_q = reg_q.where(TokenRegistry.chain == chain.lower())
            reg_result = await db.execute(reg_q)
            return [
                TrendingTokenEntry(
                    token_name=r.token_name,
                    symbol=r.symbol,
                    chain=r.chain,
                    contract_address=r.contract_address,
                    logo_url=r.logo_url,
                    search_count=r.search_count,
                    dex=r.primary_dex,
                    verified=r.verified,
                )
                for r in reg_result.scalars().all()
            ]

        return [
            TrendingTokenEntry(
                token_name=r.token_name,
                symbol=r.symbol,
                chain=r.chain,
                contract_address=r.contract_address,
                logo_url=r.logo_url,
                volume_24h=r.volume_24h,
                liquidity=r.liquidity,
                market_cap=r.market_cap,
                search_count=r.search_count,
                trend_score=r.trend_score,
                dex=r.dex,
                verified=r.verified,
            )
            for r in rows
        ]

    async def record_search(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        query: str,
        selected: Optional[NormalizedToken] = None,
    ) -> None:
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
        db: AsyncSession,
        session_id: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
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

    async def _persist_metadata(self, db: AsyncSession, token: NormalizedToken) -> None:
        expires = datetime.utcnow() + timedelta(minutes=settings.TOKEN_SEARCH_CACHE_MINUTES * 2)
        db.add(TokenMetadata(
            chain=token.chain,
            contract_address=token.contract_address,
            market_cap=token.market_cap,
            liquidity=token.liquidity,
            volume_24h=token.volume_24h,
            price_usd=token.price_usd,
            price_change_24h=token.price_change_24h,
            holder_count=token.holder_count,
            dex=token.dex,
            pair_address=token.pair_address,
            verified=token.verified,
            expires_at=expires,
        ))


token_search_service = TokenSearchService()
