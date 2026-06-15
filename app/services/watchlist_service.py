"""Watchlist CRUD per user."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.watchlist_item import WatchlistItem


async def list_product_ids(db: AsyncSession, user_id: int) -> list[str]:
    result = await db.execute(
        select(WatchlistItem.product_id)
        .where(WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.sort_order, WatchlistItem.created_at)
    )
    return [row[0] for row in result.all()]


async def replace_items(db: AsyncSession, user_id: int, product_ids: list[str]) -> list[str]:
    normalized = []
    seen: set[str] = set()
    for raw in product_ids:
        pid = raw.strip().upper()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        normalized.append(pid)

    await db.execute(delete(WatchlistItem).where(WatchlistItem.user_id == user_id))
    for idx, product_id in enumerate(normalized):
        db.add(
            WatchlistItem(
                user_id=user_id,
                product_id=product_id,
                sort_order=idx,
            )
        )
    await db.flush()
    return normalized


async def add_item(db: AsyncSession, user_id: int, product_id: str) -> list[str]:
    pid = product_id.strip().upper()
    if not pid:
        return await list_product_ids(db, user_id)

    result = await db.execute(
        select(WatchlistItem.product_id).where(
            WatchlistItem.user_id == user_id,
            WatchlistItem.product_id == pid,
        )
    )
    if result.scalar_one_or_none():
        return await list_product_ids(db, user_id)

    count_result = await db.execute(
        select(func.count()).select_from(WatchlistItem).where(WatchlistItem.user_id == user_id)
    )
    sort_order = int(count_result.scalar_one() or 0)
    db.add(WatchlistItem(user_id=user_id, product_id=pid, sort_order=sort_order))
    await db.flush()
    return await list_product_ids(db, user_id)


async def remove_item(db: AsyncSession, user_id: int, product_id: str) -> list[str]:
    pid = product_id.strip().upper()
    await db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == user_id,
            WatchlistItem.product_id == pid,
        )
    )
    await db.flush()
    return await list_product_ids(db, user_id)
