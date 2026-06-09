"""On-chain signal generation from analytics."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.onchain.analytics.volume_analytics import compute_volume_metrics
from app.onchain.analytics.holder_analytics import compute_holder_growth
from app.onchain.models.entities import LiquidityEvent, OnchainTrade, SmartMoneyWallet
from app.onchain.types import OnchainSignal


async def generate_signals(
    db: AsyncSession,
    chain: str,
    token_address: str,
    *,
    hours: int = 24,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[OnchainSignal]:
    """Generate on-chain signals from computed analytics."""
    if since is None and until is None:
        since = datetime.utcnow() - timedelta(hours=hours)
        until = datetime.utcnow()
    elif since is None:
        since = until - timedelta(hours=hours)  # type: ignore[operator]
    elif until is None:
        until = datetime.utcnow()

    signals: list[OnchainSignal] = []

    volume = await compute_volume_metrics(
        db, chain, token_address,
        since=since,
        until=until,
        whale_threshold_usd=settings.WHALE_THRESHOLD_USD,
    )

    if volume["net_flow_usd"] > settings.WHALE_THRESHOLD_USD:
        signals.append(OnchainSignal(
            chain=chain,
            token_address=token_address,
            signal_type="NET_BUY_PRESSURE",
            severity="info",
            title="Strong Buy Pressure",
            description=(
                f"Net buy flow ${volume['net_flow_usd']:,.0f} "
                f"({volume['unique_buyers']} buyers vs {volume['unique_sellers']} sellers)"
            ),
            usd_value=volume["net_flow_usd"],
        ))

    # Smart money accumulation (within selected window, last hour of window)
    sm_window_start = max(since, until - timedelta(hours=1))
    sm_result = await db.execute(
        select(SmartMoneyWallet).where(
            SmartMoneyWallet.chain == chain,
            SmartMoneyWallet.token_address == token_address,
            SmartMoneyWallet.score >= settings.SMART_MONEY_MIN_SCORE,
        ).order_by(SmartMoneyWallet.score.desc()).limit(10)
    )
    smart_wallets = sm_result.scalars().all()

    if smart_wallets:
        sm_buys = await db.execute(
            select(func.count(OnchainTrade.id)).where(
                OnchainTrade.chain == chain,
                OnchainTrade.token_address == token_address,
                OnchainTrade.side == "BUY",
                OnchainTrade.timestamp >= sm_window_start,
                OnchainTrade.timestamp <= until,
                OnchainTrade.wallet.in_([w.wallet for w in smart_wallets]),
            )
        )
        sm_buy_count = int(sm_buys.scalar() or 0)
        if sm_buy_count >= 2:
            signals.append(OnchainSignal(
                chain=chain,
                token_address=token_address,
                signal_type="SMART_MONEY_ACCUMULATION",
                severity="warning",
                title="Smart Money Accumulation",
                description=(
                    f"{sm_buy_count} smart money buys in the last hour "
                    f"from {len(smart_wallets)} tracked profitable wallets"
                ),
                metadata={"wallet_count": len(smart_wallets), "buy_count": sm_buy_count},
            ))

    # Liquidity changes
    liq_result = await db.execute(
        select(LiquidityEvent).where(
            LiquidityEvent.chain == chain,
            LiquidityEvent.token_address == token_address,
            LiquidityEvent.timestamp >= since,
            LiquidityEvent.timestamp <= until,
        )
    )
    liq_events = liq_result.scalars().all()
    adds = sum(e.usd_value for e in liq_events if e.event_type == "ADD")
    removes = sum(e.usd_value for e in liq_events if e.event_type == "REMOVE")

    if removes > adds * 1.5 and removes > 10_000:
        signals.append(OnchainSignal(
            chain=chain,
            token_address=token_address,
            signal_type="LIQUIDITY_REMOVAL",
            severity="critical",
            title="Liquidity Removal Alert",
            description=f"Liquidity removed ${removes:,.0f} vs added ${adds:,.0f} in selected period",
            usd_value=removes,
        ))
    elif adds > removes * 1.2 and adds > 10_000:
        pct = round((adds - removes) / max(removes, 1) * 100)
        signals.append(OnchainSignal(
            chain=chain,
            token_address=token_address,
            signal_type="LIQUIDITY_INCREASE",
            severity="info",
            title="Liquidity Increase",
            description=f"Liquidity increased ~{pct}% while net flow is ${volume['net_flow_usd']:,.0f}",
            usd_value=adds,
        ))

    # Holder growth
    holder = await compute_holder_growth(db, chain, token_address, days=7)
    if holder["holder_growth_pct"] > 10:
        signals.append(OnchainSignal(
            chain=chain,
            token_address=token_address,
            signal_type="HOLDER_GROWTH",
            severity="info",
            title="Holder Growth",
            description=f"Holder count grew {holder['holder_growth_pct']}% over 7 days",
            metadata=holder,
        ))

    # Large trades in selected window (read-only — no DB writes)
    whale_trades = await db.execute(
        select(OnchainTrade).where(
            OnchainTrade.chain == chain,
            OnchainTrade.token_address == token_address,
            OnchainTrade.timestamp >= since,
            OnchainTrade.timestamp <= until,
            OnchainTrade.usd_value >= settings.WHALE_THRESHOLD_USD,
        ).order_by(desc(OnchainTrade.timestamp)).limit(10)
    )
    for trade in whale_trades.scalars().all():
        event_type = "LARGE_BUY" if trade.side == "BUY" else "LARGE_SELL"
        signals.append(OnchainSignal(
            chain=chain,
            token_address=token_address,
            signal_type=event_type,
            severity="critical" if trade.usd_value >= settings.WHALE_THRESHOLD_USD * 2 else "warning",
            title=event_type.replace("_", " ").title(),
            description=(
                f"{'Whale buy' if trade.side == 'BUY' else 'Whale sell'} "
                f"${trade.usd_value:,.0f} on {trade.dex or 'DEX'}"
            ),
            usd_value=trade.usd_value,
            wallet=trade.wallet,
            created_at=trade.timestamp,
        ))

    return signals
