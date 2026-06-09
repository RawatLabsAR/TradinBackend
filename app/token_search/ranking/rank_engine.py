"""Token search ranking — resolve symbol ambiguity via liquidity/volume/verification."""

from __future__ import annotations

import math
import re
from typing import Optional

from app.token_search.types import NormalizedToken

MIN_LIQUIDITY_USD = 500.0  # deprioritize obvious scam clones


def _log_score(value: float, weight: float = 1.0) -> float:
    if value <= 0:
        return 0.0
    return math.log10(value + 1) * weight


def compute_rank_score(token: NormalizedToken, query: str) -> float:
    """Higher score = better match. Used to sort ambiguous symbols."""
    q = query.strip().lower()
    score = 0.0

    symbol = token.symbol.lower()
    name = token.token_name.lower()

    # Exact symbol match
    if symbol == q:
        score += 500.0
    elif symbol.startswith(q):
        score += 200.0
    elif q in symbol:
        score += 80.0

    # Name match
    if name == q:
        score += 300.0
    elif q in name:
        score += 100.0

    # Fuzzy: alphanumeric only comparison
    q_clean = re.sub(r"[^a-z0-9]", "", q)
    sym_clean = re.sub(r"[^a-z0-9]", "", symbol)
    if q_clean and q_clean == sym_clean:
        score += 150.0

    # Verified on CoinGecko alone is weaker than DEX liquidity proof
    if token.verified:
        if token.liquidity >= MIN_LIQUIDITY_USD:
            score += 1000.0
        elif token.source == "coingecko":
            score += 200.0
        else:
            score += 400.0

    # Prefer live DEX pair data from DexScreener
    if token.source == "dexscreener" and token.liquidity >= MIN_LIQUIDITY_USD:
        score += 250.0

    # Liquidity / volume / market cap
    score += _log_score(token.liquidity, 120.0)
    score += _log_score(token.volume_24h, 80.0)
    score += _log_score(token.market_cap, 60.0)

    # Active trading bonus
    if token.volume_24h > 10_000:
        score += 50.0
    if token.liquidity > 50_000:
        score += 75.0

    # Penalize very low liquidity clones
    if 0 < token.liquidity < MIN_LIQUIDITY_USD:
        score -= 200.0
    if token.liquidity == 0 and token.volume_24h == 0:
        score -= 100.0

    # Trusted DEX presence
    trusted_dexes = {"uniswap", "raydium", "orca", "pancakeswap", "aerodrome", "curve"}
    if any(d in token.dex.lower() for d in trusted_dexes):
        score += 40.0

    return round(score, 4)


def rank_tokens(
    tokens: list[NormalizedToken],
    query: str,
    *,
    limit: int = 20,
) -> list[NormalizedToken]:
    """Deduplicate by identity, score, and sort."""
    by_key: dict[str, NormalizedToken] = {}

    for token in tokens:
        key = token.identity_key()
        token.rank_score = compute_rank_score(token, query)

        existing = by_key.get(key)
        if existing is None or token.rank_score > existing.rank_score:
            # Merge best metrics from duplicate entries
            if existing:
                token.liquidity = max(token.liquidity, existing.liquidity)
                token.volume_24h = max(token.volume_24h, existing.volume_24h)
                token.market_cap = max(token.market_cap, existing.market_cap)
                token.verified = token.verified or existing.verified
                if not token.logo_url:
                    token.logo_url = existing.logo_url
            by_key[key] = token

    ranked = sorted(by_key.values(), key=lambda t: t.rank_score, reverse=True)
    return ranked[:limit]


def filter_low_quality(tokens: list[NormalizedToken], *, min_score: float = -500) -> list[NormalizedToken]:
    return [t for t in tokens if t.rank_score >= min_score]
