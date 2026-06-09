"""
News REST endpoints.

GET /api/news/{symbol}         — paginated news articles for a symbol
GET /api/news/{symbol}/latest  — latest 5 articles (no pagination, for sidebar)
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.db.database import get_db
from app.models.news_article import NewsArticle
from app.schemas.news import NewsArticleSchema, NewsListResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])


def _symbol_filter(symbol: str):
    """
    PostgreSQL JSON array filter.

    symbols is stored as a JSON array e.g. ["BTC", "ETH"].
    Uses the @> (contains) operator via SQLAlchemy's .contains().
    """
    return NewsArticle.symbols.contains([symbol])


@router.get("/{symbol}", response_model=NewsListResponse)
async def get_news_for_symbol(
    symbol: str,
    page: int = Query(1, ge=1, le=50),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> NewsListResponse:
    """
    Return paginated news articles that mention the given symbol.
    Articles are ordered newest-first.
    """
    symbol = symbol.upper()
    offset = (page - 1) * page_size

    total_result = await db.execute(
        select(func.count(NewsArticle.id)).where(_symbol_filter(symbol))
    )
    total = total_result.scalar_one() or 0

    articles_result = await db.execute(
        select(NewsArticle)
        .where(_symbol_filter(symbol))
        .order_by(desc(NewsArticle.published_at))
        .offset(offset)
        .limit(page_size)
    )
    articles = list(articles_result.scalars().all())

    return NewsListResponse(
        symbol=symbol,
        articles=[NewsArticleSchema.model_validate(a) for a in articles],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{symbol}/latest", response_model=list[NewsArticleSchema])
async def get_latest_news(
    symbol: str,
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[NewsArticleSchema]:
    """Return the N most recent articles for a symbol — fast sidebar feed."""
    symbol = symbol.upper()
    result = await db.execute(
        select(NewsArticle)
        .where(_symbol_filter(symbol))
        .order_by(desc(NewsArticle.published_at))
        .limit(limit)
    )
    articles = list(result.scalars().all())
    return [NewsArticleSchema.model_validate(a) for a in articles]
