"""Load/save discovery snapshots in PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.types import DiscoveryResult
from app.discovery.utils import chain_key, discovery_result_from_payload, filter_tokens_by_chain
from app.models.discovery_snapshot import DiscoverySnapshot


async def load_snapshot(
    db: AsyncSession,
    category: str,
    chain: Optional[str] = None,
) -> Optional[DiscoveryResult]:
    chain_key_val = chain_key(chain)
    result = await db.execute(
        select(DiscoverySnapshot).where(
            DiscoverySnapshot.category == category,
            DiscoverySnapshot.chain == chain_key_val,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        if chain_key_val:
            result = await db.execute(
                select(DiscoverySnapshot).where(
                    DiscoverySnapshot.category == category,
                    DiscoverySnapshot.chain == "",
                )
            )
            row = result.scalar_one_or_none()
        if not row:
            return None

    payload = dict(row.payload)
    payload.setdefault("category", category)
    payload.setdefault("sources_used", row.sources_used or [])
    payload.setdefault("scanned_at", row.scanned_at.isoformat() if row.scanned_at else "")

    discovery = discovery_result_from_payload(payload, category=category, cached=True)
    if chain_key_val:
        discovery.items = filter_tokens_by_chain(discovery.items, chain)
    return discovery


async def save_snapshot(
    db: AsyncSession,
    result: DiscoveryResult,
    chain: Optional[str] = None,
) -> None:
    chain_key_val = chain_key(chain)
    payload = result.to_dict()
    scanned_at = datetime.now(timezone.utc)
    if result.scanned_at:
        try:
            scanned_at = datetime.fromisoformat(result.scanned_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    stmt = insert(DiscoverySnapshot).values(
        category=result.category,
        chain=chain_key_val,
        payload=payload,
        sources_used=result.sources_used,
        scanned_at=scanned_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_discovery_category_chain",
        set_={
            "payload": payload,
            "sources_used": result.sources_used,
            "scanned_at": scanned_at,
        },
    )
    await db.execute(stmt)


async def delete_stale_snapshots(db: AsyncSession, cutoff: datetime) -> int:
    result = await db.execute(
        delete(DiscoverySnapshot).where(DiscoverySnapshot.scanned_at < cutoff)
    )
    return result.rowcount or 0
