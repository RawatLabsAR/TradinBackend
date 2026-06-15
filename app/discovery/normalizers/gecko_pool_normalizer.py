"""Normalize GeckoTerminal pool responses into DiscoveryToken."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.discovery.types import DiscoveryToken
from app.token_search.types import normalize_chain, normalize_contract

SUPPORTED_NETWORKS = {
    "eth": "ethereum",
    "base": "base",
    "bsc": "bsc",
    "solana": "solana",
    "arbitrum": "arbitrum",
    "arb": "arbitrum",
    "polygon_pos": "polygon",
    "polygon": "polygon",
}

NETWORK_TO_GECKO = {
    "ethereum": "eth",
    "base": "base",
    "bsc": "bsc",
    "solana": "solana",
    "arbitrum": "arbitrum",
    "polygon": "polygon_pos",
}


def _network_from_pool(pool: dict, included: list[dict] | None = None) -> str:
    pool_id = str(pool.get("id") or "")
    if "_" in pool_id:
        return pool_id.split("_", 1)[0]

    rel = pool.get("relationships") or {}
    net_ref = (rel.get("network") or {}).get("data") or {}
    net_id = str(net_ref.get("id") or "")
    if net_id:
        return net_id

    if included:
        for item in included:
            if item.get("type") == "network":
                return str(item.get("id") or "")
    return ""


def _safe_float(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_age_hours(created_at: Optional[str]) -> float:
    if not created_at:
        return 0.0
    try:
        ts = created_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 0.0


def _token_lookup(included: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in included or []:
        if item.get("type") == "token":
            lookup[str(item.get("id") or "")] = item.get("attributes") or {}
    return lookup


def normalize_gecko_pool(
    pool: dict,
    *,
    network: str,
    included: list[dict] | None = None,
    category: str = "new_dex",
) -> Optional[DiscoveryToken]:
    if not pool:
        return None

    chain = SUPPORTED_NETWORKS.get(network.lower())
    if not chain:
        return None

    attrs = pool.get("attributes") or {}
    rel = pool.get("relationships") or {}
    token_lookup = _token_lookup(included or [])

    base_ref = (rel.get("base_token") or {}).get("data") or {}
    base_id = str(base_ref.get("id") or "")
    base_attrs = token_lookup.get(base_id, {})

    address = str(base_attrs.get("address") or "")
    if not address:
        return None

    address = normalize_contract(chain, address)
    created_at = str(attrs.get("pool_created_at") or "")
    age_hours = _parse_age_hours(created_at)

    volume = _safe_float((attrs.get("volume_usd") or {}).get("h24"))
    liquidity = _safe_float(attrs.get("reserve_in_usd"))
    price = _safe_float(attrs.get("token_price_usd"))
    mc = _safe_float(attrs.get("market_cap_usd") or attrs.get("fdv_usd"))
    price_change = _safe_float((attrs.get("price_change_percentage") or {}).get("h24"))

    txns = (attrs.get("transactions") or {}).get("h24") or {}
    buys = int(txns.get("buys") or 0)
    sells = int(txns.get("sells") or 0)
    tx_count = buys + sells
    buy_sell_ratio = buys / sells if sells > 0 else (float(buys) if buys else 0.0)

    dex_data = (rel.get("dex") or {}).get("data") or {}
    dex_id = str(dex_data.get("id") or "").replace("-", " ")

    return DiscoveryToken(
        token_name=str(base_attrs.get("name") or attrs.get("name") or ""),
        symbol=str(base_attrs.get("symbol") or "").upper(),
        chain=chain,
        contract_address=address,
        logo_url=str(base_attrs.get("image_url") or ""),
        market_cap=mc,
        liquidity=liquidity,
        volume_24h=volume,
        price_usd=price,
        price_change_24h=price_change,
        verified=False,
        dex=dex_id,
        pair_address=str(attrs.get("address") or ""),
        source="geckoterminal",
        discovery_category=category,
        age_hours=age_hours,
        pool_created_at=created_at or None,
        buy_sell_ratio=round(buy_sell_ratio, 2),
        tx_count_24h=tx_count,
        source_type="dex",
        metadata={
            "pool_id": pool.get("id"),
            "network": network,
        },
    )
