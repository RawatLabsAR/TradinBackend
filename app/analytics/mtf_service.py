"""Multi-timeframe confluence analysis."""

from __future__ import annotations

from app.core.cache import cache
from app.services import market_service

_TIMEFRAMES = ["15m", "1H", "4H", "1D"]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _analyze_tf(closes: list[float]) -> dict:
    if len(closes) < 20:
        return {"trend": "neutral", "rsi": 50.0, "ema_cross": "none", "score": 0}

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    rsi_val = _rsi(closes)
    price = closes[-1]

    trend = "neutral"
    score = 0
    if price > ema9[-1] > ema21[-1]:
        trend, score = "bullish", 1
    elif price < ema9[-1] < ema21[-1]:
        trend, score = "bearish", -1

    ema_cross = "none"
    if len(ema9) >= 2 and len(ema21) >= 2:
        if ema9[-2] <= ema21[-2] and ema9[-1] > ema21[-1]:
            ema_cross, score = "golden", score + 1
        elif ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1]:
            ema_cross, score = "death", score - 1

    if rsi_val > 60:
        score += 1 if trend == "bullish" else 0
    elif rsi_val < 40:
        score -= 1 if trend == "bearish" else 0

    return {"trend": trend, "rsi": round(rsi_val, 1), "ema_cross": ema_cross, "score": score}


async def get_mtf_confluence(product_id: str) -> dict:
    cache_key = f"analytics:mtf:{product_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    product_id = product_id.upper()
    signals = []
    total_score = 0

    for tf in _TIMEFRAMES:
        try:
            candles = await market_service.get_candles(product_id, tf)
            closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
            analysis = _analyze_tf(closes)
            signals.append({"timeframe": tf, **analysis})
            total_score += analysis["score"]
        except Exception:
            signals.append({
                "timeframe": tf,
                "trend": "neutral",
                "rsi": 50.0,
                "ema_cross": "none",
                "score": 0,
            })

    max_score = len(_TIMEFRAMES) * 2
    confluence_pct = round((total_score + max_score) / (2 * max_score) * 100, 1) if max_score else 50

    if total_score >= 2:
        bias = "bullish"
    elif total_score <= -2:
        bias = "bearish"
    else:
        bias = "neutral"

    result = {
        "product_id": product_id,
        "signals": signals,
        "overall_score": total_score,
        "bias": bias,
        "confluence_pct": confluence_pct,
    }
    cache.set(cache_key, result, 120)
    return result
