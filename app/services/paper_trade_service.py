"""Paper trade PnL, listing, mark-to-market, and journal analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import desc, select
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
        q = q.where(PaperTrade.closed_at.is_(None), PaperTrade.is_pending == 0)
    elif status == "closed":
        q = q.where(PaperTrade.closed_at.isnot(None))
    elif status == "pending":
        q = q.where(PaperTrade.closed_at.is_(None), PaperTrade.is_pending == 1)
    q = q.order_by(desc(PaperTrade.opened_at))
    result = await db.execute(q)
    return list(result.scalars().all())


def build_stats(trades: list[PaperTrade]) -> dict:
    closed = [t for t in trades if t.closed_at and t.pnl is not None]
    wins = sum(1 for t in closed if t.pnl > 0)
    losses = sum(1 for t in closed if t.pnl <= 0)
    total_pnl = sum(t.pnl for t in closed)
    win_rate = (wins / len(closed) * 100) if closed else 0.0
    open_count = sum(1 for t in trades if not t.closed_at and not t.is_pending)
    pending_count = sum(1 for t in trades if not t.closed_at and t.is_pending)
    return {
        "open_count": open_count,
        "pending_count": pending_count,
        "closed_count": len(closed),
        "total_realized_pnl": round(total_pnl, 2),
        "win_count": wins,
        "loss_count": losses,
        "win_rate_pct": round(win_rate, 1),
    }


def trade_to_dict(trade: PaperTrade) -> dict:
    return {
        "id": trade.id,
        "product_id": trade.product_id,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "quantity": trade.quantity,
        "fee_pct": trade.fee_pct,
        "pnl": trade.pnl,
        "pnl_pct": trade.pnl_pct,
        "notes": trade.notes,
        "source": trade.source,
        "order_type": getattr(trade, "order_type", None) or "market",
        "limit_price": getattr(trade, "limit_price", None),
        "stop_loss": getattr(trade, "stop_loss", None),
        "take_profit": getattr(trade, "take_profit", None),
        "script_id": getattr(trade, "script_id", None),
        "is_pending": bool(getattr(trade, "is_pending", 0)),
        "opened_at": trade.opened_at,
        "closed_at": trade.closed_at,
    }


def build_journal_analytics(
    trades: list[PaperTrade],
    starting_balance: float = 10_000.0,
) -> dict:
    closed = sorted(
        [t for t in trades if t.closed_at and t.pnl is not None],
        key=lambda t: t.closed_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    cumulative = 0.0
    equity = starting_balance
    peak = starting_balance
    max_dd = 0.0
    curve: list[dict] = []
    by_symbol: dict[str, float] = defaultdict(float)
    by_source: dict[str, float] = defaultdict(float)

    for t in closed:
        cumulative += t.pnl or 0
        equity += t.pnl or 0
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
        by_symbol[t.product_id] += t.pnl or 0
        by_source[t.source or "manual"] += t.pnl or 0
        curve.append({
            "date": (t.closed_at or datetime.now(timezone.utc)).date().isoformat(),
            "cumulative_pnl": round(cumulative, 2),
            "equity": round(equity, 2),
        })

    stats = build_stats(trades)
    return {
        "equity_curve": curve,
        "by_symbol": dict(by_symbol),
        "by_source": dict(by_source),
        "max_drawdown_pct": round(max_dd, 2),
        "total_realized_pnl": stats["total_realized_pnl"],
        "win_rate_pct": stats["win_rate_pct"],
        "trade_count": stats["closed_count"],
    }


async def list_open_for_product(
    db: AsyncSession,
    product_id: str,
) -> list[PaperTrade]:
    q = (
        select(PaperTrade)
        .where(
            PaperTrade.product_id == product_id.upper(),
            PaperTrade.closed_at.is_(None),
        )
    )
    result = await db.execute(q)
    return list(result.scalars().all())
