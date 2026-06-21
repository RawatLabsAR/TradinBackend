"""Pydantic schemas for whale scanner web API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.onchain import WhaleEventSchema


class WhaleScanEventSummary(BaseModel):
    event_type: str
    count: int


class WhaleScanHitSchema(BaseModel):
    chain: str
    contract_address: str
    symbol: Optional[str] = None
    token_name: Optional[str] = None
    dex: Optional[str] = None
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    age_hours: float = 0.0
    last_scanned_at: Optional[str] = None
    max_usd: float = 0.0
    score: float = 0.0
    event_summary: list[WhaleScanEventSummary] = Field(default_factory=list)
    notified_at: Optional[str] = None


class WhaleScanOverviewResponse(BaseModel):
    last_run_at: str = ""
    last_run_status: str = "never"
    tokens_scanned: int = 0
    whales_detected: int = 0
    hits_count: int = 0
    threshold_usd: float = 0.0
    lookback_hours: int = 24
    max_age_days: int = 30


class WhaleScanHitsResponse(BaseModel):
    total: int
    items: list[WhaleScanHitSchema]
    scanned_at: str = ""
    page: int = 1
    page_size: int = 50


class WhaleScanRunStatusResponse(BaseModel):
    run_id: Optional[int] = None
    status: str = "idle"
    phase: str = ""
    phase_label: str = ""
    total: int = 0
    completed: int = 0
    percent: int = 0
    is_running: bool = False
    candidates_found: int = 0
    tokens_scanned: int = 0
    whales_detected: int = 0
    messages_sent: int = 0
    current_token: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: Optional[str] = None


class WhaleScanDetailResponse(BaseModel):
    chain: str
    contract_address: str
    symbol: Optional[str] = None
    token_name: Optional[str] = None
    dex: Optional[str] = None
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    age_hours: float = 0.0
    last_scanned_at: Optional[str] = None
    max_usd: float = 0.0
    score: float = 0.0
    event_summary: list[WhaleScanEventSummary] = Field(default_factory=list)
    events: list[WhaleEventSchema] = Field(default_factory=list)
    total_events: int = 0
    page: int = 1
    page_size: int = 50
    threshold_usd: float = 0.0
    lookback_hours: int = 24
