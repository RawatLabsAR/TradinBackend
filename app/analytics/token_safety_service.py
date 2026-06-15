"""Token safety scanner using DexScreener (free public API)."""

from __future__ import annotations

import logging

from app.analytics.http_client import fetch_json
from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)


async def scan_token_safety(chain: str, address: str) -> dict:
    chain = chain.lower()
    addr = address.lower() if address.startswith("0x") else address
    cache_key = f"analytics:safety:{chain}:{addr}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    flags: list[str] = []
    score = 100
    liquidity = None
    symbol = "UNKNOWN"
    holder_pct = None

    try:
        url = f"{settings.DEXSCREENER_API_URL}/latest/dex/tokens/{addr}"
        data = await fetch_json(url, timeout_sec=15)

        pairs = data.get("pairs") or []
        if not pairs:
            flags.append("No DEX pairs found")
            score -= 40
        else:
            best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
            symbol = best.get("baseToken", {}).get("symbol", symbol)
            liquidity = float(best.get("liquidity", {}).get("usd", 0) or 0)
            if liquidity < 10_000:
                flags.append("Very low liquidity (<$10k)")
                score -= 30
            elif liquidity < 50_000:
                flags.append("Low liquidity (<$50k)")
                score -= 15

            vol_h24 = float(best.get("volume", {}).get("h24", 0) or 0)
            if vol_h24 < 1000:
                flags.append("Minimal 24h volume")
                score -= 10

            price_change = float(best.get("priceChange", {}).get("h24", 0) or 0)
            if abs(price_change) > 80:
                flags.append("Extreme 24h price move (>80%)")
                score -= 10

            if best.get("info", {}).get("isScam"):
                flags.append("Flagged as potential scam")
                score -= 50
    except Exception as exc:
        logger.warning("Token safety scan failed: %s", exc)
        flags.append("Unable to fetch DEX data")
        score -= 20

    if score >= 80:
        risk = "low"
    elif score >= 60:
        risk = "medium"
    elif score >= 40:
        risk = "high"
    else:
        risk = "critical"

    recommendations = []
    if liquidity and liquidity < 50_000:
        recommendations.append("Use small position sizes due to low liquidity")
    if "Extreme" in " ".join(flags):
        recommendations.append("Wait for volatility to settle before entry")
    if risk in ("high", "critical"):
        recommendations.append("Conduct additional due diligence before trading")
    if not recommendations:
        recommendations.append("Standard risk management applies")

    result = {
        "chain": chain,
        "address": addr,
        "symbol": symbol,
        "score": max(0, score),
        "risk_level": risk,
        "flags": flags,
        "liquidity_usd": liquidity,
        "holder_concentration_pct": holder_pct,
        "is_verified": False,
        "recommendations": recommendations,
        "source": "dexscreener.com (free)",
    }
    cache.set(cache_key, result, 300)
    return result
