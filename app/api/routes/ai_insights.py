"""
AI Insights REST endpoints.

GET /api/ai/insights/{symbol}   — full AI analysis (summary + sentiment + drivers)
GET /api/ai/summary/{symbol}    — summary text only
GET /api/ai/sentiment/{symbol}  — quick sentiment + confidence
GET /api/ai/batch/sentiment     — sentiment for multiple symbols at once
GET /api/ai/history/{symbol}    — historical AI summaries
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db.database import get_optional_db
from app.models.ai_summary import AISummary
from app.models.coin_sentiment import CoinSentiment
from app.schemas.ai_insight import (
    AIInsightResponse,
    AISummaryOnlyResponse,
    AISummarySchema,
    BatchSentimentItem,
    CoinSentimentSchema,
)
from app.services.ai import insight_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/insights/{symbol}", response_model=AIInsightResponse)
async def get_full_insights(
    symbol: str,
    db: AsyncSession | None = Depends(get_optional_db),
) -> AIInsightResponse:
    """
    Return the full AI market intelligence for a symbol.
    Serves from DB cache; triggers fresh OpenAI analysis only when stale.
    """
    result = await insight_service.get_insights(db, symbol.upper())
    return AIInsightResponse(**result)


@router.get("/summary/{symbol}", response_model=AISummaryOnlyResponse)
async def get_ai_summary(
    symbol: str,
    db: AsyncSession | None = Depends(get_optional_db),
) -> AISummaryOnlyResponse:
    """Return just the AI-generated summary text for a symbol."""
    result = await insight_service.get_insights(db, symbol.upper())
    return AISummaryOnlyResponse(
        symbol=result["symbol"],
        summary=result.get("summary"),
        last_updated=result.get("last_updated"),
        is_stale=result.get("is_stale", False),
    )


@router.get("/sentiment/{symbol}", response_model=CoinSentimentSchema)
async def get_sentiment(
    symbol: str,
    db: AsyncSession | None = Depends(get_optional_db),
) -> CoinSentimentSchema:
    """
    Return quick sentiment snapshot.
    Reads from coin_sentiment (single row per symbol) first for speed,
    falls back to running full insight generation.
    """
    symbol = symbol.upper()
    if db is not None:
        result = await db.execute(
            select(CoinSentiment).where(CoinSentiment.symbol == symbol)
        )
        coin_sent = result.scalar_one_or_none()
        if coin_sent:
            return CoinSentimentSchema.model_validate(coin_sent)

    insight = await insight_service.get_insights(db, symbol)
    return CoinSentimentSchema(
        symbol=symbol,
        sentiment=insight.get("sentiment", "neutral"),
        confidence=insight.get("confidence", 0),
        updated_at=insight.get("last_updated") or datetime.now(timezone.utc),
    )


@router.get("/batch/sentiment", response_model=list[BatchSentimentItem])
async def batch_sentiment(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. BTC,ETH,SOL"),
    db: AsyncSession | None = Depends(get_optional_db),
) -> list[BatchSentimentItem]:
    """
    Return sentiment for multiple symbols in one request.
    Reads only from the coin_sentiment snapshot table — no AI calls triggered.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:20]
    if not sym_list:
        raise HTTPException(status_code=400, detail="No symbols provided")

    if db is None:
        return [
            BatchSentimentItem(symbol=sym, sentiment="neutral", confidence=0, updated_at=None)
            for sym in sym_list
        ]

    result = await db.execute(
        select(CoinSentiment).where(CoinSentiment.symbol.in_(sym_list))
    )
    rows = list(result.scalars().all())
    row_map = {r.symbol: r for r in rows}

    return [
        BatchSentimentItem(
            symbol=sym,
            sentiment=row_map[sym].sentiment if sym in row_map else "neutral",
            confidence=row_map[sym].confidence if sym in row_map else 0,
            updated_at=row_map[sym].updated_at.isoformat() if sym in row_map else None,
        )
        for sym in sym_list
    ]


@router.get("/history/{symbol}", response_model=list[AISummarySchema])
async def get_insights_history(
    symbol: str,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession | None = Depends(get_optional_db),
) -> list[AISummarySchema]:
    """Return historical AI summary records for a symbol (newest first)."""
    if db is None:
        return []

    result = await db.execute(
        select(AISummary)
        .where(AISummary.symbol == symbol.upper())
        .order_by(desc(AISummary.created_at))
        .limit(limit)
    )
    return [AISummarySchema.model_validate(r) for r in result.scalars().all()]
