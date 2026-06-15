"""Shared HTTP client for free public API providers (no API keys)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Tradin/1.0 (crypto-analytics; free-tier)",
}


async def fetch_json(
    url: str,
    params: dict | None = None,
    timeout_sec: int = 15,
    retries: int = 2,
) -> Any:
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))

    logger.warning("Free API fetch failed %s: %s", url, last_exc)
    raise last_exc or RuntimeError(f"Failed to fetch {url}")
