"""Trending token computation from search frequency + volume."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.token_search.models.entities import SearchHistory, TokenRegistry, TrendingToken
from app.token_search.ranking.rank_engine import compute_rank_score
from app.token_search.types import NormalizedToken

logger = logging.getLogger(__name__)


async def compute_trending_tokens(db: AsyncSession, *, limit: int = 30) -> int:
    """Rebuild trending_tokens table from recent search + registry data."""
    since = datetime.utcnow() - timedelta(hours=24)

    # Search frequency per token
    freq_q = await db.execute(
        select(
            SearchHistory.selected_chain,
            SearchHistory.selected_address,
            SearchHistory.selected_symbol,
            func.count(SearchHistory.id).label("cnt"),
        )
        .where(
            SearchHistory.searched_at >= since,
            SearchHistory.selected_address != "",
        )
        .group_by(
            SearchHistory.selected_chain,
            SearchHistory.selected_address,
            SearchHistory.selected_symbol,
        )
        .order_by(desc("cnt"))
        .limit(limit * 2)
    )
    freq_rows = freq_q.all()

    await db.execute(delete(TrendingToken))

    rank = 0
    for row in freq_rows:
        chain, address, symbol, cnt = row[0], row[1], row[2], row[3]
        reg = await db.execute(
            select(TokenRegistry).where(
                TokenRegistry.chain == chain,
                TokenRegistry.contract_address == address,
            )
        )
        registry = reg.scalar_one_or_none()

        token = NormalizedToken(
            token_name=registry.token_name if registry else symbol,
            symbol=symbol or (registry.symbol if registry else ""),
            chain=chain,
            contract_address=address,
            logo_url=registry.logo_url if registry else "",
            verified=registry.verified if registry else False,
            dex=registry.primary_dex if registry else "",
            volume_24h=0,
            liquidity=0,
            market_cap=0,
        )
        trend_score = compute_rank_score(token, symbol or "") + cnt * 50

        rank += 1
        db.add(TrendingToken(
            chain=chain,
            contract_address=address,
            token_name=token.token_name,
            symbol=token.symbol,
            logo_url=token.logo_url,
            search_count=cnt,
            trend_score=trend_score,
            dex=token.dex,
            verified=token.verified,
            rank_position=rank,
        ))

    await db.commit()
    logger.info("Trending tokens refreshed: %d entries", rank)
    return rank
