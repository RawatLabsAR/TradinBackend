"""Curated tokens for on-chain analytics."""

from __future__ import annotations

import json

from fastapi import HTTPException

from app.core.config import settings
from app.onchain.types import normalize_address

_DEFAULT_TRACKED: list[dict[str, str]] = [
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


def _parse_env_tokens(raw: str) -> list[dict[str, str]]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [t for t in parsed if isinstance(t, dict) and t.get("token_address")]
    except json.JSONDecodeError:
        pass
    tokens = []
    for part in raw.split(";"):
        part = part.strip()
        if ":" not in part:
            continue
        chain, addr = part.split(":", 1)
        tokens.append({
            "id": addr[:8],
            "name": addr[:8],
            "symbol": addr[:6].upper(),
            "chain": chain.strip().lower(),
            "token_address": addr.strip(),
        })
    return tokens


def _load_tracked_tokens() -> list[dict[str, str]]:
    env_tokens = _parse_env_tokens(settings.ONCHAIN_TRACKED_TOKENS)
    return env_tokens if env_tokens else _DEFAULT_TRACKED


TRACKED_TOKENS: list[dict[str, str]] = _load_tracked_tokens()


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
            status_code=403,
            detail={
                "code": "not_tracked",
                "message": "This token is not in the curated on-chain list. Use /analyze for live data or POST /sync after adding to ONCHAIN_TRACKED_TOKENS.",
            },
        )
    return token
