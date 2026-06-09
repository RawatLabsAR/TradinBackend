from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


AlertDirection = Literal["above", "below"]


class PriceAlertCreate(BaseModel):
    product_id: str
    target_price: float = Field(gt=0)
    direction: AlertDirection = "above"
    message: Optional[str] = None
    notify_telegram: bool = False
    channel_id: Optional[int] = None


class PriceAlertUpdate(BaseModel):
    is_active: Optional[bool] = None
    target_price: Optional[float] = Field(default=None, gt=0)
    message: Optional[str] = None
    notify_telegram: Optional[bool] = None
    channel_id: Optional[int] = None


class PriceAlertOut(BaseModel):
    id: int
    product_id: str
    target_price: float
    direction: AlertDirection
    message: Optional[str]
    is_active: bool
    notify_telegram: bool
    channel_id: Optional[int]
    triggered_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
