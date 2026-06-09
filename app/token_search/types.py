"""Unified token discovery types — internal identity is chain + contract_address."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class NormalizedToken(BaseModel):
    token_name: str
    symbol: str
    chain: str
    contract_address: str
    logo_url: str = ""
    market_cap: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0
    price_usd: float = 0.0
    verified: bool = False
    dex: str = ""
    pair_address: str = ""
    price_change_24h: float = 0.0
    holder_count: int = 0
    source: str = ""
    rank_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def identity_key(self) -> str:
        return f"{self.chain}:{self.contract_address.lower()}"


class TokenSearchResult(BaseModel):
    query: str
    total: int
    items: list[NormalizedToken]
    sources_used: list[str] = Field(default_factory=list)
    cached: bool = False
    took_ms: float = 0.0


class TrendingTokenEntry(BaseModel):
    token_name: str
    symbol: str
    chain: str
    contract_address: str
    logo_url: str = ""
    volume_24h: float = 0.0
    liquidity: float = 0.0
    market_cap: float = 0.0
    search_count: int = 0
    trend_score: float = 0.0
    dex: str = ""
    verified: bool = False


# Chain ID normalization map (provider-specific → internal)
CHAIN_ALIASES: dict[str, str] = {
    "eth": "ethereum",
    "ethereum": "ethereum",
    "base": "base",
    "sol": "solana",
    "solana": "solana",
    "bsc": "bsc",
    "bnb": "bsc",
    "binance-smart-chain": "bsc",
    "arbitrum": "arbitrum",
    "polygon": "polygon",
    "matic": "polygon",
    "avalanche": "avalanche",
    "avax": "avalanche",
}


def normalize_chain(raw: str) -> str:
    key = (raw or "").lower().strip()
    return CHAIN_ALIASES.get(key, key)


def normalize_contract(chain: str, address: str) -> str:
    addr = (address or "").strip()
    if chain in {"ethereum", "base", "bsc", "arbitrum", "polygon", "avalanche"}:
        return addr.lower()
    return addr
