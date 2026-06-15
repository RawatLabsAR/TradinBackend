"""Advanced analytics REST endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.analytics import (
    bridge_service,
    correlation_service,
    events_service,
    exchange_compare_service,
    fear_greed_service,
    funding_service,
    liquidation_service,
    market_overview_service,
    mtf_service,
    orderbook_service,
    screener_service,
    token_safety_service,
    volatility_service,
)
from app.schemas.analytics import (
    BridgeFlowsResponse,
    CorrelationMatrixResponse,
    EventsResponse,
    ExchangeCompareResponse,
    FearGreedResponse,
    FundingRatesResponse,
    GlobalOverviewResponse,
    LiquidationHeatmapResponse,
    MtfConfluenceResponse,
    OrderBookResponse,
    ScreenerResponse,
    TokenSafetyCheck,
    VolatilityResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/funding", response_model=FundingRatesResponse)
async def funding_rates(
    symbols: Optional[str] = Query(None, description="Comma-separated symbols e.g. BTC,ETH"),
):
    sym_list = [s.strip() for s in symbols.split(",")] if symbols else None
    return await funding_service.get_funding_rates(sym_list)


@router.get("/correlation", response_model=CorrelationMatrixResponse)
async def correlation(
    symbols: Optional[str] = Query(None),
    period_days: int = Query(30, ge=7, le=90),
):
    sym_list = [s.strip() for s in symbols.split(",")] if symbols else None
    if sym_list:
        sym_list = [s if "-USD" in s else f"{s}-USD" for s in sym_list]
    return await correlation_service.get_correlation_matrix(sym_list, period_days)


@router.get("/orderbook/{product_id}", response_model=OrderBookResponse)
async def orderbook(product_id: str, depth: int = Query(20, ge=5, le=50)):
    return await orderbook_service.get_orderbook(product_id, depth)


@router.get("/liquidations/{product_id}", response_model=LiquidationHeatmapResponse)
async def liquidations(product_id: str):
    return await liquidation_service.get_liquidation_levels(product_id)


@router.get("/mtf/{product_id}", response_model=MtfConfluenceResponse)
async def mtf_confluence(product_id: str):
    return await mtf_service.get_mtf_confluence(product_id)


@router.get("/compare/{symbol}", response_model=ExchangeCompareResponse)
async def exchange_compare(symbol: str):
    return await exchange_compare_service.compare_exchanges(symbol)


@router.get("/safety/{chain}/{address}", response_model=TokenSafetyCheck)
async def token_safety(chain: str, address: str):
    return await token_safety_service.scan_token_safety(chain, address)


@router.get("/volatility", response_model=VolatilityResponse)
async def volatility(symbols: Optional[str] = Query(None)):
    sym_list = None
    if symbols:
        sym_list = [s if "-USD" in s else f"{s}-USD" for s in symbols.split(",")]
    return await volatility_service.get_volatility(sym_list)


@router.get("/events", response_model=EventsResponse)
async def events(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=50),
):
    return await events_service.get_events(symbol, limit)


@router.get("/screener", response_model=ScreenerResponse)
async def screener(
    min_volume_24h: Optional[float] = Query(None),
    max_volume_24h: Optional[float] = Query(None),
    min_change_24h: Optional[float] = Query(None),
    max_change_24h: Optional[float] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort_by: str = Query("volume_24h"),
    sort_dir: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
):
    return await screener_service.run_screener(
        min_volume_24h=min_volume_24h,
        max_volume_24h=max_volume_24h,
        min_change_24h=min_change_24h,
        max_change_24h=max_change_24h,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )


@router.get("/bridges", response_model=BridgeFlowsResponse)
async def bridge_flows():
    return await bridge_service.get_bridge_flows()


@router.get("/fear-greed", response_model=FearGreedResponse)
async def fear_greed(limit: int = Query(30, ge=1, le=90)):
    return await fear_greed_service.get_fear_greed(limit)


@router.get("/global", response_model=GlobalOverviewResponse)
async def global_overview():
    return await market_overview_service.get_global_overview()
