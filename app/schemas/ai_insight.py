from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class AISummarySchema(BaseModel):
    id: int
    symbol: str
    summary: Optional[str] = None
    sentiment: Optional[str] = "neutral"
    confidence: int = 0
    positive_factors: list[str] = []
    negative_factors: list[str] = []
    market_impact: Optional[str] = None
    key_events: list[str] = []
    articles_processed: int = 0
    model_used: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CoinSentimentSchema(BaseModel):
    symbol: str
    sentiment: str = "neutral"
    confidence: int = 0
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIInsightResponse(BaseModel):
    """Combined response: AI summary + latest news count + sentiment."""
    symbol: str
    summary: Optional[str] = None
    sentiment: str = "neutral"
    confidence: int = 0
    positive_factors: list[str] = []
    negative_factors: list[str] = []
    market_impact: Optional[str] = None
    key_events: list[str] = []
    articles_processed: int = 0
    last_updated: Optional[datetime] = None
    cache_expires: Optional[datetime] = None
    is_stale: bool = False


class AISummaryOnlyResponse(BaseModel):
    symbol: str
    summary: Optional[str] = None
    last_updated: Optional[datetime] = None
    is_stale: bool = False


class BatchSentimentItem(BaseModel):
    symbol: str
    sentiment: str = "neutral"
    confidence: int = 0
    updated_at: Optional[str] = None
