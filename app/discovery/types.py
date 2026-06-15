"""Discovery types — extends token search with growth scoring."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field

from app.token_search.types import NormalizedToken

DiscoveryCategory = Literal["new_dex", "new_cex", "surging", "trending"]
SourceType = Literal["dex", "cex"]
RiskLevel = Literal["low", "medium", "high"]


class DiscoveryToken(NormalizedToken):
    growth_score: float = 0.0
    discovery_category: str = ""
    age_hours: float = 0.0
    volume_change_pct: float = 0.0
    source_type: str = "dex"
    product_id: str = ""
    risk_level: str = "high"
    pool_created_at: Optional[str] = None
    buy_sell_ratio: float = 0.0
    tx_count_24h: int = 0
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class DiscoveryResult:
    """Discovery scan result — cached in memory and optionally persisted to Postgres."""

    def __init__(
        self,
        *,
        category: str,
        items: list[DiscoveryToken],
        sources_used: list[str],
        scanned_at: str,
        cached: bool = False,
    ) -> None:
        self.category = category
        self.items = items
        self.sources_used = sources_used
        self.scanned_at = scanned_at
        self.cached = cached

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "items": [t.model_dump() for t in self.items],
            "sources_used": self.sources_used,
            "scanned_at": self.scanned_at,
            "cached": self.cached,
            "total": len(self.items),
        }
