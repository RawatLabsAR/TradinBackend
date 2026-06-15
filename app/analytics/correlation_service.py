"""Price correlation matrix from historical candles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from app.core.cache import cache
from app.services import market_service

logger = logging.getLogger(__name__)


def _returns(closes: list[float]) -> np.ndarray:
    arr = np.array(closes, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return np.diff(arr) / arr[:-1]


async def get_correlation_matrix(
    symbols: list[str] | None = None,
    period_days: int = 30,
) -> dict:
    syms = symbols or ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
    cache_key = f"analytics:corr:{','.join(syms)}:{period_days}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    returns_map: dict[str, np.ndarray] = {}
    for product_id in syms:
        try:
            candles = await market_service.get_candles(product_id, "1D")
            closes = [float(c.get("close", 0)) for c in candles[-period_days:] if c.get("close")]
            if len(closes) >= 5:
                returns_map[product_id] = _returns(closes)
        except Exception as exc:
            logger.debug("Correlation skip %s: %s", product_id, exc)

    valid_syms = [s for s in syms if s in returns_map]
    n = len(valid_syms)
    matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    pairs = []

    for i in range(n):
        for j in range(i + 1, n):
            r1, r2 = returns_map[valid_syms[i]], returns_map[valid_syms[j]]
            min_len = min(len(r1), len(r2))
            if min_len < 3:
                continue
            corr = float(np.corrcoef(r1[-min_len:], r2[-min_len:])[0, 1])
            matrix[i][j] = matrix[j][i] = round(corr, 4)
            pairs.append({
                "symbol_a": valid_syms[i].replace("-USD", ""),
                "symbol_b": valid_syms[j].replace("-USD", ""),
                "correlation": round(corr, 4),
                "period_days": period_days,
            })

    result = {
        "symbols": [s.replace("-USD", "") for s in valid_syms],
        "matrix": matrix,
        "pairs": pairs,
        "period_days": period_days,
    }
    cache.set(cache_key, result, 600)
    return result
