from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

PaperSide = Literal["long", "short"]
PaperSource = Literal["manual", "coin_detail", "strategy"]
PaperStatus = Literal["open", "closed", "all"]


class PaperTradeCreate(BaseModel):
    product_id: str = Field(min_length=3, max_length=32)
    side: PaperSide
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    fee_pct: float = Field(default=0.001, ge=0, le=0.05)
    notes: Optional[str] = Field(default=None, max_length=500)
    source: PaperSource = "manual"


class PaperTradeClose(BaseModel):
    exit_price: float = Field(gt=0)


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
    opened_at: datetime
    closed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaperTradeListResponse(BaseModel):
    items: list[PaperTradeOut]
    total: int
    stats: "PaperTradeStats"


class PaperTradeStats(BaseModel):
    open_count: int
    closed_count: int
    total_realized_pnl: float
    win_count: int
    loss_count: int
    win_rate_pct: float
