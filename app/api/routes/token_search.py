"""
Token discovery REST endpoints.

Users search by symbol/name; system resolves to chain + contract_address.
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.onchain.tracked_tokens import find_tracked_token
from app.schemas.common import StatusResponse
from app.schemas.token_search import (
    BroadcastTokenRequest,
    BroadcastTokenResponse,
    RecentSearchSchema,
    RecordSearchRequest,
    TokenDetailResponse,
    TokenResultSchema,
    TokenSearchResponse,
    TrendingTokenSchema,
)
from app.token_search.services.ai_insights import generate_token_ai_summary
from app.token_search.services.search_service import token_search_service
from app.token_search.services.telegram_alerts import broadcast_token_alert
from app.token_search.types import NormalizedToken
from app.token_search.utils.query_utils import normalize_search_query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/token", tags=["token-search"])

_QUERY_RE = re.compile(r"^[\w\s\-./_]{1,64}$", re.UNICODE)


def _sanitize_query(q: str) -> str:
    q = q.strip()
    if not q or len(q) > 64:
        raise HTTPException(status_code=400, detail="Query must be 1-64 characters")
    if not _QUERY_RE.match(q):
        raise HTTPException(status_code=400, detail="Invalid characters in query")
    return normalize_search_query(q)


def _to_schema(token: NormalizedToken, ai_summary: Optional[str] = None) -> TokenResultSchema:
    return TokenResultSchema(
        token_name=token.token_name,
        symbol=token.symbol,
        chain=token.chain,
        contract_address=token.contract_address,
        logo_url=token.logo_url,
        market_cap=token.market_cap,
        liquidity=token.liquidity,
        volume_24h=token.volume_24h,
        price_usd=token.price_usd,
        price_change_24h=token.price_change_24h,
        verified=token.verified,
        dex=token.dex,
        pair_address=token.pair_address,
        rank_score=token.rank_score,
        source=token.source,
        ai_summary=ai_summary,
    )


@router.get("/search", response_model=TokenSearchResponse)
async def search_tokens(
    q: str = Query(..., min_length=1, max_length=64),
    chain: Optional[Literal["ethereum", "base", "solana", "bsc", "arbitrum", "polygon"]] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    query = _sanitize_query(q)
    result = await token_search_service.search(db, query, limit=limit, chain=chain)
    return TokenSearchResponse(
        query=result.query,
        total=result.total,
        items=[_to_schema(t) for t in result.items],
        sources_used=result.sources_used,
        cached=result.cached,
        took_ms=result.took_ms,
    )


@router.get("/trending", response_model=list[TrendingTokenSchema])
async def get_trending(
    chain: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    entries = await token_search_service.get_trending(db, limit=limit, chain=chain)
    return [TrendingTokenSchema.model_validate(e.model_dump()) for e in entries]


@router.get("/resolve/{symbol}", response_model=TokenSearchResponse)
async def resolve_symbol(
    symbol: str,
    chain: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    sym = _sanitize_query(symbol)
    result = await token_search_service.resolve_symbol(db, sym, chain=chain, limit=limit)
    return TokenSearchResponse(
        query=result.query,
        total=result.total,
        items=[_to_schema(t) for t in result.items],
        sources_used=result.sources_used,
        cached=result.cached,
        took_ms=result.took_ms,
    )


@router.get("/recent-searches", response_model=list[RecentSearchSchema])
async def recent_searches(
    session_id: str = Query("anonymous"),
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    items = await token_search_service.get_recent_searches(db, session_id, limit=limit)
    return [RecentSearchSchema.model_validate(i) for i in items]


@router.get("/{contract_address}", response_model=TokenDetailResponse)
async def get_token_detail(
    contract_address: str,
    chain: Literal["ethereum", "base", "solana", "bsc", "arbitrum", "polygon"] = Query(...),
    include_ai: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    if len(contract_address) < 20:
        raise HTTPException(status_code=400, detail="Invalid contract address")

    token = await token_search_service.get_token_detail(db, chain, contract_address)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    ai_summary = None
    if include_ai:
        ai_summary = await generate_token_ai_summary(token)

    tracked = find_tracked_token(chain, contract_address)
    return TokenDetailResponse(
        token=_to_schema(token, ai_summary=ai_summary),
        ai_summary=ai_summary,
        onchain_url=f"/onchain?token={tracked['id']}" if tracked else "",
    )


@router.post("/record-search", response_model=StatusResponse)
async def record_search(
    body: RecordSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    selected = None
    if body.chain and body.contract_address:
        selected = NormalizedToken(
            token_name=body.symbol,
            symbol=body.symbol,
            chain=body.chain,
            contract_address=body.contract_address,
        )
    await token_search_service.record_search(
        db,
        session_id=body.session_id,
        query=body.query,
        selected=selected,
    )
    return StatusResponse(status="ok")


@router.post("/broadcast", response_model=BroadcastTokenResponse)
async def broadcast_token(
    body: BroadcastTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> BroadcastTokenResponse:
    token = await token_search_service.get_token_detail(db, body.chain, body.contract_address)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    ok = await broadcast_token_alert(db, token, message=body.message)
    if not ok:
        raise HTTPException(status_code=503, detail="Telegram broadcast unavailable")
    return BroadcastTokenResponse(status="queued", symbol=token.symbol)
