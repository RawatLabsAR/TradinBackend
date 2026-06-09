"""Liquidity event normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.onchain.types import NormalizedLiquidityEvent, normalize_address


def normalize_dune_liquidity(
    row: dict,
    chain: str,
    token_address: str,
) -> Optional[NormalizedLiquidityEvent]:
    evt_type = str(row.get("evt_type") or row.get("event_type") or "").upper()
    if "ADD" in evt_type or evt_type == "MINT":
        event_type = "ADD"
    elif "REMOVE" in evt_type or evt_type == "BURN":
        event_type = "REMOVE"
    else:
        event_type = "ADD"

    ts = row.get("block_time") or row.get("timestamp")
    if isinstance(ts, str):
        timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    else:
        timestamp = datetime.utcnow()

    return NormalizedLiquidityEvent(
        chain=chain,
        token_address=normalize_address(chain, token_address),
        pool_address=str(row.get("pool_address") or row.get("contract_address") or ""),
        event_type=event_type,  # type: ignore[arg-type]
        usd_value=float(row.get("amount_usd") or 0),
        liquidity_usd=float(row.get("liquidity_usd") or row.get("amount_usd") or 0),
        timestamp=timestamp,
        tx_hash=str(row.get("tx_hash") or ""),
        dex=str(row.get("dex") or row.get("project") or ""),
        metadata={"source": "dune"},
    )
