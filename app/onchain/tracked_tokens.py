"""Curated tokens for on-chain analytics."""

from __future__ import annotations

from fastapi import HTTPException

from app.onchain.types import normalize_address

TRACKED_TOKENS: list[dict[str, str]] = [
    {
        "id": "troll",
        "name": "Troll",
        "symbol": "TROLL",
        "chain": "solana",
        "token_address": "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
    },
    {
        "id": "rave",
        "name": "Rave",
        "symbol": "RAVE",
        "chain": "ethereum",
        "token_address": "0x17205fab260a7a6383a81452cE6315A39370Db97",
    },
    {
        "id": "labusdt",
        "name": "Labusdt",
        "symbol": "LABUSDT",
        "chain": "bsc",
        "token_address": "0x7ec43Cf65F1663F820427C62A5780b8f2E25593A",
    },
    {
        "id": "pippinusdt",
        "name": "Pippinusdt",
        "symbol": "PIPPINUSDT",
        "chain": "solana",
        "token_address": "Dfh5DzRgSvvCFDoYc2ciTkMrbDfRKybA4SoFbPmApump",
    },
    {
        "id": "power",
        "name": "Power",
        "symbol": "POWER",
        "chain": "ethereum",
        "token_address": "0x9dC44ae5BE187ECA9e2A67e33f27A4c91cEA1223",
    },
]


def get_tracked_tokens() -> list[dict[str, str]]:
    return [
        {"chain": t["chain"], "token_address": t["token_address"]}
        for t in TRACKED_TOKENS
    ]


def find_tracked_token(chain: str, address: str) -> dict[str, str] | None:
    chain = chain.lower()
    normalized = normalize_address(chain, address)
    for token in TRACKED_TOKENS:
        if token["chain"] == chain and normalize_address(chain, token["token_address"]) == normalized:
            return token
    return None


def is_tracked_token(chain: str, address: str) -> bool:
    return find_tracked_token(chain, address) is not None


def require_tracked_token(chain: str, address: str) -> dict[str, str]:
    token = find_tracked_token(chain, address)
    if token is None:
        raise HTTPException(
            status_code=400,
            detail="On-chain analysis is limited to the curated token list.",
        )
    return token
