"""Search query normalization — pair symbols, slashes, etc."""

from __future__ import annotations

import re

_PAIR_SPLIT_RE = re.compile(r"[/\-_]")


def normalize_search_query(query: str) -> str:
    """
    Normalize user input for token search.
    Examples: TROLL/USD -> TROLL, pepe-usdt -> PEPE, bonk_usdc -> BONK
    """
    q = query.strip()
    if not q:
        return q

    if _PAIR_SPLIT_RE.search(q):
        base = _PAIR_SPLIT_RE.split(q, maxsplit=1)[0].strip()
        if base:
            return base

    return q
