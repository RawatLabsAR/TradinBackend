"""HTTP client with retry, rate limiting, and caching for on-chain collectors."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)

_session: Optional[aiohttp.ClientSession] = None
_rate_lock = asyncio.Lock()
_last_request_ts: dict[str, float] = {}


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=60, connect=15)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _rate_limit(source: str, min_interval_ms: int = 200) -> None:
    """Simple per-source rate limiter."""
    import time
    async with _rate_lock:
        now = time.monotonic()
        last = _last_request_ts.get(source, 0.0)
        wait = min_interval_ms / 1000.0 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts[source] = time.monotonic()


async def api_request(
    method: str,
    url: str,
    *,
    source: str,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    cache_key: Optional[str] = None,
    cache_ttl: int = 60,
    max_retries: int = 3,
    min_interval_ms: int = 200,
) -> dict[str, Any] | list[Any]:
    """Make an HTTP request with retry, rate limiting, and optional caching."""
    if cache_key:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    session = await get_session()
    last_error: Exception | None = None

    for attempt in range(max_retries):
        await _rate_limit(source, min_interval_ms)
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
            ) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "2"))
                    logger.warning(
                        "%s rate limited (429), retry in %ds (attempt %d)",
                        source, retry_after, attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status >= 500:
                    body = await resp.text()
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status, message=body[:200],
                    )

                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning(
                        "%s API error %d: %s", source, resp.status, body[:300],
                    )
                    return {"error": body, "status": resp.status}

                data = await resp.json(content_type=None)

                if cache_key:
                    cache.set(cache_key, data, cache_ttl)

                return data

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = exc
            backoff = 2 ** attempt
            logger.warning(
                "%s request failed (attempt %d/%d): %s — retry in %ds",
                source, attempt + 1, max_retries, exc, backoff,
            )
            await asyncio.sleep(backoff)

    logger.error("%s request exhausted retries: %s", source, last_error)
    return {"error": str(last_error), "status": 0}
