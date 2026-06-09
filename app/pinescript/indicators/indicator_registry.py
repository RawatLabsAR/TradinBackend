"""
Built-in technical indicator implementations.

All functions accept and return numpy arrays (float64).
NaN is used for periods where insufficient data exists.
"""
from __future__ import annotations

import math
import logging
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────── Core maths ──────────────────────────────────────

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average (Wilder-style seed: first SMA)."""
    if len(data) < period:
        return np.full(len(data), np.nan)
    result = np.full(len(data), np.nan)
    # Seed value: SMA of first `period` bars
    seed = np.nanmean(data[:period])
    result[period - 1] = seed
    k = 2.0 / (period + 1)
    for i in range(period, len(data)):
        if np.isnan(data[i]):
            result[i] = result[i - 1]
        else:
            result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    result = np.full(len(data), np.nan)
    for i in range(period - 1, len(data)):
        result[i] = np.nanmean(data[i - period + 1 : i + 1])
    return result


def _rma(data: np.ndarray, period: int) -> np.ndarray:
    """Wilder's Moving Average (RMA / SMMA)."""
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    result[period - 1] = np.nanmean(data[:period])
    alpha = 1.0 / period
    for i in range(period, len(data)):
        result[i] = data[i] * alpha + result[i - 1] * (1 - alpha)
    return result


# ─────────────────────────── Public indicators ───────────────────────────────

def ta_ema(series: np.ndarray, period: int) -> np.ndarray:
    return _ema(series, int(period))


def ta_sma(series: np.ndarray, period: int) -> np.ndarray:
    return _sma(series, int(period))


def ta_rsi(series: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    period = int(period)
    delta = np.diff(series.astype(float))
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)

    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    rsi = 100.0 - (100.0 / (1 + rs))
    return np.concatenate([[np.nan], rsi])


def ta_macd(series: np.ndarray,
            fast: int = 12,
            slow: int = 26,
            signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    MACD indicator.
    Returns (macd_line, signal_line, histogram).
    """
    fast_ema = _ema(series, int(fast))
    slow_ema = _ema(series, int(slow))
    macd_line = fast_ema - slow_ema
    signal_line = _ema(np.where(np.isnan(macd_line), 0.0, macd_line), int(signal))
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def ta_bb(series: np.ndarray,
          period: int = 20,
          mult: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Bollinger Bands.
    Returns (upper, middle, lower).
    """
    period = int(period)
    middle = _sma(series, period)
    std = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        std[i] = np.std(series[i - period + 1 : i + 1], ddof=0)
    upper = middle + mult * std
    lower = middle - mult * std
    return upper, middle, lower


def ta_atr(high: np.ndarray,
           low: np.ndarray,
           close: np.ndarray,
           period: int = 14) -> np.ndarray:
    """Average True Range."""
    period = int(period)
    tr = np.full(len(high), np.nan)
    for i in range(1, len(high)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    tr[0] = high[0] - low[0]
    return _rma(tr, period)


def ta_stoch(high: np.ndarray,
             low: np.ndarray,
             close: np.ndarray,
             k_period: int = 14,
             d_period: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic oscillator (K%, D%)."""
    k_period = int(k_period)
    d_period = int(d_period)
    k = np.full(len(close), np.nan)
    for i in range(k_period - 1, len(close)):
        h = np.max(high[i - k_period + 1 : i + 1])
        l = np.min(low[i - k_period + 1 : i + 1])
        k[i] = 100.0 * (close[i] - l) / (h - l) if (h - l) != 0 else 50.0
    d = _sma(np.where(np.isnan(k), 0.0, k), d_period)
    return k, d


def ta_vwap(high: np.ndarray,
            low: np.ndarray,
            close: np.ndarray,
            volume: np.ndarray) -> np.ndarray:
    """Volume Weighted Average Price (cumulative)."""
    typical = (high + low + close) / 3.0
    cum_tp_vol = np.nancumsum(typical * volume)
    cum_vol = np.nancumsum(volume)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(cum_vol == 0, np.nan, cum_tp_vol / cum_vol)


def ta_change(series: np.ndarray, length: int = 1) -> np.ndarray:
    length = int(length)
    result = np.full(len(series), np.nan)
    if length < len(series):
        result[length:] = series[length:] - series[:-length]
    return result


def ta_highest(series: np.ndarray, length: int) -> np.ndarray:
    length = int(length)
    result = np.full(len(series), np.nan)
    for i in range(length - 1, len(series)):
        result[i] = np.nanmax(series[i - length + 1 : i + 1])
    return result


def ta_lowest(series: np.ndarray, length: int) -> np.ndarray:
    length = int(length)
    result = np.full(len(series), np.nan)
    for i in range(length - 1, len(series)):
        result[i] = np.nanmin(series[i - length + 1 : i + 1])
    return result


def ta_tr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True Range."""
    tr = np.full(len(high), np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    return tr


def ta_wma(series: np.ndarray, period: int) -> np.ndarray:
    period = int(period)
    weights = np.arange(1, period + 1, dtype=float)
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        window = series[i - period + 1 : i + 1]
        result[i] = np.dot(window, weights) / weights.sum()
    return result


def ta_stdev(series: np.ndarray, period: int) -> np.ndarray:
    period = int(period)
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = np.std(series[i - period + 1 : i + 1], ddof=0)
    return result


def ta_mom(series: np.ndarray, length: int = 10) -> np.ndarray:
    return ta_change(series, int(length))


def ta_roc(series: np.ndarray, length: int = 10) -> np.ndarray:
    length = int(length)
    result = np.full(len(series), np.nan)
    for i in range(length, len(series)):
        prev = series[i - length]
        if prev != 0:
            result[i] = 100.0 * (series[i] - prev) / prev
    return result


def ta_cum(series: np.ndarray) -> np.ndarray:
    return np.nancumsum(series.astype(float))


def ta_rma(series: np.ndarray, period: int) -> np.ndarray:
    return _rma(series.astype(float), int(period))


# ─────────────────────────── Cross-over helpers ──────────────────────────────

def ta_crossover(a: np.ndarray, b: np.ndarray, idx: int) -> bool:
    """Returns True when a crosses above b at bar `idx`."""
    if idx < 1 or np.isnan(a[idx]) or np.isnan(b[idx]):
        return False
    if np.isnan(a[idx - 1]) or np.isnan(b[idx - 1]):
        return False
    return bool(a[idx] > b[idx] and a[idx - 1] <= b[idx - 1])


def ta_crossunder(a: np.ndarray, b: np.ndarray, idx: int) -> bool:
    """Returns True when a crosses below b at bar `idx`."""
    if idx < 1 or np.isnan(a[idx]) or np.isnan(b[idx]):
        return False
    if np.isnan(a[idx - 1]) or np.isnan(b[idx - 1]):
        return False
    return bool(a[idx] < b[idx] and a[idx - 1] >= b[idx - 1])


# ─────────────────────────── Registry ────────────────────────────────────────

INDICATOR_REGISTRY: dict[str, Callable] = {
    "ema": ta_ema,
    "sma": ta_sma,
    "rsi": ta_rsi,
    "macd": ta_macd,
    "bb": ta_bb,
    "atr": ta_atr,
    "stoch": ta_stoch,
    "vwap": ta_vwap,
    "change": ta_change,
    "highest": ta_highest,
    "lowest": ta_lowest,
    "tr": ta_tr,
    "wma": ta_wma,
    "stdev": ta_stdev,
    "mom": ta_mom,
    "roc": ta_roc,
    "cum": ta_cum,
    "rma": ta_rma,
}

CROSSOVER_REGISTRY: dict[str, Callable] = {
    "crossover": ta_crossover,
    "crossunder": ta_crossunder,
}

def get_indicator(name: str) -> Callable | None:
    return INDICATOR_REGISTRY.get(name.lower())

def get_crossover_fn(name: str) -> Callable | None:
    return CROSSOVER_REGISTRY.get(name.lower())
