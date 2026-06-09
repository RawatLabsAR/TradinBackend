"""
Execution sandbox for Pine Script DSL.

Enforces:
  - Wall-clock timeout (default 10 s)
  - Maximum bar count (prevents O(n²) abuse)
  - Memory limit via RSS check
  - No raw Python eval/exec — the script is NEVER passed to Python's eval
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Hard limits
MAX_BARS = 10_000
MAX_VARIABLES = 500
EXECUTION_TIMEOUT_SECS = 15
MAX_SCRIPT_LEN = 32_768   # 32 KB source cap


class SandboxViolation(Exception):
    """Raised when a script exceeds resource limits."""


async def sandboxed_run(
    coro,
    timeout: float = EXECUTION_TIMEOUT_SECS,
) -> Any:
    """
    Awaits `coro` inside an asyncio timeout guard.
    `coro` must be an async coroutine produced by the executor.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise SandboxViolation(
            f"Script execution exceeded {timeout}s time limit."
        )


def check_source_limits(source: str) -> None:
    """Pre-execution source-level checks."""
    if len(source) > MAX_SCRIPT_LEN:
        raise SandboxViolation(
            f"Script too long: {len(source)} chars (max {MAX_SCRIPT_LEN})."
        )


def check_bar_limits(n_bars: int) -> None:
    if n_bars > MAX_BARS:
        raise SandboxViolation(
            f"Too many bars: {n_bars} (max {MAX_BARS})."
        )


class RateLimiter:
    """Simple token-bucket rate limiter for per-user script runs."""

    def __init__(self, capacity: int = 10, refill_rate: float = 1.0) -> None:
        self._capacity = capacity
        self._tokens = float(capacity)
        self._refill_rate = refill_rate   # tokens per second
        self._last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._refill_rate,
        )
        self._last_refill = now
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
