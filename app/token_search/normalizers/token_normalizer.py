"""Normalize provider responses into unified NormalizedToken schema."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.token_search.types import NormalizedToken, normalize_chain, normalize_contract

logger = logging.getLogger(__name__)

SUPPORTED_CHAINS = {
    "ethereum", "base", "solana", "bsc", "arbitrum", "polygon", "avalanche",
}


def _safe_float(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_dexscreener_pair(pair: dict) -> Optional[NormalizedToken]:
    if not pair:
        return None

    chain = normalize_chain(str(pair.get("chainId") or ""))
    if chain not in SUPPORTED_CHAINS:
        return None

    base = pair.get("baseToken") or {}
    address = str(base.get("address") or "")
    if not address:
        return None

    address = normalize_contract(chain, address)
    liquidity = _safe_float((pair.get("liquidity") or {}).get("usd"))
    volume = _safe_float((pair.get("volume") or {}).get("h24"))
    mc = _safe_float(pair.get("marketCap") or pair.get("fdv"))
    price = _safe_float(pair.get("priceUsd"))

    # Low liquidity scam filter hint (ranking handles final sort)
    info = pair.get("info") or {}

    return NormalizedToken(
        token_name=str(base.get("name") or ""),
        symbol=str(base.get("symbol") or "").upper(),
        chain=chain,
        contract_address=address,
        logo_url=str(info.get("imageUrl") or ""),
        market_cap=mc,
        liquidity=liquidity,
        volume_24h=volume,
        price_usd=price,
        verified=bool(pair.get("labels") and "verified" in str(pair.get("labels")).lower()),
        dex=str(pair.get("dexId") or ""),
        pair_address=str(pair.get("pairAddress") or ""),
        price_change_24h=_safe_float((pair.get("priceChange") or {}).get("h24")),
        source="dexscreener",
        metadata={
            "url": pair.get("url"),
            "quote_token": (pair.get("quoteToken") or {}).get("symbol"),
        },
    )


def normalize_coingecko_coin(coin: dict) -> list[NormalizedToken]:
    """Expand CoinGecko coin into per-chain contract entries."""
    results: list[NormalizedToken] = []
    if not coin:
        return results

    name = str(coin.get("name") or "")
    symbol = str(coin.get("symbol") or "").upper()
    image = str((coin.get("image") or {}).get("small") or coin.get("image") or "")
    mc = _safe_float((coin.get("market_data") or {}).get("market_cap", {}).get("usd"))
    volume = _safe_float((coin.get("market_data") or {}).get("total_volume", {}).get("usd"))
    price = _safe_float((coin.get("market_data") or {}).get("current_price", {}).get("usd"))
    change = _safe_float((coin.get("market_data") or {}).get("price_change_percentage_24h"))

    platform_map = {
        "ethereum": "ethereum",
        "base": "base",
        "solana": "solana",
        "binance-smart-chain": "bsc",
        "arbitrum-one": "arbitrum",
        "polygon-pos": "polygon",
        "avalanche": "avalanche",
    }

    platforms = coin.get("platforms") or coin.get("detail_platforms") or {}
    if isinstance(platforms, dict):
        for platform, address in platforms.items():
            if not address:
                continue
            chain = platform_map.get(platform, normalize_chain(platform))
            if chain not in SUPPORTED_CHAINS:
                continue
            results.append(NormalizedToken(
                token_name=name,
                symbol=symbol,
                chain=chain,
                contract_address=normalize_contract(chain, str(address)),
                logo_url=image,
                market_cap=mc,
                volume_24h=volume,
                price_usd=price,
                price_change_24h=change,
                verified=True,
                source="coingecko",
                metadata={"coingecko_id": coin.get("id")},
            ))

    return results
