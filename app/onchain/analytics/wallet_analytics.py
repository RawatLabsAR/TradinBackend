"""Early buyer and sniper wallet detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.models.entities import OnchainTrade, WalletStat


async def detect_early_buyers(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    window_hours: int = 24,
) -> list[str]:
    """Wallets that bought within the first N hours of tracked data."""
    first_trade_q = await db.execute(
        select(OnchainTrade.timestamp).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.side == "BUY",
        ).order_by(OnchainTrade.timestamp.asc()).limit(1)
    )
    first_ts = first_trade_q.scalar_one_or_none()
    if not first_ts:
        return []

    cutoff = first_ts + timedelta(hours=window_hours)
    result = await db.execute(
        select(OnchainTrade.wallet).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.side == "BUY",
            OnchainTrade.timestamp <= cutoff,
        ).distinct()
    )
    return [row[0] for row in result.all()]


async def detect_sniper_wallets(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    max_blocks_after_launch: int = 3,
) -> list[str]:
    """
    Detect sniper wallets: bought in the first few blocks with high USD value.
    Uses block_number proximity when available.
    """
    result = await db.execute(
        select(OnchainTrade).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.side == "BUY",
            OnchainTrade.block_number.isnot(None),
        ).order_by(OnchainTrade.block_number.asc())
    )
    trades = result.scalars().all()
    if not trades:
        return []

    min_block = trades[0].block_number or 0
    snipers = {
        t.wallet for t in trades
        if t.block_number is not None
        and (t.block_number - min_block) <= max_blocks_after_launch
        and t.usd_value >= 1000
    }

    for wallet in snipers:
        stat_q = await db.execute(
            select(WalletStat).where(
                WalletStat.chain == chain,
                WalletStat.wallet == wallet,
            )
        )
        stat = stat_q.scalar_one_or_none()
        if stat:
            stat.is_sniper = True
        else:
            db.add(WalletStat(chain=chain, wallet=wallet, is_sniper=True))

    return list(snipers)
