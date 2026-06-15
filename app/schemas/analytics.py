"""Schemas for advanced analytics endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class FundingRateItem(BaseModel):
    symbol: str
    product_id: str
    funding_rate: float
    funding_rate_pct: float
    next_funding_time: Optional[str] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    open_interest: Optional[float] = None
    open_interest_usd: Optional[float] = None
    source: Optional[str] = None
    secondary_funding_rate_pct: Optional[float] = None
    secondary_source: Optional[str] = None


class FundingRatesResponse(BaseModel):
    items: list[FundingRateItem]
    source: str
    updated_at: str


class CorrelationPair(BaseModel):
    symbol_a: str
    symbol_b: str
    correlation: float
    period_days: int


class CorrelationMatrixResponse(BaseModel):
    symbols: list[str]
    matrix: list[list[float]]
    pairs: list[CorrelationPair]
    period_days: int


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBookResponse(BaseModel):
    product_id: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    spread: float
    spread_pct: float
    bid_depth_usd: float
    ask_depth_usd: float
    imbalance: float
    mid_price: float
    source: str


class LiquidationLevel(BaseModel):
    price: float
    side: Literal["long", "short"]
    estimated_usd: float
    leverage: int


class LiquidationHeatmapResponse(BaseModel):
    product_id: str
    current_price: float
    open_interest_usd: Optional[float] = None
    levels: list[LiquidationLevel]
    source: Optional[str] = None
    note: str


class TimeframeSignal(BaseModel):
    timeframe: str
    trend: Literal["bullish", "bearish", "neutral"]
    rsi: float
    ema_cross: Literal["golden", "death", "none"]
    score: int


class MtfConfluenceResponse(BaseModel):
    product_id: str
    signals: list[TimeframeSignal]
    overall_score: int
    bias: Literal["bullish", "bearish", "neutral"]
    confluence_pct: float


class ExchangePriceItem(BaseModel):
    exchange: str
    product_id: str
    price: float
    volume_24h: Optional[float] = None
    change_24h_pct: Optional[float] = None


class ExchangeCompareResponse(BaseModel):
    symbol: str
    items: list[ExchangePriceItem]
    spread_pct: float
    arb_opportunity: bool


class TokenSafetyCheck(BaseModel):
    chain: str
    address: str
    symbol: str
    score: int
    risk_level: Literal["low", "medium", "high", "critical"]
    flags: list[str]
    liquidity_usd: Optional[float] = None
    holder_concentration_pct: Optional[float] = None
    is_verified: bool = False
    recommendations: list[str]


class VolatilityItem(BaseModel):
    product_id: str
    atr_14: float
    atr_pct: float
    realized_vol_30d: float
    regime: Literal["low", "normal", "high", "extreme"]
    percentile_90d: float


class VolatilityResponse(BaseModel):
    items: list[VolatilityItem]
    updated_at: str


class EventItem(BaseModel):
    id: str
    title: str
    symbol: str
    event_type: str
    date: str
    impact: Literal["low", "medium", "high"]
    description: str


class EventsResponse(BaseModel):
    items: list[EventItem]
    total: int
    source: Optional[str] = None


class FearGreedPoint(BaseModel):
    value: int
    classification: str
    timestamp: Optional[str] = None


class FearGreedResponse(BaseModel):
    current: Optional[FearGreedPoint] = None
    history: list[FearGreedPoint]
    source: str
    updated_at: str


class GlobalOverviewResponse(BaseModel):
    total_market_cap_usd: Optional[float] = None
    total_volume_24h_usd: Optional[float] = None
    btc_dominance_pct: Optional[float] = None
    eth_dominance_pct: Optional[float] = None
    market_cap_change_24h_pct: Optional[float] = None
    active_cryptocurrencies: Optional[int] = None
    markets: Optional[int] = None
    source: str
    updated_at: str


class ScreenerFilter(BaseModel):
    min_volume_24h: Optional[float] = None
    max_volume_24h: Optional[float] = None
    min_change_24h: Optional[float] = None
    max_change_24h: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    quote: str = "USD"
    sort_by: str = "volume_24h"
    sort_dir: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=50, ge=1, le=200)


class ScreenerItem(BaseModel):
    product_id: str
    base_name: str
    price: float
    change_24h_pct: float
    volume_24h: float
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None


class ScreenerResponse(BaseModel):
    total: int
    items: list[ScreenerItem]
    filters_applied: dict[str, Any]


class BridgeFlowItem(BaseModel):
    chain: str
    bridge: str
    inflow_usd_24h: float
    outflow_usd_24h: float
    net_flow_usd: float
    tvl_usd: Optional[float] = None


class BridgeFlowsResponse(BaseModel):
    items: list[BridgeFlowItem]
    total_net_inflow_usd: float
    stablecoin_supply_usd: Optional[float] = None
    source: Optional[str] = None
    note: str
    updated_at: Optional[str] = None


class WalletTrackRequest(BaseModel):
    chain: str
    wallet: str
    label: Optional[str] = None


class WalletTrackItem(BaseModel):
    chain: str
    wallet: str
    label: Optional[str] = None
    total_trades: int = 0
    total_volume_usd: float = 0
    smart_money_score: float = 0
    last_active_at: Optional[str] = None


AlertType = Literal["price", "percent_change", "volume_spike", "rsi", "funding"]


class AdvancedAlertCreate(BaseModel):
    product_id: str
    alert_type: AlertType = "price"
    target_price: Optional[float] = Field(default=None, gt=0)
    direction: Optional[Literal["above", "below"]] = "above"
    percent_threshold: Optional[float] = None
    rsi_threshold: Optional[float] = None
    rsi_condition: Optional[Literal["above", "below"]] = None
    message: Optional[str] = None
    notify_telegram: bool = False
    channel_id: Optional[int] = None
