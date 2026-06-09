"""Telegram broadcast helpers for token discovery."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.token_search.types import NormalizedToken

logger = logging.getLogger(__name__)


async def broadcast_token_alert(
    db: AsyncSession,
    token: NormalizedToken,
    *,
    message: str = "",
) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False

    try:
        from app.broadcast.services.broadcast_service import broadcast_service

        title = f"🔍 Token Alert: {token.symbol}"
        content = message or (
            f"*Token:* {token.token_name} ({token.symbol})\n"
            f"*Chain:* `{token.chain}`\n"
            f"*Contract:* `{token.contract_address}`\n"
            f"*DEX:* {token.dex or 'N/A'}\n"
            f"*Liquidity:* ${token.liquidity:,.0f}\n"
            f"*Volume 24h:* ${token.volume_24h:,.0f}\n"
            f"*Market Cap:* ${token.market_cap:,.0f}\n"
            f"*Verified:* {'Yes' if token.verified else 'No'}"
        )

        msg = await broadcast_service.send_manual(db, content=content, title=title)
        await db.commit()
        await broadcast_service.enqueue_committed_message(msg)
        return True
    except Exception as exc:
        logger.warning("Token Telegram alert failed: %s", exc)
        return False
