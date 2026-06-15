from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WatchlistResponse(BaseModel):
    items: list[str]


class WatchlistReplace(BaseModel):
    items: list[str] = Field(default_factory=list)


class PortfolioHoldingOut(BaseModel):
    product_id: str
    quantity: float
    avg_cost: float
    added_at: datetime

    model_config = {"from_attributes": True}


class PortfolioResponse(BaseModel):
    holdings: list[PortfolioHoldingOut]


class PortfolioHoldingCreate(BaseModel):
    product_id: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0)


class PortfolioHoldingUpdate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, ge=0)


class PortfolioHoldingReplaceItem(BaseModel):
    product_id: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0)
    added_at: datetime | None = None


class PortfolioReplace(BaseModel):
    holdings: list[PortfolioHoldingReplaceItem] = Field(default_factory=list)
