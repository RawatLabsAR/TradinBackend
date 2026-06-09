"""Expose on-chain metrics to Pine Script runtime."""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.onchain.services.onchain_service import onchain_service
from app.pinescript.runtime.context import SeriesValue

logger = logging.getLogger(__name__)

# Built-in on-chain metric names available in Pine scripts
ONCHAIN_METRICS = {
    "whale_buy_volume",
    "whale_sell_volume",
    "buy_volume_usd",
    "sell_volume_usd",
    "net_flow_usd",
    "smart_money_score",
    "holder_count",
    "holder_growth_pct",
    "liquidity_usd",
    "unique_wallets",
}


async def load_onchain_metrics_for_script(
    db: AsyncSession,
    chain: str,
    token_address: str,
    bar_count: int,
) -> dict[str, SeriesValue]:
    """
    Load on-chain metrics as constant series for Pine Script access.
    Metrics are broadcast as flat arrays (same value across all bars).
    """
    metrics_list = await onchain_service.get_metrics(db, chain, token_address, limit=1)
    if not metrics_list:
        return {}

    m = metrics_list[0]
    values = {
        "whale_buy_volume": m.whale_buy_volume_usd,
        "whale_sell_volume": m.whale_sell_volume_usd,
        "buy_volume_usd": m.buy_volume_usd,
        "sell_volume_usd": m.sell_volume_usd,
        "net_flow_usd": m.net_flow_usd,
        "smart_money_score": m.smart_money_score_avg,
        "holder_count": float(m.holder_count),
        "holder_growth_pct": m.holder_growth_pct,
        "liquidity_usd": m.liquidity_usd,
        "unique_wallets": float(m.unique_wallets),
    }

    result: dict[str, SeriesValue] = {}
    for name, val in values.items():
        arr = np.full(bar_count, float(val or 0), dtype=float)
        result[name] = SeriesValue(arr)

    return result


def inject_onchain_vars(ctx: Any, metrics: dict[str, SeriesValue]) -> None:
    """Inject on-chain metric series into execution context."""
    for name, series in metrics.items():
        ctx.set_var(name, series)
