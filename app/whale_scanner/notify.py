"""Send whale scan digest to Telegram."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.telegram.telegram_client import TelegramClient
from app.models.whale_scan import WhaleScanNotification
from app.onchain.models.entities import WhaleWallet
from app.whale_scanner.scan import TokenScanResult
from app.whale_scanner.settings import whale_scan_settings

logger = logging.getLogger(__name__)

_EVENT_EMOJI = {
    "LARGE_BUY": "🟢",
    "ACCUMULATION": "🟢",
    "COORDINATED_ACTIVITY": "🟡",
    "LARGE_SELL": "🔴",
}


def _summarize_events(events: list[WhaleWallet]) -> str:
    if not events:
        return "No whale events"
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
    parts = []
    for etype, count in sorted(by_type.items(), key=lambda x: -x[1]):
        emoji = _EVENT_EMOJI.get(etype, "•")
        label = etype.replace("_", " ").title()
        parts.append(f"{emoji} {count}× {label}")
    max_usd = max(e.usd_value for e in events)
    parts.append(f"max ${max_usd:,.0f}")
    return " · ".join(parts)


def build_digest_message(
    hits: list[TokenScanResult],
    *,
    scanned_count: int,
    run_date: datetime | None = None,
) -> str:
    run_date = run_date or datetime.now(timezone.utc)
    header = (
        f"🐋 *Tradin Whale Scan* — {run_date.strftime('%d %b %Y')}\n"
        f"New tokens (≤{whale_scan_settings.MAX_AGE_DAYS}d) with whale activity "
        f"in last {whale_scan_settings.WHALE_LOOKBACK_HOURS}h\n"
    )
    if not hits:
        return (
            header
            + f"\n_No significant whale activity detected today._\n\n"
            f"Scanned {scanned_count} tokens · threshold "
            f"${whale_scan_settings.WHALE_THRESHOLD_USD:,.0f}"
        )

    lines = [header, ""]
    base = whale_scan_settings.app_link_base
    for idx, hit in enumerate(hits[: whale_scan_settings.MAX_TELEGRAM_ALERTS], start=1):
        c = hit.candidate
        sym = c.symbol or c.token_name or c.contract_address[:8]
        summary = _summarize_events(hit.events)
        link = f"{base}/token/{c.chain}/{c.contract_address}"
        lines.append(
            f"*{idx}. {sym}* · `{c.chain}`\n"
            f"   {summary}\n"
            f"   Liq ${c.liquidity_usd:,.0f} · Vol 24h ${c.volume_24h:,.0f}\n"
            f"   `{c.contract_address[:10]}…` · [View]({link})\n"
        )

    footer = (
        f"\n—\n"
        f"Scanned {scanned_count} tokens · {len(hits)} with whales · "
        f"threshold ${whale_scan_settings.WHALE_THRESHOLD_USD:,.0f}\n"
        f"_Not financial advice._"
    )
    return "\n".join(lines) + footer


async def _already_notified_today(db: AsyncSession, candidate_id: int) -> bool:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(WhaleScanNotification.id).where(
            WhaleScanNotification.candidate_id == candidate_id,
            WhaleScanNotification.notified_at >= today_start,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def send_digest(
    db: AsyncSession,
    hits: list[TokenScanResult],
    *,
    run_id: int,
    scanned_count: int,
) -> int:
    chat_id = whale_scan_settings.telegram_chat_id
    token = whale_scan_settings.TELEGRAM_BOT_TOKEN.strip()

    if not hits:
        logger.info("No whale hits — skipping Telegram (scanned %d)", scanned_count)
        return 0

    if whale_scan_settings.DRY_RUN:
        logger.info(
            "DRY RUN — would notify %d tokens:\n%s",
            len(hits),
            build_digest_message(hits, scanned_count=scanned_count),
        )
        return 0

    if not token or not chat_id:
        logger.warning(
            "Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_WHALE_CHANNEL_ID"
        )
        return 0

    fresh_hits = []
    for hit in hits:
        if await _already_notified_today(db, hit.candidate.id):
            continue
        fresh_hits.append(hit)

    if not fresh_hits:
        logger.info("All whale hits already notified today")
        return 0

    text = build_digest_message(fresh_hits, scanned_count=scanned_count)
    client = TelegramClient(token)
    await client.start()
    try:
        resp = await client.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        msg_id = resp.get("message_id") if isinstance(resp, dict) else None
    finally:
        await client.stop()

    for hit in fresh_hits:
        db.add(
            WhaleScanNotification(
                run_id=run_id,
                candidate_id=hit.candidate.id,
                event_type="digest",
                usd_value=hit.max_usd,
                telegram_message_id=msg_id,
            )
        )
    await db.commit()
    logger.info("Telegram digest sent to %s (%d tokens)", chat_id, len(fresh_hits))
    return 1
