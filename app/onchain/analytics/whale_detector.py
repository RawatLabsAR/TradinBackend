"""Whale detection — large buys, exits, coordinated activity."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.onchain.models.entities import OnchainTrade, WhaleWallet
from app.onchain.types import OnchainSignal

logger = logging.getLogger(__name__)


async def detect_whale_events(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    hours: int = 1,
    threshold_usd: Optional[float] = None,
) -> list[WhaleWallet]:
    """Detect and persist whale events from recent trades."""
    threshold = threshold_usd or settings.WHALE_THRESHOLD_USD
    since = datetime.utcnow() - timedelta(hours=hours)

    result = await db.execute(
        select(OnchainTrade).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.timestamp >= since,
            OnchainTrade.usd_value >= threshold,
        ).order_by(OnchainTrade.timestamp.desc())
    )
    trades = result.scalars().all()
    events: list[WhaleWallet] = []

    for trade in trades:
        event_type = "LARGE_BUY" if trade.side == "BUY" else "LARGE_SELL"
        desc = (
            f"{'Whale buy' if trade.side == 'BUY' else 'Whale sell'} "
            f"${trade.usd_value:,.0f} on {trade.dex or 'DEX'}"
        )
        event = WhaleWallet(
            chain=chain,
            wallet=trade.wallet,
            token_address=token_address,
            event_type=event_type,
            usd_value=trade.usd_value,
            description=desc,
            tx_hash=trade.tx_hash,
            detected_at=trade.timestamp,
            metadata_json={"side": trade.side, "dex": trade.dex},
        )
        db.add(event)
        events.append(event)

    # Coordinated activity: 3+ wallets buying within 15 minutes
    buy_trades = [t for t in trades if t.side == "BUY"]
    window_groups: dict[str, list] = defaultdict(list)
    for t in buy_trades:
        window_key = t.timestamp.strftime("%Y%m%d%H") + str(t.timestamp.minute // 15)
        window_groups[window_key].append(t)

    for window_trades in window_groups.values():
        unique_wallets = {t.wallet for t in window_trades}
        if len(unique_wallets) >= 3:
            total_usd = sum(t.usd_value for t in window_trades)
            event = WhaleWallet(
                chain=chain,
                wallet="coordinated",
                token_address=token_address,
                event_type="COORDINATED_ACTIVITY",
                usd_value=total_usd,
                description=(
                    f"Coordinated accumulation: {len(unique_wallets)} wallets "
                    f"bought ${total_usd:,.0f} within 15 minutes"
                ),
                detected_at=window_trades[0].timestamp,
                metadata_json={"wallets": list(unique_wallets)[:10]},
            )
            db.add(event)
            events.append(event)

    # Sudden accumulation: single wallet multiple large buys
    wallet_buys: dict[str, list] = defaultdict(list)
    for t in buy_trades:
        wallet_buys[t.wallet].append(t)

    for wallet, wtrades in wallet_buys.items():
        if len(wtrades) >= 2:
            total = sum(t.usd_value for t in wtrades)
            if total >= threshold * 1.5:
                event = WhaleWallet(
                    chain=chain,
                    wallet=wallet,
                    token_address=token_address,
                    event_type="ACCUMULATION",
                    usd_value=total,
                    description=f"Wallet accumulated ${total:,.0f} in {len(wtrades)} buys",
                    detected_at=wtrades[0].timestamp,
                    metadata_json={"trade_count": len(wtrades)},
                )
                db.add(event)
                events.append(event)

    return events


def whale_events_to_signals(events: list[WhaleWallet]) -> list[OnchainSignal]:
    signals = []
    for e in events:
        severity = "critical" if e.usd_value >= settings.WHALE_THRESHOLD_USD * 2 else "warning"
        signals.append(OnchainSignal(
            chain=e.chain,
            token_address=e.token_address,
            signal_type=e.event_type,
            severity=severity,
            title=e.event_type.replace("_", " ").title(),
            description=e.description,
            usd_value=e.usd_value,
            wallet=e.wallet,
            created_at=e.detected_at,
        ))
    return signals
