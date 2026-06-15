"""
On-chain analytics REST endpoints.

All endpoints identify tokens by chain + contract/mint address (never symbols).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.onchain.services.onchain_service import onchain_service
from app.onchain.services.live_analysis_service import live_analysis_service
from app.onchain.tracked_tokens import find_tracked_token, require_tracked_token
from app.onchain.types import SUPPORTED_CHAINS, validate_token_address
from app.onchain.utils.time_range import parse_date_param
from app.onchain.pipelines.etl_pipeline import run_full_etl
from app.schemas.onchain import (
    HolderSnapshotSchema,
    LiquidityEventSchema,
    LiveTradeSchema,
    OhlcvCandleSchema,
    OhlcvResponseSchema,
    OnchainAnalysisSchema,
    OnchainSignalSchema,
    OnchainSyncResponse,
    OnchainTradeSchema,
    PaginatedTradesResponse,
    PaginatedWhalesResponse,
    PoolInfoSchema,
    SmartMoneyWalletSchema,
    TokenMetricsSchema,
    TokenOverviewSchema,
    TradeHeatmapSchema,
    WalletStatSchema,
    WhaleEventSchema,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onchain", tags=["onchain"])


def _validate_chain(chain: str) -> str:
    chain = chain.lower()
    if chain not in {c.value for c in SUPPORTED_CHAINS}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported chain '{chain}'. Supported: ethereum, base, solana",
        )
    return chain


def _normalize(chain: str, address: str) -> str:
    try:
        normalized = validate_token_address(chain, address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    require_tracked_token(chain, normalized)
    return normalized


def _parse_range(
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[Optional[datetime], Optional[datetime]]:
    try:
        start = parse_date_param(start_date, end_of_day=False)
        end = parse_date_param(end_date, end_of_day=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if start and end and start > end:
        start, end = end, start
    return start, end


def _query_hours(
    since: Optional[datetime],
    until: Optional[datetime],
    hours: Optional[int],
    *,
    default: int = 24,
) -> Optional[int]:
    """When both bounds are provided, ignore rolling hours window."""
    if since is not None and until is not None:
        return None
    return hours if hours is not None else default


@router.get("/analyze/{address}", response_model=OnchainAnalysisSchema)
async def analyze_token_live(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
):
    """
    Live analysis — fetches OHLCV directly from GeckoTerminal (free API).
    No database sync required. Returns metrics, candles, heatmap, and live trades.
    """
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)

    data = await live_analysis_service.analyze(
        chain, token_address,
        start_date=since,
        end_date=until,
        hours=_query_hours(since, until, hours, default=7),
    )

    metrics = None
    if data.get("metrics"):
        metrics = TokenMetricsSchema.model_validate(data["metrics"])

    heatmap = None
    if data.get("heatmap"):
        heatmap = TradeHeatmapSchema.model_validate(data["heatmap"])

    pool = None
    if data.get("pool"):
        pool = PoolInfoSchema.model_validate(data["pool"])

    return OnchainAnalysisSchema(
        chain=chain,
        token_address=token_address,
        period_start=data["period_start"],
        period_end=data["period_end"],
        data_source=data.get("data_source", "none"),
        error=data.get("error"),
        pool=pool,
        metrics=metrics,
        candles=[OhlcvCandleSchema.model_validate(c) for c in data.get("candles", [])],
        heatmap=heatmap,
        live_trades=[LiveTradeSchema.model_validate(t) for t in data.get("live_trades", [])],
    )


@router.get("/token/{address}", response_model=TokenOverviewSchema)
async def get_token_overview(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD or ISO datetime"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD or ISO datetime"),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    data = await onchain_service.get_token_overview(
        db, chain, token_address,
        hours=_query_hours(since, until, hours),
        start_date=since,
        end_date=until,
    )

    metrics = None
    if data.get("metrics"):
        metrics = TokenMetricsSchema.model_validate(data["metrics"])

    return TokenOverviewSchema(
        chain=chain,
        token_address=token_address,
        metrics=metrics,
        recent_signals=[
            OnchainSignalSchema.model_validate(s)
            for s in data.get("recent_signals", [])
        ],
        ai_insight=data.get("ai_insight"),
        data_source=data.get("data_source", "trades"),
        ohlcv_candle_count=data.get("ohlcv_candle_count", 0),
    )


@router.get("/trades/{address}", response_model=PaginatedTradesResponse)
async def get_trades(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    side: Optional[Literal["BUY", "SELL"]] = Query(None),
    min_usd: Optional[float] = Query(None, ge=0),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    result = await onchain_service.get_trades(
        db, chain, token_address,
        page=page, page_size=page_size,
        side=side, min_usd=min_usd,
        hours=_query_hours(since, until, hours),
        start_date=since, end_date=until,
    )
    return PaginatedTradesResponse(
        items=[OnchainTradeSchema.model_validate(t) for t in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        has_more=result["has_more"],
    )


@router.get("/holders/{address}", response_model=list[HolderSnapshotSchema])
async def get_holders(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    limit: int = Query(30, ge=1, le=100),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    snapshots = await onchain_service.get_holders(
        db, chain, token_address, limit=limit,
        start_date=since, end_date=until,
    )
    return [HolderSnapshotSchema.model_validate(s) for s in snapshots]


@router.get("/whales/{address}", response_model=PaginatedWhalesResponse)
async def get_whales(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    result = await onchain_service.get_whales(
        db, chain, token_address,
        page=page, page_size=page_size,
        hours=_query_hours(since, until, hours),
        start_date=since, end_date=until,
    )
    return PaginatedWhalesResponse(
        items=[WhaleEventSchema.model_validate(w) for w in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/liquidity/{address}", response_model=list[LiquidityEventSchema])
async def get_liquidity(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    limit: int = Query(100, ge=1, le=500),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    events = await onchain_service.get_liquidity(
        db, chain, token_address,
        hours=_query_hours(since, until, hours, default=168),
        limit=limit,
        start_date=since, end_date=until,
    )
    return [LiquidityEventSchema.model_validate(e) for e in events]


@router.get("/smart-money/{address}", response_model=list[SmartMoneyWalletSchema])
async def get_smart_money(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    wallets = await onchain_service.get_smart_money(
        db, chain, token_address, min_score=min_score, limit=limit,
        start_date=since, end_date=until,
    )
    return [SmartMoneyWalletSchema.model_validate(w) for w in wallets]


@router.get("/heatmap/{address}", response_model=TradeHeatmapSchema)
async def get_trade_heatmap(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    data = await onchain_service.get_trade_heatmap(
        db, chain, token_address,
        hours=_query_hours(since, until, hours),
        start_date=since,
        end_date=until,
    )
    return TradeHeatmapSchema.model_validate(data)


@router.get("/ohlcv/{address}", response_model=OhlcvResponseSchema)
async def get_ohlcv(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)
    data = await onchain_service.get_ohlcv(
        db, chain, token_address,
        hours=_query_hours(since, until, hours),
        start_date=since,
        end_date=until,
        limit=limit,
    )
    return OhlcvResponseSchema.model_validate(data)


@router.get("/metrics/{address}", response_model=list[TokenMetricsSchema])
async def get_metrics(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    metrics = await onchain_service.get_metrics(db, chain, token_address, limit=limit)
    return [TokenMetricsSchema.model_validate(m) for m in metrics]


@router.get("/wallet/{wallet}", response_model=WalletStatSchema)
async def get_wallet_stats(
    wallet: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    db: AsyncSession = Depends(get_db),
):
    chain = _validate_chain(chain)
    stat = await onchain_service.get_wallet_stats(db, chain, wallet)
    if not stat:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return WalletStatSchema.model_validate(stat)


@router.post("/sync/{address}", response_model=OnchainSyncResponse)
async def sync_token_data(
    address: str,
    chain: Literal["ethereum", "base", "solana"] = Query("ethereum"),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> OnchainSyncResponse:
    """
    Trigger on-chain ETL sync for a token (GeckoTerminal OHLCV + live trades).
    Pass start_date/end_date to backfill a specific range (max 180 days).
    """
    if not settings.ENABLE_ONCHAIN_PERSISTENCE:
        raise HTTPException(status_code=503, detail="On-chain persistence is disabled")
    chain = _validate_chain(chain)
    token_address = _normalize(chain, address)
    since, until = _parse_range(start_date, end_date)

    try:
        result = await run_full_etl(
            db, chain, token_address,
            start_date=since,
            end_date=until,
        )
        await db.commit()
        return OnchainSyncResponse(
            status="ok",
            chain=chain,
            token_address=token_address,
            **result,
        )
    except Exception as exc:
        logger.exception("On-chain sync failed for %s/%s", chain, token_address)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc
