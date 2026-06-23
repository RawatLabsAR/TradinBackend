"""
Backtesting engine.

Runs a script against historical candle data and produces comprehensive
performance statistics: P&L, win rate, Sharpe ratio, max drawdown, and
per-trade history.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.pinescript.executor.strategy_executor import execute_script, ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    label: str
    pnl_pct: float
    entry_timestamp: str = ""
    exit_timestamp: str = ""


@dataclass
class BacktestResult:
    success: bool
    strategy_name: str = ""
    symbol: str = ""
    timeframe: str = ""

    # Capital
    initial_capital: float = 10_000.0
    final_capital: float = 0.0
    net_profit_pct: float = 0.0
    gross_profit_pct: float = 0.0
    gross_loss_pct: float = 0.0

    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Risk metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Per-trade history
    trades: list[dict] = field(default_factory=list)

    # Signals and overlays for chart rendering
    signals: list[dict] = field(default_factory=list)
    indicator_overlays: dict[str, list[float]] = field(default_factory=dict)
    equity_curve: list[float] = field(default_factory=list)

    bars_tested: int = 0
    execution_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


async def run_backtest(
    source: str,
    candles: list[dict],
    symbol: str = "UNKNOWN",
    timeframe: str = "1D",
    initial_capital: float = 10_000.0,
    fee_pct: float = 0.001,
) -> BacktestResult:
    """
    Execute a full backtest.

    Returns a BacktestResult with all performance statistics.
    """
    import time
    t0 = time.monotonic()

    exec_result: ExecutionResult = await execute_script(
        source=source,
        candles=candles,
        symbol=symbol,
        initial_capital=initial_capital,
        fee_pct=fee_pct,
    )

    if not exec_result.success:
        return BacktestResult(
            success=False,
            symbol=symbol,
            errors=exec_result.errors,
        )

    # Build trade records from signals
    trades = _build_trades(exec_result.signals, candles, fee_pct=fee_pct)

    # Compute equity curve
    equity_curve = _compute_equity_curve(trades, initial_capital, len(candles))

    # Compute statistics
    stats = _compute_statistics(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=initial_capital,
        fee_pct=fee_pct,
    )

    elapsed = (time.monotonic() - t0) * 1000

    return BacktestResult(
        success=True,
        strategy_name=exec_result.strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=initial_capital,
        final_capital=stats["final_capital"],
        net_profit_pct=stats["net_profit_pct"],
        gross_profit_pct=stats["gross_profit_pct"],
        gross_loss_pct=stats["gross_loss_pct"],
        total_trades=stats["total_trades"],
        winning_trades=stats["winning_trades"],
        losing_trades=stats["losing_trades"],
        win_rate_pct=stats["win_rate_pct"],
        avg_win_pct=stats["avg_win_pct"],
        avg_loss_pct=stats["avg_loss_pct"],
        profit_factor=stats["profit_factor"],
        max_consecutive_wins=stats["max_consecutive_wins"],
        max_consecutive_losses=stats["max_consecutive_losses"],
        max_drawdown_pct=stats["max_drawdown_pct"],
        sharpe_ratio=stats["sharpe_ratio"],
        sortino_ratio=stats["sortino_ratio"],
        calmar_ratio=stats["calmar_ratio"],
        trades=[t.__dict__ for t in trades],
        signals=exec_result.signals,
        indicator_overlays=exec_result.indicator_overlays,
        equity_curve=equity_curve,
        bars_tested=exec_result.bars_executed,
        execution_ms=round(elapsed, 2),
    )


# ─────────────────────────── Internal helpers ─────────────────────────────────

def _build_trades(
    signals: list[dict],
    candles: list[dict],
    fee_pct: float = 0.001,
) -> list[TradeRecord]:
    """Pair entry/exit signals into TradeRecord objects."""
    timestamps = [c.get("start", "") for c in candles]
    trades: list[TradeRecord] = []
    open_entries: dict[str, dict] = {}  # label → entry signal

    for sig in signals:
        stype = sig.get("signal_type")
        label = sig.get("label", "")

        if stype == "entry":
            open_entries[label] = sig
        elif stype in ("exit", "close"):
            # Match against any open entry
            entry = None
            if label in open_entries:
                entry = open_entries.pop(label)
            elif open_entries:
                # Close the first open entry
                entry_label = next(iter(open_entries))
                entry = open_entries.pop(entry_label)

            if entry:
                bi_in = entry.get("bar_index", 0)
                bi_out = sig.get("bar_index", 0)
                ts_in = timestamps[bi_in] if bi_in < len(timestamps) else ""
                ts_out = timestamps[bi_out] if bi_out < len(timestamps) else ""
                p_in = entry.get("price", 0)
                p_out = sig.get("price", 0)
                is_long = entry.get("direction") == "buy"
                raw_pnl = (p_out - p_in) / p_in if is_long else (p_in - p_out) / p_in
                net = raw_pnl - 2 * fee_pct
                trades.append(TradeRecord(
                    entry_bar=bi_in,
                    exit_bar=bi_out,
                    entry_price=p_in,
                    exit_price=p_out,
                    label=entry.get("label", ""),
                    pnl_pct=round(net * 100, 4),
                    entry_timestamp=ts_in,
                    exit_timestamp=ts_out,
                ))

    return trades


def _compute_equity_curve(
    trades: list[TradeRecord],
    initial_capital: float,
    num_bars: int,
) -> list[float]:
    """Bar-by-bar equity curve."""
    equity = [initial_capital] * num_bars
    capital = initial_capital
    for trade in sorted(trades, key=lambda t: t.exit_bar):
        capital *= 1.0 + trade.pnl_pct / 100.0
        for i in range(trade.exit_bar, num_bars):
            equity[i] = capital
    return [round(v, 2) for v in equity]


def _compute_statistics(
    trades: list[TradeRecord],
    equity_curve: list[float],
    initial_capital: float,
    fee_pct: float,
) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "final_capital": initial_capital,
            "net_profit_pct": 0.0,
            "gross_profit_pct": 0.0,
            "gross_loss_pct": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
        }

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    final_capital = equity_curve[-1] if equity_curve else initial_capital
    net_profit_pct = round((final_capital - initial_capital) / initial_capital * 100, 4)

    gross_profit_pct = round(sum(wins), 4)
    gross_loss_pct = round(abs(sum(losses)), 4)
    profit_factor = (
        round(gross_profit_pct / gross_loss_pct, 4) if gross_loss_pct > 0 else float("inf")
    )

    # Consecutive runs
    max_wins, max_losses, cur_w, cur_l = 0, 0, 0, 0
    for p in pnls:
        if p > 0:
            cur_w += 1
            cur_l = 0
        else:
            cur_l += 1
            cur_w = 0
        max_wins = max(max_wins, cur_w)
        max_losses = max(max_losses, cur_l)

    # Max drawdown
    max_drawdown_pct = _max_drawdown(equity_curve)

    # Sharpe ratio (annualised, assuming 252 trading days)
    returns = np.array(pnls) / 100.0
    sharpe = 0.0
    sortino = 0.0
    if len(returns) > 1:
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        if std_r > 0:
            sharpe = round(mean_r / std_r * math.sqrt(252), 4)
        downside = np.std([r for r in returns if r < 0], ddof=1)
        if downside > 0:
            sortino = round(mean_r / downside * math.sqrt(252), 4)

    calmar = 0.0
    if max_drawdown_pct > 0:
        calmar = round(net_profit_pct / max_drawdown_pct, 4)

    return {
        "final_capital": round(final_capital, 2),
        "net_profit_pct": net_profit_pct,
        "gross_profit_pct": gross_profit_pct,
        "gross_loss_pct": gross_loss_pct,
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 2) if n else 0.0,
        "avg_win_pct": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "profit_factor": profit_factor,
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
    }


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(max_dd, 4)
