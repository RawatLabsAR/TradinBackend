"""Abstract base collector with checkpoint support."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import SyncCheckpoint
from app.onchain.types import (
    NormalizedHolderSnapshot,
    NormalizedLiquidityEvent,
    NormalizedTrade,
)

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    source_name: str = "base"

    @abstractmethod
    async def fetch_trades(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedTrade], str]:
        ...

    async def fetch_wallet_activity(
        self,
        chain: str,
        wallet: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedTrade], str]:
        return [], ""

    async def fetch_liquidity_events(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedLiquidityEvent], str]:
        return [], ""

    async def fetch_holder_snapshot(
        self,
        chain: str,
        token_address: str,
    ) -> Optional[NormalizedHolderSnapshot]:
        return None

    async def get_checkpoint(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        sync_type: str,
    ) -> Optional[SyncCheckpoint]:
        result = await db.execute(
            select(SyncCheckpoint).where(
                SyncCheckpoint.chain == chain,
                SyncCheckpoint.token_address == token_address,
                SyncCheckpoint.source == self.source_name,
                SyncCheckpoint.sync_type == sync_type,
            )
        )
        return result.scalar_one_or_none()

    async def update_checkpoint(
        self,
        db: AsyncSession,
        chain: str,
        token_address: str,
        sync_type: str,
        *,
        last_timestamp: Optional[datetime] = None,
        last_block: Optional[int] = None,
        last_cursor: str = "",
        records_synced: int = 0,
        status: str = "idle",
        error_message: str = "",
    ) -> SyncCheckpoint:
        cp = await self.get_checkpoint(db, chain, token_address, sync_type)
        if cp is None:
            cp = SyncCheckpoint(
                chain=chain,
                token_address=token_address,
                source=self.source_name,
                sync_type=sync_type,
            )
            try:
                async with db.begin_nested():
                    db.add(cp)
                    await db.flush()
            except IntegrityError:
                cp = await self.get_checkpoint(db, chain, token_address, sync_type)
                if cp is None:
                    raise

        if last_timestamp is not None:
            cp.last_timestamp = last_timestamp
        if last_block is not None:
            cp.last_block = last_block
        if last_cursor:
            cp.last_cursor = last_cursor
        cp.records_synced = (cp.records_synced or 0) + records_synced
        cp.status = status
        cp.error_message = error_message
        cp.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return cp

    @staticmethod
    def _parse_ts(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.utcfromtimestamp(ts)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        return datetime.utcnow()
