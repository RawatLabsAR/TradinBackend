"""Telegram alerts for on-chain events."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

ALERT_TYPES = {
    "LARGE_BUY", "LARGE_SELL", "ACCUMULATION", "EXIT",
    "COORDINATED_ACTIVITY", "SMART_MONEY_ACCUMULATION",
    "LIQUIDITY_REMOVAL", "LIQUIDITY_INCREASE",
}


async def broadcast_onchain_telegram_alerts(
    db: AsyncSession,
    chain: str,
    token_address: str,
    signals: list[dict[str, Any]],
) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    critical_signals = [
        s for s in signals
        if s.get("signal_type") in ALERT_TYPES
        and s.get("severity") in ("warning", "critical")
    ]
    if not critical_signals:
        return

    try:
        from app.broadcast.services.broadcast_service import broadcast_service

        for signal in critical_signals[:5]:
            title = f"🐋 On-Chain Alert: {signal.get('title', 'Event')}"
            content = (
                f"*Chain:* `{chain}`\n"
                f"*Token:* `{token_address[:12]}...`\n"
                f"*Type:* {signal.get('signal_type', '')}\n"
                f"*Severity:* {signal.get('severity', 'info')}\n\n"
                f"{signal.get('description', '')}\n"
            )
            if signal.get("usd_value"):
                content += f"\n*Value:* ${signal['usd_value']:,.0f}"

            message = await broadcast_service.send_manual(
                db,
                content=content,
                title=title,
            )
            await db.commit()
            await broadcast_service.enqueue_committed_message(message)

    except Exception as exc:
        logger.warning("On-chain Telegram alert failed: %s", exc)
