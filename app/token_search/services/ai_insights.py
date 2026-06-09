"""AI summaries for discovered tokens."""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.token_search.types import NormalizedToken

logger = logging.getLogger(__name__)


async def generate_token_ai_summary(token: NormalizedToken) -> Optional[str]:
    """Generate concise AI insight for a token."""
    parts: list[str] = []

    if token.verified:
        parts.append(f"{token.symbol} appears on verified listings.")
    else:
        parts.append(f"{token.symbol} is unverified — exercise caution.")

    if token.liquidity > 100_000:
        parts.append(f"Liquidity is ${token.liquidity:,.0f}.")
    elif token.liquidity > 0:
        parts.append(f"Low liquidity (${token.liquidity:,.0f}) — high slippage risk.")
    else:
        parts.append("No liquidity data available.")

    if token.volume_24h > 1_000_000:
        parts.append(f"Strong 24h volume (${token.volume_24h:,.0f}).")
    elif token.volume_24h == 0:
        parts.append("No recent trading volume detected.")

    if token.market_cap > 0:
        parts.append(f"Market cap ~${token.market_cap:,.0f}.")

    base_summary = " ".join(parts)

    if not settings.OPENAI_API_KEY:
        return base_summary

    try:
        from app.services.ai.openai_service import chat_json
        prompt = (
            f"Token: {token.token_name} ({token.symbol}) on {token.chain}\n"
            f"Contract: {token.contract_address}\n"
            f"Liquidity: ${token.liquidity:,.0f}, Volume 24h: ${token.volume_24h:,.0f}\n"
            f"Verified: {token.verified}, DEX: {token.dex}\n\n"
            "Write a 2-sentence on-chain intelligence summary including scam risk hint."
        )
        result, _, _ = await chat_json(
            system_prompt="You are a crypto token analyst. Be concise. Return JSON with key 'summary'.",
            user_prompt=prompt,
        )
        if isinstance(result, dict) and result.get("summary"):
            return result["summary"]
    except Exception as exc:
        logger.debug("Token AI summary skipped: %s", exc)

    return base_summary
