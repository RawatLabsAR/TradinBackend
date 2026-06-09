"""Holder growth and distribution analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import HolderSnapshot


async def compute_holder_growth(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    days: int = 7,
) -> dict:
    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(HolderSnapshot).where(
            HolderSnapshot.chain == chain,
            HolderSnapshot.token_address == token_address,
            HolderSnapshot.snapshot_at >= since,
        ).order_by(HolderSnapshot.snapshot_at.asc())
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return {
            "holder_count": 0,
            "holder_growth_pct": 0.0,
            "top10_pct": 0.0,
            "top50_pct": 0.0,
            "history": [],
        }

    latest = snapshots[-1]
    earliest = snapshots[0]
    growth_pct = 0.0
    if earliest.holder_count > 0:
        growth_pct = round(
            (latest.holder_count - earliest.holder_count) / earliest.holder_count * 100, 2
        )

    return {
        "holder_count": latest.holder_count,
        "holder_growth_pct": growth_pct,
        "top10_pct": latest.top10_pct,
        "top50_pct": latest.top50_pct,
        "history": [
            {
                "holder_count": s.holder_count,
                "snapshot_at": s.snapshot_at.isoformat(),
                "top10_pct": s.top10_pct,
            }
            for s in snapshots
        ],
    }
