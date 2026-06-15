"""Shared on-chain type definitions — address-based token identity only."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Chain(str, Enum):
    ETHEREUM = "ethereum"
    BASE = "base"
    SOLANA = "solana"
    BSC = "bsc"
    ARBITRUM = "arbitrum"
    POLYGON = "polygon"
    AVALANCHE = "avalanche"


EVM_CHAINS = {Chain.ETHEREUM, Chain.BASE, Chain.BSC, Chain.ARBITRUM, Chain.POLYGON, Chain.AVALANCHE}
SUPPORTED_CHAINS = {Chain.ETHEREUM, Chain.BASE, Chain.SOLANA, Chain.BSC}


def normalize_address(chain: str, address: str) -> str:
    """Normalize token/wallet address for consistent storage."""
    addr = address.strip()
    if chain in {c.value for c in EVM_CHAINS}:
        return addr.lower()
    return addr


_EVM_ADDRESS = re.compile(r"^0x[a-f0-9]{40}$")
_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def validate_token_address(chain: str, address: str) -> str:
    """Return normalized address or raise ValueError for invalid input."""
    chain = chain.lower().strip()
    addr = normalize_address(chain, address.strip())
    if not addr:
        raise ValueError("Token address is required")

    if chain in {c.value for c in EVM_CHAINS}:
        if not _EVM_ADDRESS.fullmatch(addr):
            raise ValueError(
                f"Invalid {chain} contract address. Expected 0x followed by 40 hex characters."
            )
        return addr

    if chain == Chain.SOLANA.value:
        if not _SOLANA_ADDRESS.fullmatch(addr):
            raise ValueError(
                "Invalid Solana mint address. Expected a base58 address (32–44 characters)."
            )
        return addr

    raise ValueError(f"Unsupported chain '{chain}'")


class TokenRef(BaseModel):
    chain: Chain
    token_address: str

    @field_validator("token_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("token_address is required")
        return v

    def normalized(self) -> TokenRef:
        return TokenRef(
            chain=self.chain,
            token_address=normalize_address(self.chain.value, self.token_address),
        )


TradeSide = Literal["BUY", "SELL"]
LiquidityEventType = Literal["ADD", "REMOVE", "SWAP"]
WhaleEventType = Literal[
    "LARGE_BUY",
    "LARGE_SELL",
    "ACCUMULATION",
    "EXIT",
    "COORDINATED_ACTIVITY",
    "UNUSUAL_BEHAVIOR",
]


class NormalizedTrade(BaseModel):
    chain: str
    token_address: str
    wallet: str
    side: TradeSide
    amount: float
    usd_value: float
    timestamp: datetime
    dex: str = ""
    tx_hash: str = ""
    block_number: Optional[int] = None
    price_usd: Optional[float] = None
    raw_source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedLiquidityEvent(BaseModel):
    chain: str
    token_address: str
    pool_address: str = ""
    event_type: LiquidityEventType
    wallet: str = ""
    token_amount: float = 0.0
    usd_value: float = 0.0
    liquidity_usd: float = 0.0
    timestamp: datetime
    tx_hash: str = ""
    dex: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedOhlcv(BaseModel):
    chain: str
    token_address: str
    pool_address: str
    timeframe: str  # hour | day | minute
    aggregate: int = 1
    timestamp: datetime
    open_usd: float
    high_usd: float
    low_usd: float
    close_usd: float
    volume_usd: float
    raw_source: str = "geckoterminal"
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedHolderSnapshot(BaseModel):
    chain: str
    token_address: str
    holder_count: int
    top10_pct: float = 0.0
    top50_pct: float = 0.0
    snapshot_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedWalletActivity(BaseModel):
    chain: str
    wallet: str
    token_address: str
    side: TradeSide
    amount: float
    usd_value: float
    timestamp: datetime
    tx_hash: str = ""
    dex: str = ""


class OnchainSignal(BaseModel):
    chain: str
    token_address: str
    signal_type: str
    severity: str  # info | warning | critical
    title: str
    description: str
    usd_value: float = 0.0
    wallet: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
