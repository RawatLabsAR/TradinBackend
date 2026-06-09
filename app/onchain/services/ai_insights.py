"""AI insight generation for on-chain analytics."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


def _signal_field(signal: Any, field: str, default: Any = "") -> Any:
    if isinstance(signal, dict):
        return signal.get(field, default)
    return getattr(signal, field, default)


async def generate_onchain_ai_insight(
    db: AsyncSession,
    chain: str,
    token_address: str,
    signals: list[Any],
) -> Optional[str]:
    """Generate AI insight text from on-chain signals."""
    if not signals:
        return None

    # Build insight from signals without requiring OpenAI for basic cases
    smart_money = [
        s for s in signals
        if _signal_field(s, "signal_type") == "SMART_MONEY_ACCUMULATION"
    ]
    whale = [
        s for s in signals
        if "WHALE" in str(_signal_field(s, "signal_type"))
        or _signal_field(s, "signal_type") in ("LARGE_BUY", "ACCUMULATION")
    ]
    liquidity = [
        s for s in signals
        if "LIQUIDITY" in str(_signal_field(s, "signal_type"))
    ]

    parts: list[str] = []

    if smart_money:
        sm = smart_money[0]
        desc = _signal_field(sm, "description")
        parts.append(desc or "Smart money wallets are actively accumulating this token.")

    if whale:
        w = whale[0]
        desc = _signal_field(w, "description")
        parts.append(desc or "Whale activity detected on this token.")

    if liquidity:
        liq = liquidity[0]
        desc = _signal_field(liq, "description")
        parts.append(desc or "Significant liquidity changes detected.")

    if parts:
        return " ".join(parts)

    # Optional OpenAI enhancement
    if settings.OPENAI_API_KEY and len(signals) >= 2:
        try:
            from app.services.ai.openai_service import chat_json
            signal_summary = "\n".join(
                f"- {_signal_field(s, 'signal_type')}: {_signal_field(s, 'description')}"
                for s in signals[:5]
            )
            prompt = (
                f"Generate a single concise on-chain intelligence insight (2 sentences max) "
                f"for token {token_address} on {chain} based on:\n{signal_summary}"
            )
            result, _, _ = await chat_json(
                system_prompt="You are a crypto on-chain analyst. Be concise and factual. Return JSON with key 'insight'.",
                user_prompt=prompt,
            )
            if isinstance(result, dict) and result.get("insight"):
                return result["insight"]
        except Exception as exc:
            logger.debug("OpenAI on-chain insight skipped: %s", exc)

    return None
