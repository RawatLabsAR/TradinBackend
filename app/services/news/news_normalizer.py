"""
Normalise raw CryptoPanic API responses into the internal article format
and persist them to the news_articles table (deduplicated via external_id).
"""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.news_article import NewsArticle

logger = logging.getLogger(__name__)


def normalise_cryptopanic(raw_items: list[dict]) -> list[dict]:
    """
    Transform CryptoPanic result objects into our internal dict format.
    Only headlines + short descriptions are kept — we deliberately drop
    full article content to keep DB size and AI token cost low.
    """
    articles = []
    for item in raw_items:
        title = item.get("title", "").strip()
        if not title:
            continue

        url = item.get("original_url") or item.get("url", "")
        if not url:
            continue

        # Stable external ID: CryptoPanic's own id cast to string
        cp_id = item.get("id")
        external_id = str(cp_id) if cp_id else hashlib.sha256(url.encode()).hexdigest()[:32]

        pub_str = item.get("published_at") or item.get("created_at", "")
        try:
            published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.now(timezone.utc)

        # Extract coin symbols from instruments
        instruments = item.get("instruments") or item.get("currencies", [])
        symbols = [inst.get("code", "").upper() for inst in instruments if inst.get("code")]

        source = item.get("source") or {}
        votes = item.get("votes") or {}

        description = item.get("description") or ""
        articles.append({
            "external_id": external_id,
            "title": title[:512],
            "description": description[:1000],
            "url": url,
            "image_url": item.get("image"),
            "published_at": published_at,
            "source_name": source.get("title"),
            "source_domain": source.get("domain"),
            "kind": item.get("kind", "news"),
            "symbols": symbols,
            "votes_positive": votes.get("positive", 0),
            "votes_negative": votes.get("negative", 0),
            "panic_score": item.get("panic_score", 0),
        })

    return articles


async def upsert_articles(
    session: AsyncSession,
    articles: list[dict],
) -> tuple[int, int]:
    """
    Insert new articles; skip existing ones (deduplicate by external_id).
    Returns (inserted_count, skipped_count).
    """
    if not articles:
        return 0, 0

    external_ids = [a["external_id"] for a in articles]

    # Fetch already-stored IDs in one query
    result = await session.execute(
        select(NewsArticle.external_id).where(
            NewsArticle.external_id.in_(external_ids)
        )
    )
    existing_ids = {row[0] for row in result.fetchall()}

    inserted = 0
    skipped = 0
    for art in articles:
        if art["external_id"] in existing_ids:
            skipped += 1
            continue
        session.add(NewsArticle(**art))
        inserted += 1

    if inserted:
        await session.commit()

    logger.info("News upsert: +%d new, %d skipped", inserted, skipped)
    return inserted, skipped
