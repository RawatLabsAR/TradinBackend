"""Pydantic schemas for token search API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TokenResultSchema(BaseModel):
    token_name: str
    symbol: str
    chain: str
    contract_address: str
    logo_url: str = ""
    market_cap: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0
    price_usd: float = 0.0
    price_change_24h: float = 0.0
    verified: bool = False
    dex: str = ""
    pair_address: str = ""
    rank_score: float = 0.0
    source: str = ""
    ai_summary: Optional[str] = None

    model_config = {"from_attributes": True}


class TokenSearchResponse(BaseModel):
    query: str
    total: int
    items: list[TokenResultSchema]
    sources_used: list[str] = Field(default_factory=list)
    cached: bool = False
    took_ms: float = 0.0


class TrendingTokenSchema(BaseModel):
    token_name: str
    symbol: str
    chain: str
    contract_address: str
    logo_url: str = ""
    volume_24h: float = 0.0
    liquidity: float = 0.0
    market_cap: float = 0.0
    search_count: int = 0
    trend_score: float = 0.0
    dex: str = ""
    verified: bool = False


class RecentSearchSchema(BaseModel):
    query: str
    chain: str
    contract_address: str
    symbol: str
    searched_at: str


class TokenDetailResponse(BaseModel):
    token: TokenResultSchema
    ai_summary: Optional[str] = None
    onchain_url: str = ""


class RecordSearchRequest(BaseModel):
    query: str
    session_id: str = "anonymous"
    chain: str = ""
    contract_address: str = ""
    symbol: str = ""


class BroadcastTokenRequest(BaseModel):
    chain: str
    contract_address: str
    message: str = ""


class BroadcastTokenResponse(BaseModel):
    status: str
    symbol: str
