"""Trade normalization — all collectors output NormalizedTrade."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.onchain.types import NormalizedTrade, normalize_address


def _parse_timestamp(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(float(ts))
    if isinstance(ts, str):
        cleaned = ts.strip().replace(" UTC", "Z").replace(" ", "T")
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(ts.replace(" UTC", "").strip(), fmt)
            except ValueError:
                continue
    return datetime.utcnow()


def _hex_addr(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    text = str(value).strip()
    if text.startswith("0x"):
        return text.lower()
    return text.lower()


def _side_from_amounts(bought_addr: str, sold_addr: str, target: str) -> str:
    target = target.lower()
    if bought_addr.lower() == target:
        return "BUY"
    if sold_addr.lower() == target:
        return "SELL"
    return "BUY"


def normalize_dune_trade(
    row: dict,
    chain: str,
    target_token: str = "",
) -> Optional[NormalizedTrade]:
    token_bought = _hex_addr(row.get("token_bought_address"))
    token_sold = _hex_addr(row.get("token_sold_address"))
    target = normalize_address(chain, target_token or token_bought or token_sold)
    if not target:
        return None

    side = _side_from_amounts(token_bought, token_sold, target)
    amount = float(
        row.get("token_bought_amount") if side == "BUY"
        else row.get("token_sold_amount") or 0
    )
    usd_value = float(row.get("amount_usd") or row.get("usd_value") or 0)
    wallet = _hex_addr(row.get("wallet") or row.get("taker") or row.get("trader"))
    ts = row.get("block_time") or row.get("timestamp")
    timestamp = _parse_timestamp(ts)

    return NormalizedTrade(
        chain=chain,
        token_address=target,
        wallet=normalize_address(chain, wallet),
        side=side,  # type: ignore[arg-type]
        amount=amount,
        usd_value=usd_value,
        timestamp=timestamp,
        dex=str(row.get("dex") or row.get("project") or ""),
        tx_hash=str(row.get("tx_hash") or row.get("transaction_hash") or ""),
        block_number=int(row["block_number"]) if row.get("block_number") else None,
        raw_source="dune",
    )
