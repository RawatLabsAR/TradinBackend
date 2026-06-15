"""
Main AI orchestration service.

Primary flow (web-search mode):
  1. Check DB cache — return cached insight if still fresh.
  2. Call OpenAI Responses API with web_search_preview tool:
       - OpenAI searches the live web for recent {symbol} news
       - Returns structured JSON: summary, sentiment, drivers, sources
  3. Persist results to ai_summaries + coin_sentiment + market_insights.
  4. Persist sources returned by OpenAI as news_articles (deduplication).
  5. Return structured insight dict.

Fallback flow (if Responses API fails, e.g. model doesn't support web search):
  - Pull latest GNews articles from DB and send to chat_json().

Frontend NEVER calls OpenAI directly.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, desc, func

from app.core.cache import cache
from app.core.config import settings
from app.models.ai_summary import AISummary
from app.models.coin_sentiment import CoinSentiment
from app.models.market_insight import MarketInsight
from app.models.news_article import NewsArticle
from app.services.ai import openai_service
from app.services.ai.prompt_templates import (
    SYSTEM_PROMPT,
    WEB_SEARCH_ANALYSIS_PROMPT,
    NEWS_ANALYSIS_PROMPT,
    NO_NEWS_PROMPT,
    build_news_block,
)
from app.services.news.news_normalizer import upsert_articles

logger = logging.getLogger(__name__)

_COIN_NAMES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "DOGE": "Dogecoin",
    "XRP": "XRP",
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "MATIC": "Polygon",
    "LTC": "Litecoin",
    "SHIB": "Shiba Inu",
    "UNI": "Uniswap",
}

_FALLBACK_RESPONSE = {
    "summary": "AI analysis is currently unavailable. Please check back later.",
    "sentiment": "neutral",
    "confidence": 0,
    "positive_factors": [],
    "negative_factors": [],
    "market_impact": "Unable to assess market impact at this time.",
    "key_events": [],
}


def _coin_name(symbol: str) -> str:
    return _COIN_NAMES.get(symbol.upper(), symbol)


def _ai_memory_key(symbol: str) -> str:
    return f"ai_insight:{symbol.upper()}"


def _cache_insight_response(symbol: str, response: dict) -> None:
    cache.set(_ai_memory_key(symbol), response, settings.AI_CACHE_MINUTES * 60)


def _get_memory_insight(symbol: str) -> Optional[dict]:
    cached = cache.get(_ai_memory_key(symbol.upper()))
    return cached if isinstance(cached, dict) else None


async def _get_cached_summary(session: AsyncSession | None, symbol: str) -> Optional[AISummary]:
    if not settings.ENABLE_AI_PERSISTENCE or session is None:
        return None
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(AISummary)
        .where(AISummary.symbol == symbol.upper())
        .where(AISummary.expires_at > now)
        .order_by(desc(AISummary.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_recent_gnews_articles(
    session: AsyncSession | None, symbol: str, limit: int = 15
) -> list[NewsArticle]:
    """Fetch GNews articles from DB as fallback context."""
    if session is None or not settings.ENABLE_NEWS_PERSISTENCE:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    sym = symbol.upper()
    result = await session.execute(
        select(NewsArticle)
        .where(NewsArticle.published_at >= cutoff)
        .where(func.json_contains(NewsArticle.symbols, f'"{sym}"') == 1)
        .order_by(desc(NewsArticle.published_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def _persist_ai_sources(
    session: AsyncSession | None,
    symbol: str,
    sources: list[dict],
) -> None:
    """
    Persist news sources that OpenAI found via web search into news_articles.
    These appear alongside GNews articles in the NewsFeed component.
    """
    if not settings.ENABLE_NEWS_PERSISTENCE or session is None:
        return
    if not sources:
        return

    import hashlib
    from datetime import timezone

    normalised = []
    for src in sources:
        url = src.get("url", "").strip()
        title = src.get("title", "").strip()
        if not url or not title:
            continue

        external_id = hashlib.sha256(url.encode()).hexdigest()[:32]
        normalised.append({
            "external_id": external_id,
            "title": title[:512],
            "description": None,
            "url": url,
            "image_url": None,
            "published_at": datetime.now(timezone.utc),
            "source_name": "OpenAI Web Search",
            "source_domain": None,
            "kind": "news",
            "symbols": [symbol.upper()],
            "votes_positive": 0,
            "votes_negative": 0,
            "panic_score": 0,
        })

    if normalised:
        await upsert_articles(session, normalised)


async def _save_summary(
    session: AsyncSession | None,
    symbol: str,
    ai_result: dict,
    articles_processed: int,
    prompt_tokens: int,
    completion_tokens: int,
    model_used: str,
) -> AISummary | dict:
    cache_minutes = settings.AI_CACHE_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=cache_minutes)
    symbol_up = symbol.upper()

    if not settings.ENABLE_AI_PERSISTENCE or session is None:
        response = {
            "symbol": symbol_up,
            "summary": ai_result.get("summary"),
            "sentiment": ai_result.get("sentiment", "neutral"),
            "confidence": int(ai_result.get("confidence", 0)),
            "positive_factors": ai_result.get("positive_factors", []),
            "negative_factors": ai_result.get("negative_factors", []),
            "market_impact": ai_result.get("market_impact"),
            "key_events": ai_result.get("key_events", []),
            "articles_processed": articles_processed,
            "last_updated": datetime.now(timezone.utc),
            "cache_expires": expires_at,
            "is_stale": False,
        }
        _cache_insight_response(symbol_up, response)
        return response

    existing_result = await session.execute(
        select(AISummary)
        .where(AISummary.symbol == symbol_up)
        .order_by(desc(AISummary.created_at))
        .limit(1)
    )
    summary_obj = existing_result.scalar_one_or_none()

    if summary_obj is None:
        summary_obj = AISummary(symbol=symbol_up)
        session.add(summary_obj)
    else:
        await session.execute(
            delete(AISummary).where(
                AISummary.symbol == symbol_up,
                AISummary.id != summary_obj.id,
            )
        )

    summary_obj.summary = ai_result.get("summary")
    summary_obj.sentiment = ai_result.get("sentiment", "neutral")
    summary_obj.confidence = int(ai_result.get("confidence", 0))
    summary_obj.positive_factors = ai_result.get("positive_factors", [])
    summary_obj.negative_factors = ai_result.get("negative_factors", [])
    summary_obj.market_impact = ai_result.get("market_impact")
    summary_obj.key_events = ai_result.get("key_events", [])
    summary_obj.model_used = model_used
    summary_obj.articles_processed = articles_processed
    summary_obj.prompt_tokens = prompt_tokens
    summary_obj.completion_tokens = completion_tokens
    summary_obj.created_at = datetime.now(timezone.utc)
    summary_obj.expires_at = expires_at
    await session.flush()

    await session.execute(
        delete(MarketInsight).where(MarketInsight.symbol == symbol_up)
    )

    sent_result = await session.execute(
        select(CoinSentiment).where(CoinSentiment.symbol == symbol_up)
    )
    coin_sent = sent_result.scalar_one_or_none()
    if coin_sent:
        coin_sent.sentiment = summary_obj.sentiment
        coin_sent.confidence = summary_obj.confidence
        coin_sent.ai_summary_id = summary_obj.id
        coin_sent.updated_at = datetime.now(timezone.utc)
    else:
        session.add(
            CoinSentiment(
                symbol=symbol_up,
                sentiment=summary_obj.sentiment,
                confidence=summary_obj.confidence,
                ai_summary_id=summary_obj.id,
            )
        )

    for factor in (ai_result.get("positive_factors") or [])[:3]:
        session.add(MarketInsight(
            symbol=symbol_up,
            insight_type="CATALYST",
            content=factor,
            severity="info",
            ai_summary_id=summary_obj.id,
            expires_at=expires_at,
        ))
    for factor in (ai_result.get("negative_factors") or [])[:3]:
        session.add(MarketInsight(
            symbol=symbol_up,
            insight_type="RISK",
            content=factor,
            severity="warning",
            ai_summary_id=summary_obj.id,
            expires_at=expires_at,
        ))

    await session.commit()
    await session.refresh(summary_obj)
    return summary_obj


def _summary_to_response(s: AISummary, is_stale: bool = False) -> dict:
    return {
        "symbol": s.symbol,
        "summary": s.summary,
        "sentiment": s.sentiment,
        "confidence": s.confidence,
        "positive_factors": s.positive_factors or [],
        "negative_factors": s.negative_factors or [],
        "market_impact": s.market_impact,
        "key_events": s.key_events or [],
        "articles_processed": s.articles_processed,
        "last_updated": s.created_at,
        "cache_expires": s.expires_at,
        "is_stale": is_stale,
    }


async def get_insights(session: AsyncSession | None, symbol: str) -> dict:
    """
    Primary entry point for the API route.

    1. Serve from DB cache if still fresh (no OpenAI call).
    2. Otherwise call OpenAI with web_search_preview — OpenAI searches the
       live web for recent news, then generates structured analysis.
    3. Persist sources OpenAI found into news_articles (feeds NewsFeed UI).
    4. Fall back to GNews-article-based analysis if web search fails.
    5. Return last stale record if both AI paths fail.
    """
    symbol = symbol.upper()
    model = settings.AI_MODEL or "gpt-4o-mini"

    mem_cached = _get_memory_insight(symbol)
    if mem_cached:
        logger.debug("Memory cache hit for AI insights: %s", symbol)
        return mem_cached

    # ── 1. Cache hit ──────────────────────────────────────────────────────────
    cached = await _get_cached_summary(session, symbol)
    if cached:
        logger.debug("Cache hit for AI insights: %s", symbol)
        response = _summary_to_response(cached)
        _cache_insight_response(symbol, response)
        return response

    # ── 2. Web-search analysis (primary) ─────────────────────────────────────
    coin = _coin_name(symbol)
    web_prompt = WEB_SEARCH_ANALYSIS_PROMPT.format(
        coin_name=coin, symbol=symbol
    )

    ai_result, prompt_tokens, completion_tokens = await openai_service.web_search_analyze(
        symbol=symbol,
        coin_name=coin,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=web_prompt,
        model=model,
    )

    if ai_result is not None:
        # Persist sources OpenAI found so they appear in the NewsFeed
        sources = ai_result.pop("sources", []) or []
        await _persist_ai_sources(session, symbol, sources)

        saved = await _save_summary(
            session, symbol, ai_result,
            articles_processed=len(sources),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_used=f"{model}+web_search",
        )
        if isinstance(saved, dict):
            return saved
        response = _summary_to_response(saved)
        _cache_insight_response(symbol, response)
        return response

    # ── 3. Fallback: GNews articles from DB ───────────────────────────────────
    logger.warning(
        "%s: web_search_analyze failed, falling back to GNews DB articles", symbol
    )
    articles = await _get_recent_gnews_articles(session, symbol)

    if articles:
        news_block = build_news_block([
            {"title": a.title, "description": a.description} for a in articles
        ])
        fallback_prompt = NEWS_ANALYSIS_PROMPT.format(
            n=len(articles), coin_name=coin, symbol=symbol, news_block=news_block
        )
    else:
        fallback_prompt = NO_NEWS_PROMPT.format(coin_name=coin, symbol=symbol)

    ai_result2, pt2, ct2 = await openai_service.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=fallback_prompt,
        model=model,
    )

    if ai_result2 is not None:
        ai_result2.pop("sources", None)
        saved2 = await _save_summary(
            session, symbol, ai_result2,
            articles_processed=len(articles),
            prompt_tokens=pt2,
            completion_tokens=ct2,
            model_used=model,
        )
        if isinstance(saved2, dict):
            return saved2
        response = _summary_to_response(saved2)
        _cache_insight_response(symbol, response)
        return response

    # ── 4. Both paths failed — return last stale record or hard fallback ──────
    if session is not None and settings.ENABLE_AI_PERSISTENCE:
        stale_result = await session.execute(
            select(AISummary)
            .where(AISummary.symbol == symbol)
            .order_by(desc(AISummary.created_at))
            .limit(1)
        )
        stale = stale_result.scalar_one_or_none()
        if stale:
            return _summary_to_response(stale, is_stale=True)

    return {
        **_FALLBACK_RESPONSE,
        "symbol": symbol,
        "last_updated": None,
        "cache_expires": None,
        "is_stale": True,
    }


async def refresh_insights_for_symbols(
    session: AsyncSession | None, symbols: list[str]
) -> None:
    """
    Batch refresh called by the scheduler.
    Skips symbols whose cache is still fresh to avoid unnecessary API calls.
    """
    for symbol in symbols:
        if settings.ENABLE_AI_PERSISTENCE:
            cached = await _get_cached_summary(session, symbol)
            if cached:
                logger.debug("Scheduler: %s AI cache still fresh, skipping", symbol)
                continue
        elif _get_memory_insight(symbol):
            logger.debug("Scheduler: %s AI memory cache still fresh, skipping", symbol)
            continue
        logger.info("Scheduler: generating AI insights for %s via web search", symbol)
        await get_insights(session, symbol)
