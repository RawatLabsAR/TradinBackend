"""Shared discovery parsing and filtering helpers."""

from __future__ import annotations

from typing import Any, Optional

from app.discovery.types import DiscoveryResult, DiscoveryToken


def chain_key(chain: Optional[str]) -> str:
    return (chain or "").strip().lower()


def filter_tokens_by_chain(
    tokens: list[DiscoveryToken],
    chain: Optional[str],
) -> list[DiscoveryToken]:
    if not chain:
        return tokens
    chain_lower = chain.strip().lower()
    return [t for t in tokens if t.chain == chain_lower or t.source_type == "cex"]


def discovery_result_from_payload(
    data: dict[str, Any],
    *,
    category: str = "",
    chain: Optional[str] = None,
    cached: bool = True,
) -> DiscoveryResult:
    items = [DiscoveryToken.model_validate(t) for t in data.get("items", [])]
    if chain:
        items = filter_tokens_by_chain(items, chain)
    return DiscoveryResult(
        category=category or data.get("category", ""),
        items=items,
        sources_used=data.get("sources_used", []),
        scanned_at=data.get("scanned_at", ""),
        cached=cached,
    )
