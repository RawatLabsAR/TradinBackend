from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class NewsArticleSchema(BaseModel):
    id: int
    external_id: str
    title: str
    description: Optional[str] = None
    url: str
    image_url: Optional[str] = None
    published_at: datetime
    source_name: Optional[str] = None
    source_domain: Optional[str] = None
    kind: str = "news"
    symbols: list[str] = []
    votes_positive: int = 0
    votes_negative: int = 0
    panic_score: int = 0

    model_config = {"from_attributes": True}


class NewsListResponse(BaseModel):
    symbol: str
    articles: list[NewsArticleSchema]
    total: int
    page: int
    page_size: int
