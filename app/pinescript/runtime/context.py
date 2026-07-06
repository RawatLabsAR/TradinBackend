"""
Execution context passed to every AST node evaluation.

Manages:
  - per-bar scalar values (close, open, …)
  - series (pre-computed numpy arrays)
  - user variables
  - signals generated for the current bar
  - position state
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────── Signal model ────────────────────────────────────

@dataclass
class Signal:
    bar_index: int
    timestamp: str          # ISO-8601
    signal_type: str        # "entry" | "exit" | "close"
    label: str              # user-supplied label e.g. "LONG"
    price: float
    direction: str          # "buy" | "sell" | "neutral"
    metadata: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────── Series wrapper ──────────────────────────────────

class SeriesValue:
    """
    Wraps a numpy array so the runtime can distinguish a full time-series
    from a plain scalar.  Accessing `.scalar(idx)` returns the value for a
    specific bar.
    """
    __slots__ = ("_data",)

    def __init__(self, data: np.ndarray) -> None:
        self._data = data

    def scalar(self, idx: int) -> float:
        if idx < 0 or idx >= len(self._data):
            return math.nan
        v = self._data[idx]
        return float(v) if not np.isnan(v) else math.nan

    def array(self) -> np.ndarray:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"SeriesValue(len={len(self._data)})"


# ─────────────────────────── Strategy state ──────────────────────────────────

class StrategyState:
    """Tracks open/closed positions and pending signals for the current bar."""

    def __init__(self, initial_capital: float = 10_000.0, fee_pct: float = 0):
        self.initial_capital = initial_capital
        self.fee_pct = fee_pct
        self.capital = initial_capital
        self.position: str | None = None     # current open label or None
        self.entry_price: float = 0.0
        self.entry_bar: int = 0
        self.stop_loss: float | None = None
        self.take_profit: float | None = None
        self._bar_signals: list[Signal] = []
        self.all_signals: list[Signal] = []
        self.trades: list[dict] = []

    # ── per-bar signal management ─────────────────────────────────────────

    def emit_entry(self, label: str, price: float, bar_idx: int,
                   timestamp: str) -> None:
        if self.position is not None:
            return  # already in a trade
        self.position = label
        self.entry_price = price
        self.entry_bar = bar_idx
        sig = Signal(
            bar_index=bar_idx,
            timestamp=timestamp,
            signal_type="entry",
            label=label,
            price=price,
            direction="buy" if "SHORT" not in label.upper() else "sell",
        )
        self._bar_signals.append(sig)
        self.all_signals.append(sig)

    def emit_exit(self, label: str, price: float, bar_idx: int,
                  timestamp: str) -> None:
        if self.position is None:
            return
        entry_p = self.entry_price
        is_long = "SHORT" not in self.position.upper()
        pnl = (price - entry_p) / entry_p if is_long else (entry_p - price) / entry_p
        fee = self.fee_pct * 2  # in + out
        net_pnl = pnl - fee
        self.trades.append({
            "entry_bar": self.entry_bar,
            "exit_bar": bar_idx,
            "entry_price": entry_p,
            "exit_price": price,
            "label": self.position,
            "pnl_pct": round(net_pnl * 100, 4),
        })
        self.capital *= 1.0 + net_pnl
        self.position = None
        self.stop_loss = None
        self.take_profit = None

        sig = Signal(
            bar_index=bar_idx,
            timestamp=timestamp,
            signal_type="exit",
            label=label,
            price=price,
            direction="sell" if is_long else "buy",
            metadata={"pnl_pct": round(net_pnl * 100, 4)},
        )
        self._bar_signals.append(sig)
        self.all_signals.append(sig)

    def emit_close(self, price: float, bar_idx: int, timestamp: str) -> None:
        if self.position is not None:
            self.emit_exit(f"close_{self.position}", price, bar_idx, timestamp)

    def set_bracket(self, stop: float | None = None, limit: float | None = None) -> None:
        if stop is not None and stop > 0:
            self.stop_loss = stop
        if limit is not None and limit > 0:
            self.take_profit = limit

    def check_bar_exits(
        self,
        high: float,
        low: float,
        close: float,
        bar_idx: int,
        timestamp: str,
    ) -> None:
        """Evaluate stop-loss / take-profit against bar range."""
        if self.position is None:
            return
        is_long = "SHORT" not in self.position.upper()
        exit_price = None
        if is_long:
            if self.stop_loss is not None and low <= self.stop_loss:
                exit_price = self.stop_loss
            elif self.take_profit is not None and high >= self.take_profit:
                exit_price = self.take_profit
        else:
            if self.stop_loss is not None and high >= self.stop_loss:
                exit_price = self.stop_loss
            elif self.take_profit is not None and low <= self.take_profit:
                exit_price = self.take_profit
        if exit_price is not None:
            self.emit_exit("bracket", exit_price, bar_idx, timestamp)
            self.stop_loss = None
            self.take_profit = None

    def flush_signals(self) -> list[Signal]:
        sigs = self._bar_signals
        self._bar_signals = []
        return sigs


# ─────────────────────────── Execution context ───────────────────────────────

class ExecutionContext:
    """
    Holds all runtime state for a single execution pass.

    Built once per script run; updated on each bar via `set_bar()`.
    """

    BUILTIN_SERIES = frozenset({
        "close", "open", "high", "low", "volume",
        "hl2", "hlc3", "ohlc4",
    })
    BUILTIN_SCALARS = frozenset({"bar_index", "timenow"})

    def __init__(
        self,
        candle_data: dict[str, np.ndarray],
        timestamps: list[str],
        strategy_name: str = "Script",
        initial_capital: float = 10_000.0,
        fee_pct: float = 0,
    ) -> None:
        # Candle series (full history numpy arrays)
        self._series: dict[str, np.ndarray] = candle_data
        self._timestamps = timestamps

        # User-defined variables: name → (SeriesValue | scalar)
        self._vars: dict[str, Any] = {}
        self._var_initialized: set[str] = set()

        # Named plot overlays from plot() calls
        self.plot_overlays: dict[str, SeriesValue] = {}

        # Indicator cache: indicator_key → SeriesValue
        self._indicator_cache: dict[str, SeriesValue] = {}

        # Current bar pointer
        self.bar_index: int = 0
        self.total_bars: int = len(timestamps)

        self.strategy_name = strategy_name
        self.strategy = StrategyState(
            initial_capital=initial_capital,
            fee_pct=fee_pct,
        )

        # Derived OHLC series (TradingView built-ins)
        h = candle_data["high"]
        l = candle_data["low"]
        c = candle_data["close"]
        o = candle_data["open"]
        self._series["hl2"] = (h + l) / 2.0
        self._series["hlc3"] = (h + l + c) / 3.0
        self._series["ohlc4"] = (o + h + l + c) / 4.0

    def set_bar(self, idx: int) -> None:
        self.bar_index = idx

    # ── Series access ─────────────────────────────────────────────────────

    def get_series(self, name: str) -> np.ndarray | None:
        return self._series.get(name)

    def current_value(self, name: str) -> float:
        """Scalar value of a built-in series at the current bar."""
        arr = self._series.get(name)
        if arr is None or self.bar_index >= len(arr):
            return math.nan
        return float(arr[self.bar_index])

    @property
    def current_close(self) -> float:
        return self.current_value("close")

    @property
    def current_timestamp(self) -> str:
        if self.bar_index < len(self._timestamps):
            return self._timestamps[self.bar_index]
        return ""

    # ── Variable management ───────────────────────────────────────────────

    def set_var(self, name: str, value: Any, *, is_var: bool = False) -> None:
        if is_var and name in self._var_initialized:
            return
        self._vars[name] = value
        if is_var:
            self._var_initialized.add(name)

    def reassign_var(self, name: str, value: Any) -> None:
        self._vars[name] = value

    def has_var(self, name: str) -> bool:
        return name in self._vars

    def get_var(self, name: str) -> Any:
        # Check user vars first
        if name in self._vars:
            val = self._vars[name]
            # Resolve series to current scalar
            if isinstance(val, SeriesValue):
                return val.scalar(self.bar_index)
            return val

        # Built-in scalar identifiers
        if name == "bar_index":
            return self.bar_index
        if name == "timenow":
            return self.bar_index

        # Built-in OHLCV series → current bar scalar
        if name in self.BUILTIN_SERIES:
            return self.current_value(name)

        # On-chain metrics (injected as SeriesValue)
        ONCHAIN_VARS = {
            "whale_buy_volume", "whale_sell_volume", "buy_volume_usd",
            "sell_volume_usd", "net_flow_usd", "smart_money_score",
            "holder_count", "holder_growth_pct", "liquidity_usd", "unique_wallets",
        }
        if name in ONCHAIN_VARS and name in self._vars:
            val = self._vars[name]
            if isinstance(val, SeriesValue):
                return val.scalar(self.bar_index)
            return val

        raise NameError(f"Undefined variable: '{name}'")

    def get_raw(self, name: str) -> Any:
        """Return raw value (SeriesValue or array) without resolving."""
        if name in self._vars:
            return self._vars[name]
        if name in self.BUILTIN_SERIES:
            arr = self._series.get(name)
            return arr
        if name == "bar_index":
            return np.arange(self.total_bars, dtype=float)
        raise NameError(f"Undefined variable: '{name}'")

    def register_plot(self, title: str, series: SeriesValue) -> None:
        key = title or f"plot_{len(self.plot_overlays) + 1}"
        self.plot_overlays[key] = series

    # ── Indicator cache ────────────────────────────────────────────────────

    def cache_indicator(self, key: str, value: SeriesValue) -> None:
        self._indicator_cache[key] = value

    def get_cached_indicator(self, key: str) -> SeriesValue | None:
        return self._indicator_cache.get(key)

    def is_cached(self, key: str) -> bool:
        return key in self._indicator_cache
