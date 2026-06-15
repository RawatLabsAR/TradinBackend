"""Growth potential scoring for discovered tokens."""

from __future__ import annotations

import math
from typing import Optional

from app.discovery.types import DiscoveryToken

MIN_LIQUIDITY_USD = 5_000.0
MIN_VOLUME_USD = 10_000.0
MIN_LIQUIDITY_NEW_DEX = 1_000.0
MIN_VOLUME_NEW_DEX = 2_000.0
MIN_ACTIVITY_TRENDING = 1_000.0
MAX_AGE_HOURS_NEW = 720.0  # 30 days


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _log_norm(value: float, scale: float = 1.0) -> float:
    if value <= 0:
        return 0.0
    return _clamp(math.log10(value + 1) * scale)


def freshness_score(age_hours: float) -> float:
    """Peak score for tokens 6–72 hours old."""
    if age_hours <= 0:
        return 40.0
    if age_hours < 6:
        return _clamp(20 + age_hours * 3)
    if age_hours <= 72:
        return _clamp(100 - abs(age_hours - 36) * 1.2)
    if age_hours <= 168:
        return _clamp(70 - (age_hours - 72) * 0.3)
    return _clamp(30 - (age_hours - 168) * 0.05)


def passes_hard_filters(token: DiscoveryToken) -> bool:
    if token.source_type == "cex":
        return bool(token.product_id or token.symbol)

    category = token.discovery_category or ""

    # CoinGecko market entries without on-chain address
    if not token.contract_address:
        return category in ("trending",) and bool(token.symbol)

    if category == "new_dex":
        if token.age_hours > MAX_AGE_HOURS_NEW:
            return False
        return token.volume_24h >= MIN_VOLUME_NEW_DEX or token.liquidity >= MIN_LIQUIDITY_NEW_DEX

    if category in ("trending", "surging"):
        return (
            token.volume_24h >= MIN_ACTIVITY_TRENDING
            or token.liquidity >= MIN_ACTIVITY_TRENDING
            or token.tx_count_24h >= 10
            or token.price_change_24h >= 5
        )

    if token.liquidity <= 0 and token.volume_24h <= 0:
        return False
    if token.liquidity > 0 and token.liquidity < MIN_LIQUIDITY_USD and token.volume_24h < MIN_VOLUME_USD:
        return False
    return True


def compute_growth_score(
    token: DiscoveryToken,
    *,
    volume_change_pct: float = 0.0,
) -> tuple[float, dict[str, float]]:
    breakdown: dict[str, float] = {}

    if token.source_type == "cex":
        vol = _log_norm(token.volume_24h, 25)
        momentum = _clamp(max(0.0, token.price_change_24h) * 2.5, 0, 25)
        fresh = freshness_score(token.age_hours) * 0.2
        verified = 10.0 if token.verified else 0.0
        breakdown = {
            "volume": vol,
            "momentum": momentum,
            "freshness": fresh,
            "safety": verified,
        }
        total = _clamp(vol * 0.35 + momentum * 0.35 + fresh * 0.2 + verified * 0.1)
        return round(total, 1), breakdown

    fresh = freshness_score(token.age_hours)
    vol = _log_norm(token.volume_24h, 22)
    liq = _log_norm(token.liquidity, 18)
    momentum = _clamp(max(0.0, token.price_change_24h) * 1.5, 0, 20)
    vol_momentum = _clamp(volume_change_pct * 0.15, 0, 25) if volume_change_pct > 0 else 0.0

    activity = 0.0
    if token.tx_count_24h > 0:
        activity = _log_norm(float(token.tx_count_24h), 12)
    elif token.buy_sell_ratio > 1.2:
        activity = _clamp(token.buy_sell_ratio * 5, 0, 12)

    safety = 0.0
    if token.verified:
        safety += 8.0
    if token.liquidity >= 50_000:
        safety += 5.0
    trusted = {"uniswap", "raydium", "orca", "pancakeswap", "aerodrome", "curve"}
    if any(d in token.dex.lower() for d in trusted):
        safety += 4.0

    breakdown = {
        "freshness": round(fresh * 0.20, 1),
        "volume": round(vol * 0.25, 1),
        "liquidity": round(liq * 0.20, 1),
        "price_momentum": round(momentum * 0.15, 1),
        "volume_momentum": round(vol_momentum * 0.10, 1),
        "activity": round(activity * 0.05, 1),
        "safety": round(safety * 0.05, 1),
    }

    raw = (
        fresh * 0.20
        + vol * 0.25
        + liq * 0.20
        + momentum * 0.15
        + vol_momentum * 0.10
        + activity * 0.05
        + safety * 0.05
    )
    return round(_clamp(raw), 1), breakdown


def assign_risk_level(token: DiscoveryToken, growth_score: float) -> str:
    if token.source_type == "cex":
        return "low"
    if token.verified and token.liquidity >= 100_000:
        return "medium"
    if growth_score >= 70 and token.liquidity >= 50_000:
        return "medium"
    return "high"


def score_token(
    token: DiscoveryToken,
    *,
    volume_change_pct: float = 0.0,
) -> Optional[DiscoveryToken]:
    if not passes_hard_filters(token):
        return None

    growth, breakdown = compute_growth_score(token, volume_change_pct=volume_change_pct)
    token.growth_score = growth
    token.score_breakdown = breakdown
    token.volume_change_pct = volume_change_pct
    token.risk_level = assign_risk_level(token, growth)
    return token


def is_surging_candidate(
    token: DiscoveryToken,
    volume_change_pct: float,
    *,
    min_volume_change: float = 50.0,
) -> bool:
    """Detect surge signals — works on first scan without prior snapshots."""
    if volume_change_pct >= min_volume_change:
        return True
    if token.price_change_24h >= 10:
        return True
    if token.volume_24h >= 25_000 and token.price_change_24h > 0:
        return True
    if token.tx_count_24h >= 50 and token.volume_24h >= 5_000:
        return True
    return False


def dedupe_tokens(tokens: list[DiscoveryToken]) -> list[DiscoveryToken]:
    """Keep highest growth score per identity."""
    best: dict[str, DiscoveryToken] = {}
    for token in tokens:
        if token.source_type == "cex" and token.product_id:
            key = f"cex:{token.product_id}"
        elif token.chain and token.contract_address:
            key = token.identity_key()
        else:
            key = f"sym:{token.symbol}:{token.source}"
        existing = best.get(key)
        if existing is None or token.growth_score > existing.growth_score:
            best[key] = token
    return list(best.values())
