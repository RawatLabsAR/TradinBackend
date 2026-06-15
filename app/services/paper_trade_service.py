"""Paper trade PnL and listing helpers."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper_trade import PaperTrade


def compute_closed_pnl(
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    fee_pct: float,
) -> tuple[float, float]:
    """Return (net_pnl, pnl_pct) after round-trip fees."""
    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    fees = entry_notional * fee_pct + exit_notional * fee_pct
    if side == "long":
        gross = (exit_price - entry_price) * quantity
        pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        gross = (entry_price - exit_price) * quantity
        pct = ((entry_price - exit_price) / entry_price) * 100
    return gross - fees, pct


def compute_unrealized_pnl(
    side: str,
    entry_price: float,
    current_price: float,
    quantity: float,
    fee_pct: float,
) -> tuple[float, float]:
    """Estimate net unrealized PnL if closed at current_price."""
    return compute_closed_pnl(side, entry_price, current_price, quantity, fee_pct)


async def list_trades(
    db: AsyncSession,
    user_id: int,
    status: str = "all",
) -> list[PaperTrade]:
    q = select(PaperTrade).where(PaperTrade.user_id == user_id)
    if status == "open":
        q = q.where(PaperTrade.closed_at.is_(None))
    elif status == "closed":
        q = q.where(PaperTrade.closed_at.isnot(None))
    q = q.order_by(desc(PaperTrade.opened_at))
    result = await db.execute(q)
    return list(result.scalars().all())


def build_stats(trades: list[PaperTrade]) -> dict:
    closed = [t for t in trades if t.closed_at and t.pnl is not None]
    wins = sum(1 for t in closed if t.pnl > 0)
    losses = sum(1 for t in closed if t.pnl <= 0)
    total_pnl = sum(t.pnl for t in closed)
    win_rate = (wins / len(closed) * 100) if closed else 0.0
    open_count = sum(1 for t in trades if not t.closed_at)
    return {
        "open_count": open_count,
        "closed_count": len(closed),
        "total_realized_pnl": round(total_pnl, 2),
        "win_count": wins,
        "loss_count": losses,
        "win_rate_pct": round(win_rate, 1),
    }
