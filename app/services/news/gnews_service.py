"""
GNews API fallback — free tier supports 100 requests/day.

Endpoint: GET https://gnews.io/api/v4/search
Docs: https://gnews.io/docs/v4

Used when CryptoPanic is unavailable or not configured.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://gnews.io/api/v4/search"

# Map crypto symbols to good search queries
_SYMBOL_TO_QUERY: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "XRP": "XRP Ripple",
    "DOGE": "Dogecoin",
    "ADA": "Cardano",
    "AVAX": "Avalanche crypto",
    "DOT": "Polkadot crypto",
    "LINK": "Chainlink crypto",
    "MATIC": "Polygon MATIC",
}


def _query_for(symbol: str) -> str:
    return _SYMBOL_TO_QUERY.get(symbol.upper(), f"{symbol} cryptocurrency")


async def fetch_news(symbol: str, max_results: int = 10) -> list[dict]:
    """
    Fetch news for a single symbol from GNews.
    Returns normalised list compatible with news_normalizer expectations.
    """
    if not settings.GNEWS_API_KEY:
        return []

    params = {
        "q": _query_for(symbol),
        "lang": "en",
        "country": "any",
        "max": min(max_results, 10),
        "apikey": settings.GNEWS_API_KEY,
        "expand": "content",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_BASE, params=params) as resp:
                if resp.status != 200:
                    logger.warning("GNews HTTP %d for %s", resp.status, symbol)
                    return []
                data = await resp.json()
                return _normalise(data.get("articles", []), symbol)
    except Exception as exc:
        logger.error("GNews request failed for %s: %s", symbol, exc)
        return []


def _normalise(articles: list[dict], symbol: str) -> list[dict]:
    """Convert GNews article format to the internal normalised format."""
    result = []
    for a in articles:
        url = a.get("url", "")
        if not url:
            continue
        external_id = hashlib.sha256(url.encode()).hexdigest()[:32]
        pub = a.get("publishedAt", "")
        try:
            published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.now(timezone.utc)

        result.append({
            "external_id": external_id,
            "title": a.get("title", "")[:512],
            "description": (a.get("description") or "")[:1000],
            "url": url,
            "image_url": a.get("image"),
            "published_at": published_at,
            "source_name": a.get("source", {}).get("name"),
            "source_domain": a.get("source", {}).get("url"),
            "kind": "news",
            "symbols": [symbol],
            "votes_positive": 0,
            "votes_negative": 0,
            "panic_score": 0,
        })
    return result
