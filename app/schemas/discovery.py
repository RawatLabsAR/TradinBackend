"""Pydantic schemas for discovery API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DiscoveryTokenSchema(BaseModel):
    token_name: str
    symbol: str
    chain: str
    contract_address: str = ""
    logo_url: str = ""
    market_cap: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0
    price_usd: float = 0.0
    price_change_24h: float = 0.0
    verified: bool = False
    dex: str = ""
    pair_address: str = ""
    source: str = ""
    growth_score: float = 0.0
    discovery_category: str = ""
    age_hours: float = 0.0
    volume_change_pct: float = 0.0
    source_type: str = "dex"
    product_id: str = ""
    risk_level: str = "high"
    pool_created_at: Optional[str] = None
    buy_sell_ratio: float = 0.0
    tx_count_24h: int = 0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class DiscoveryResponse(BaseModel):
    category: str
    total: int
    items: list[DiscoveryTokenSchema]
    sources_used: list[str] = Field(default_factory=list)
    scanned_at: str = ""
    cached: bool = False
    empty_reason: Optional[str] = None


class DiscoveryOverviewResponse(BaseModel):
    new_dex_count: int = 0
    new_cex_count: int = 0
    surging_count: int = 0
    trending_count: int = 0
    last_scanned_at: str = ""
