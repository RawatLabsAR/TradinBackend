from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

PaperSide = Literal["long", "short"]
PaperSource = Literal["manual", "coin_detail", "strategy"]
PaperOrderType = Literal["market", "limit"]
PaperStatus = Literal["open", "closed", "all", "pending"]


class PaperTradeCreate(BaseModel):
    product_id: str = Field(min_length=3, max_length=32)
    side: PaperSide
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    fee_pct: float = Field(default=0.001, ge=0, le=0.05)
    notes: Optional[str] = Field(default=None, max_length=500)
    source: PaperSource = "manual"
    order_type: PaperOrderType = "market"
    limit_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)
    script_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_limit(self) -> "PaperTradeCreate":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class PaperTradeClose(BaseModel):
    exit_price: float = Field(gt=0)
    quantity: Optional[float] = Field(default=None, gt=0)


class PaperTradeOut(BaseModel):
    id: int
    product_id: str
    side: PaperSide
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    fee_pct: float
    pnl: Optional[float]
    pnl_pct: Optional[float]
    notes: Optional[str]
    source: Optional[str]
    order_type: str = "market"
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    script_id: Optional[int] = None
    is_pending: bool = False
    opened_at: datetime
    closed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaperTradeStats(BaseModel):
    open_count: int
    closed_count: int
    pending_count: int = 0
    total_realized_pnl: float
    win_count: int
    loss_count: int
    win_rate_pct: float


class PaperTradeListResponse(BaseModel):
    items: list[PaperTradeOut]
    total: int
    stats: PaperTradeStats


class PaperMarkToMarketItem(BaseModel):
    id: int
    product_id: str
    side: PaperSide
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class PaperMarkToMarketResponse(BaseModel):
    items: list[PaperMarkToMarketItem]
    total_unrealized_pnl: float


class PaperJournalPoint(BaseModel):
    date: str
    cumulative_pnl: float
    equity: float


class PaperJournalAnalytics(BaseModel):
    equity_curve: list[PaperJournalPoint]
    by_symbol: dict[str, float]
    by_source: dict[str, float]
    max_drawdown_pct: float
    total_realized_pnl: float
    win_rate_pct: float
    trade_count: int
