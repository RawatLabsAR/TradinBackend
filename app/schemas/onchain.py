"""Pydantic schemas for on-chain analytics API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, AliasChoices


class OnchainTradeSchema(BaseModel):
    id: int
    chain: str
    token_address: str
    wallet: str
    side: str
    amount: float
    usd_value: float
    price_usd: Optional[float] = None
    timestamp: datetime
    dex: str = ""
    tx_hash: str = ""
    block_number: Optional[int] = None
    raw_source: str = ""

    model_config = {"from_attributes": True}


class WalletStatSchema(BaseModel):
    chain: str
    wallet: str
    total_trades: int
    buy_count: int
    sell_count: int
    total_volume_usd: float
    realized_pnl_usd: float
    win_rate: float
    avg_roi_pct: float
    trade_accuracy: float
    smart_money_score: float
    is_whale: bool
    is_smart_money: bool
    is_sniper: bool
    first_seen_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HolderSnapshotSchema(BaseModel):
    chain: str
    token_address: str
    holder_count: int
    top10_pct: float
    top50_pct: float
    snapshot_at: datetime
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "metadata_json"),
    )

    model_config = {"from_attributes": True, "populate_by_name": True}


class LiquidityEventSchema(BaseModel):
    id: int
    chain: str
    token_address: str
    pool_address: str = ""
    event_type: str
    wallet: str = ""
    token_amount: float = 0.0
    usd_value: float = 0.0
    liquidity_usd: float = 0.0
    timestamp: datetime
    tx_hash: str = ""
    dex: str = ""

    model_config = {"from_attributes": True}


class WhaleEventSchema(BaseModel):
    id: Optional[int] = None
    chain: str
    wallet: str
    token_address: str
    event_type: str
    usd_value: float
    description: str
    tx_hash: str = ""
    detected_at: datetime
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_json"),
    )

    model_config = {"from_attributes": True, "populate_by_name": True}


class SmartMoneyWalletSchema(BaseModel):
    chain: str
    wallet: str
    token_address: str
    score: float
    win_rate: float
    avg_roi_pct: float
    trade_accuracy: float
    total_volume_usd: float
    last_trade_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenMetricsSchema(BaseModel):
    chain: str
    token_address: str
    buy_volume_usd: float
    sell_volume_usd: float
    net_flow_usd: float
    unique_wallets: int
    unique_buyers: int
    unique_sellers: int
    whale_buy_volume_usd: float
    whale_sell_volume_usd: float
    smart_money_score_avg: float
    holder_count: int
    holder_growth_pct: float
    liquidity_usd: float
    liquidity_change_pct: float
    early_buyer_count: int
    sniper_count: int
    period_start: datetime
    period_end: datetime
    computed_at: datetime
    data_source: str = "trades"
    total_volume_usd: float = 0.0
    price_open_usd: float = 0.0
    price_close_usd: float = 0.0
    price_high_usd: float = 0.0
    price_low_usd: float = 0.0
    price_change_pct: float = 0.0
    candle_count: int = 0

    model_config = {"from_attributes": True, "extra": "ignore"}


class OnchainSignalSchema(BaseModel):
    signal_type: str
    severity: str
    title: str
    description: str
    usd_value: float = 0.0
    wallet: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TokenOverviewSchema(BaseModel):
    chain: str
    token_address: str
    metrics: Optional[TokenMetricsSchema] = None
    recent_signals: list[OnchainSignalSchema] = Field(default_factory=list)
    ai_insight: Optional[str] = None
    data_source: str = "trades"
    ohlcv_candle_count: int = 0


class OhlcvCandleSchema(BaseModel):
    timestamp: datetime
    open_usd: float
    high_usd: float
    low_usd: float
    close_usd: float
    volume_usd: float
    timeframe: str = "hour"
    aggregate: int = 1


class OhlcvResponseSchema(BaseModel):
    chain: str
    token_address: str
    period_start: datetime
    period_end: datetime
    candle_count: int
    data_source: str
    candles: list[OhlcvCandleSchema] = Field(default_factory=list)


class LiveTradeSchema(BaseModel):
    id: int
    chain: str
    token_address: str
    wallet: str
    side: str
    amount: float
    usd_value: float
    price_usd: Optional[float] = None
    timestamp: datetime
    dex: str = ""
    tx_hash: str = ""
    raw_source: str = ""


class PoolInfoSchema(BaseModel):
    address: Optional[str] = None
    dex: Optional[str] = None
    liquidity_usd: float = 0.0
    volume_h24_usd: float = 0.0
    price_usd: float = 0.0


class OnchainAnalysisSchema(BaseModel):
    chain: str
    token_address: str
    period_start: datetime
    period_end: datetime
    data_source: str
    error: Optional[str] = None
    pool: Optional[PoolInfoSchema] = None
    metrics: Optional[TokenMetricsSchema] = None
    candles: list[OhlcvCandleSchema] = Field(default_factory=list)
    heatmap: Optional[TradeHeatmapSchema] = None
    live_trades: list[LiveTradeSchema] = Field(default_factory=list)


class PaginatedTradesResponse(BaseModel):
    items: list[OnchainTradeSchema]
    total: int
    page: int
    page_size: int
    has_more: bool


class PaginatedWhalesResponse(BaseModel):
    items: list[WhaleEventSchema]
    total: int
    page: int
    page_size: int


class HeatmapBucketSchema(BaseModel):
    label: str
    buy_usd: float = 0.0
    sell_usd: float = 0.0
    total_usd: float = 0.0


class TradeHeatmapSchema(BaseModel):
    chain: str
    token_address: str
    period_start: datetime
    period_end: datetime
    bucket_mode: str
    bucket_count: int
    active_buckets: int
    trade_count: int
    data_source: str = "trades"
    buckets: list[HeatmapBucketSchema]


class OnchainQueryParams(BaseModel):
    chain: Literal["ethereum", "base", "solana"] = "ethereum"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    side: Optional[Literal["BUY", "SELL"]] = None
    min_usd: Optional[float] = None
    hours: int = Field(default=24, ge=1, le=720)


class OnchainSyncResponse(BaseModel):
    status: str
    chain: str
    token_address: str
    ohlcv: dict[str, Any] = Field(default_factory=dict)
    trades: dict[str, Any] = Field(default_factory=dict)
    liquidity: dict[str, Any] = Field(default_factory=dict)
    holders: dict[str, Any] = Field(default_factory=dict)
    analytics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}
