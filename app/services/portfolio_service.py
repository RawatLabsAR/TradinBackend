"""Portfolio holdings CRUD per user."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_holding import PortfolioHolding


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_holdings(db: AsyncSession, user_id: int) -> list[PortfolioHolding]:
    result = await db.execute(
        select(PortfolioHolding)
        .where(PortfolioHolding.user_id == user_id)
        .order_by(PortfolioHolding.added_at)
    )
    return list(result.scalars().all())


async def add_or_merge(
    db: AsyncSession,
    user_id: int,
    *,
    product_id: str,
    quantity: float,
    avg_cost: float,
) -> PortfolioHolding:
    pid = product_id.strip().upper()
    result = await db.execute(
        select(PortfolioHolding).where(
            PortfolioHolding.user_id == user_id,
            PortfolioHolding.product_id == pid,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        total_qty = existing.quantity + quantity
        existing.avg_cost = (
            existing.avg_cost * existing.quantity + avg_cost * quantity
        ) / total_qty
        existing.quantity = total_qty
        await db.flush()
        return existing

    holding = PortfolioHolding(
        user_id=user_id,
        product_id=pid,
        quantity=quantity,
        avg_cost=avg_cost,
        added_at=_now(),
    )
    db.add(holding)
    await db.flush()
    return holding


async def update_holding(
    db: AsyncSession,
    user_id: int,
    product_id: str,
    *,
    quantity: float | None = None,
    avg_cost: float | None = None,
) -> PortfolioHolding | None:
    pid = product_id.strip().upper()
    result = await db.execute(
        select(PortfolioHolding).where(
            PortfolioHolding.user_id == user_id,
            PortfolioHolding.product_id == pid,
        )
    )
    holding = result.scalar_one_or_none()
    if not holding:
        return None
    if quantity is not None:
        holding.quantity = quantity
    if avg_cost is not None:
        holding.avg_cost = avg_cost
    await db.flush()
    return holding


async def remove_holding(db: AsyncSession, user_id: int, product_id: str) -> bool:
    pid = product_id.strip().upper()
    result = await db.execute(
        delete(PortfolioHolding).where(
            PortfolioHolding.user_id == user_id,
            PortfolioHolding.product_id == pid,
        )
    )
    await db.flush()
    return (result.rowcount or 0) > 0


async def clear_all(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(PortfolioHolding).where(PortfolioHolding.user_id == user_id))
    await db.flush()


async def replace_holdings(
    db: AsyncSession,
    user_id: int,
    holdings: list[dict],
) -> list[PortfolioHolding]:
    await clear_all(db, user_id)
    created: list[PortfolioHolding] = []
    for row in holdings:
        pid = str(row.get("product_id", "")).strip().upper()
        quantity = float(row.get("quantity") or 0)
        avg_cost = float(row.get("avg_cost") or 0)
        if not pid or quantity <= 0:
            continue
        added_at = _now()
        raw_added = row.get("added_at")
        if raw_added:
            try:
                added_at = datetime.fromisoformat(str(raw_added).replace("Z", "+00:00"))
            except ValueError:
                pass
        holding = PortfolioHolding(
            user_id=user_id,
            product_id=pid,
            quantity=quantity,
            avg_cost=avg_cost,
            added_at=added_at,
        )
        db.add(holding)
        created.append(holding)
    await db.flush()
    return created
