"""Volatility regime analysis (ATR + realized vol)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from app.core.cache import cache
from app.services import market_service

_DEFAULT = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "AVAX-USD", "LINK-USD"]


def _atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i].get("high", 0))
        l = float(candles[i].get("low", 0))
        prev_c = float(candles[i - 1].get("close", 0))
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return sum(trs[-period:]) / period


def _realized_vol(closes: list[float]) -> float:
    if len(closes) < 5:
        return 0.0
    returns = np.diff(np.log(np.array(closes, dtype=float)))
    return float(np.std(returns) * np.sqrt(365) * 100)


async def get_volatility(symbols: list[str] | None = None) -> dict:
    syms = symbols or _DEFAULT
    cache_key = f"analytics:vol:{','.join(syms)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    items = []
    atr_pcts: list[float] = []

    for product_id in syms:
        try:
            candles = await market_service.get_candles(product_id, "1D")
            if not candles:
                continue
            closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
            price = closes[-1] if closes else 0
            atr = _atr(candles)
            atr_pct = (atr / price * 100) if price else 0
            rv = _realized_vol(closes[-30:])
            atr_pcts.append(atr_pct)
            items.append({
                "product_id": product_id,
                "atr_14": round(atr, 4),
                "atr_pct": round(atr_pct, 2),
                "realized_vol_30d": round(rv, 2),
                "regime": "normal",
                "percentile_90d": 50.0,
            })
        except Exception:
            continue

    if atr_pcts:
        sorted_atr = sorted(atr_pcts)
        for item in items:
            pct = item["atr_pct"]
            rank = sum(1 for a in sorted_atr if a <= pct) / len(sorted_atr) * 100
            item["percentile_90d"] = round(rank, 1)
            if pct >= sorted_atr[-1] * 0.85:
                item["regime"] = "extreme"
            elif pct >= sorted_atr[-1] * 0.65:
                item["regime"] = "high"
            elif pct <= sorted_atr[0] * 1.5:
                item["regime"] = "low"

    result = {
        "items": items,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(cache_key, result, 300)
    return result
