from fastapi import APIRouter, HTTPException, Query

from app.services import market_service
from app.schemas.candle import (
    CandleResponse,
    TimeframeConfigResponse,
    TimeframeEntry,
    TimeframeType,
    TIMEFRAME_CONFIG,
)

router = APIRouter(prefix="/candles", tags=["candles"])


@router.get("/timeframes", response_model=TimeframeConfigResponse)
async def get_timeframe_config() -> TimeframeConfigResponse:
    """Return supported candle timeframes and their backend configuration."""
    return TimeframeConfigResponse(
        timeframes={
            tf: TimeframeEntry(
                granularity=cfg["granularity"],
                interval_seconds=cfg["interval_seconds"],
                default_bars=cfg["default_bars"],
            )
            for tf, cfg in TIMEFRAME_CONFIG.items()
        }
    )


@router.get("/{product_id}", response_model=CandleResponse)
async def get_candles(
    product_id: str,
    timeframe: TimeframeType = Query(default="1D"),
    limit: int | None = Query(default=None, ge=10, le=1000),
):
    """
    Get historical OHLCV candles for a product and timeframe.

    Timeframe options: 1m, 5m, 15m, 1H, 4H, 1D, 1W, 1M
    """
    if timeframe not in TIMEFRAME_CONFIG:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}")

    config = TIMEFRAME_CONFIG[timeframe]
    bar_limit = limit or config["default_bars"]

    candles = await market_service.get_candles(product_id.upper(), timeframe, bar_limit)
    if not candles:
        raise HTTPException(
            status_code=404,
            detail=f"No candle data found for {product_id} ({timeframe})",
        )
    return CandleResponse(
        product_id=product_id.upper(),
        timeframe=timeframe,
        granularity=config["granularity"],
        candles=candles,
        count=len(candles),
    )
