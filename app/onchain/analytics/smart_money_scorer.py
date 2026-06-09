"""Smart money wallet scoring system."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.onchain.models.entities import OnchainTrade, SmartMoneyWallet, WalletStat

logger = logging.getLogger(__name__)


def compute_wallet_score(
    *,
    win_rate: float,
    avg_roi_pct: float,
    trade_accuracy: float,
    total_volume_usd: float,
    total_trades: int,
) -> float:
    """Generate smart money score 0-100."""
    if total_trades < 3:
        return 0.0

    volume_score = min(total_volume_usd / 100_000, 1.0) * 20
    win_score = win_rate * 30
    roi_score = min(max(avg_roi_pct, 0) / 50, 1.0) * 30
    accuracy_score = trade_accuracy * 20

    return round(min(win_score + roi_score + accuracy_score + volume_score, 100), 2)


async def score_wallet(
    db: AsyncSession,
    chain: str,
    wallet: str,
) -> Optional[WalletStat]:
    """Compute wallet profitability metrics from trade history."""
    result = await db.execute(
        select(OnchainTrade).where(
            OnchainTrade.chain == chain,
            OnchainTrade.wallet == wallet,
        ).order_by(OnchainTrade.timestamp.asc())
    )
    trades = result.scalars().all()
    if not trades:
        return None

    buys: list[OnchainTrade] = []
    sells: list[OnchainTrade] = []
    for t in trades:
        if t.side == "BUY":
            buys.append(t)
        else:
            sells.append(t)

    total_trades = len(trades)
    wins = 0
    total_roi = 0.0
    roi_count = 0

    # Pair buys with subsequent sells for ROI calculation
    for buy in buys:
        matching_sells = [s for s in sells if s.timestamp > buy.timestamp and s.token_address == buy.token_address]
        if matching_sells:
            sell = matching_sells[0]
            if buy.usd_value > 0:
                roi = (sell.usd_value - buy.usd_value) / buy.usd_value * 100
                total_roi += roi
                roi_count += 1
                if roi > 0:
                    wins += 1

    win_rate = wins / max(roi_count, 1)
    avg_roi = total_roi / max(roi_count, 1)
    trade_accuracy = win_rate
    total_volume = sum(t.usd_value for t in trades)
    score = compute_wallet_score(
        win_rate=win_rate,
        avg_roi_pct=avg_roi,
        trade_accuracy=trade_accuracy,
        total_volume_usd=total_volume,
        total_trades=total_trades,
    )

    stat_result = await db.execute(
        select(WalletStat).where(
            WalletStat.chain == chain,
            WalletStat.wallet == wallet,
        )
    )
    stat = stat_result.scalar_one_or_none()

    values = {
        "chain": chain,
        "wallet": wallet,
        "total_trades": total_trades,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_volume_usd": round(total_volume, 2),
        "realized_pnl_usd": stat.realized_pnl_usd if stat else 0.0,
        "win_rate": round(win_rate, 4),
        "avg_roi_pct": round(avg_roi, 4),
        "trade_accuracy": round(trade_accuracy, 4),
        "smart_money_score": score,
        "is_whale": total_volume >= settings.WHALE_THRESHOLD_USD * 5,
        "is_smart_money": score >= settings.SMART_MONEY_MIN_SCORE,
        "is_sniper": stat.is_sniper if stat else False,
        "first_seen_at": trades[0].timestamp,
        "last_active_at": trades[-1].timestamp,
        "metadata_json": stat.metadata_json if stat and stat.metadata_json else {},
        "updated_at": datetime.utcnow(),
    }

    stmt = pg_insert(WalletStat).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_wallet_stats",
        set_={
            "total_trades": stmt.excluded.total_trades,
            "buy_count": stmt.excluded.buy_count,
            "sell_count": stmt.excluded.sell_count,
            "total_volume_usd": stmt.excluded.total_volume_usd,
            "win_rate": stmt.excluded.win_rate,
            "avg_roi_pct": stmt.excluded.avg_roi_pct,
            "trade_accuracy": stmt.excluded.trade_accuracy,
            "smart_money_score": stmt.excluded.smart_money_score,
            "is_whale": stmt.excluded.is_whale,
            "is_smart_money": stmt.excluded.is_smart_money,
            "first_seen_at": stmt.excluded.first_seen_at,
            "last_active_at": stmt.excluded.last_active_at,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await db.execute(stmt)

    stat = (
        await db.execute(
            select(WalletStat).where(
                WalletStat.chain == chain,
                WalletStat.wallet == wallet,
            )
        )
    ).scalar_one_or_none()

    return stat


async def update_smart_money_registry(
    db: AsyncSession,
    chain: str,
    token_address: str,
    min_score: Optional[float] = None,
) -> list[SmartMoneyWallet]:
    """Update smart money wallet registry for a token."""
    threshold = min_score or settings.SMART_MONEY_MIN_SCORE

    result = await db.execute(
        select(WalletStat).where(
            WalletStat.chain == chain,
            WalletStat.smart_money_score >= threshold,
        ).order_by(WalletStat.smart_money_score.desc()).limit(100)
    )
    stats = result.scalars().all()
    registered: list[SmartMoneyWallet] = []

    for stat in stats:
        existing = await db.execute(
            select(SmartMoneyWallet).where(
                SmartMoneyWallet.chain == chain,
                SmartMoneyWallet.wallet == stat.wallet,
                SmartMoneyWallet.token_address == token_address,
            )
        )
        sm = existing.scalar_one_or_none()
        sm_values = {
            "chain": chain,
            "wallet": stat.wallet,
            "token_address": token_address,
            "score": stat.smart_money_score,
            "win_rate": stat.win_rate,
            "avg_roi_pct": stat.avg_roi_pct,
            "trade_accuracy": stat.trade_accuracy,
            "total_volume_usd": stat.total_volume_usd,
            "last_trade_at": stat.last_active_at,
            "metadata_json": sm.metadata_json if sm and sm.metadata_json else {},
            "updated_at": datetime.utcnow(),
        }
        stmt = pg_insert(SmartMoneyWallet).values(**sm_values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_smart_money",
            set_={
                "score": stmt.excluded.score,
                "win_rate": stmt.excluded.win_rate,
                "avg_roi_pct": stmt.excluded.avg_roi_pct,
                "trade_accuracy": stmt.excluded.trade_accuracy,
                "total_volume_usd": stmt.excluded.total_volume_usd,
                "last_trade_at": stmt.excluded.last_trade_at,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await db.execute(stmt)
        sm = (
            await db.execute(
                select(SmartMoneyWallet).where(
                    SmartMoneyWallet.chain == chain,
                    SmartMoneyWallet.wallet == stat.wallet,
                    SmartMoneyWallet.token_address == token_address,
                )
            )
        ).scalar_one_or_none()
        if sm is None:
            continue
        registered.append(sm)

    return registered
