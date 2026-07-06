"""
High-level strategy executor.

Converts raw candle data into numpy arrays, compiles the script,
runs the execution loop bar-by-bar, and returns structured results.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.pinescript.parser.parser_engine import parse
from app.pinescript.runtime.context import ExecutionContext, Signal
from app.pinescript.runtime.runtime_engine import RuntimeEngine, RuntimeError
from app.pinescript.sandbox.sandbox_runtime import (
    sandboxed_run,
    check_source_limits,
    check_bar_limits,
    SandboxViolation,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    strategy_name: str
    signals: list[dict] = field(default_factory=list)
    indicator_overlays: dict[str, list[float]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    bars_executed: int = 0
    execution_ms: float = 0.0


async def execute_script(
    source: str,
    candles: list[dict],
    symbol: str = "UNKNOWN",
    initial_capital: float = 10_000.0,
    fee_pct: float = 0,
    onchain_chain: str | None = None,
    onchain_token_address: str | None = None,
) -> ExecutionResult:
    """
    Run a Pine Script DSL script against candle data.

    `candles` is a list of dicts with keys:
        start (ISO str), open, high, low, close, volume (numeric)

    Returns an ExecutionResult with signals and indicator overlays.
    """
    import time
    t0 = time.monotonic()

    try:
        check_source_limits(source)
        check_bar_limits(len(candles))
    except SandboxViolation as exc:
        return ExecutionResult(success=False, strategy_name="", errors=[str(exc)])

    # Build numpy arrays
    try:
        candle_data, timestamps = _candles_to_arrays(candles)
    except Exception as exc:
        return ExecutionResult(success=False, strategy_name="", errors=[f"Data error: {exc}"])

    # Parse
    try:
        ast = parse(source)
    except Exception as exc:
        return ExecutionResult(success=False, strategy_name="", errors=[f"Parse error: {exc}"])

    # Execute inside sandbox
    try:
        result = await sandboxed_run(
            _run_loop(
                ast, candle_data, timestamps, initial_capital, fee_pct,
                onchain_chain=onchain_chain,
                onchain_token_address=onchain_token_address,
            ),
        )
    except SandboxViolation as exc:
        return ExecutionResult(success=False, strategy_name="", errors=[str(exc)])
    except RuntimeError as exc:
        return ExecutionResult(
            success=False,
            strategy_name="",
            errors=[f"Runtime error at line {exc.line}: {exc}"],
        )
    except Exception as exc:
        logger.exception("Unexpected execution error")
        return ExecutionResult(success=False, strategy_name="", errors=[f"Execution error: {exc}"])

    elapsed = (time.monotonic() - t0) * 1000
    result.execution_ms = round(elapsed, 2)
    return result


async def _run_loop(
    ast,
    candle_data: dict[str, np.ndarray],
    timestamps: list[str],
    initial_capital: float,
    fee_pct: float,
    onchain_chain: str | None = None,
    onchain_token_address: str | None = None,
) -> ExecutionResult:
    """The actual bar-by-bar execution loop."""
    ctx = ExecutionContext(
        candle_data=candle_data,
        timestamps=timestamps,
        initial_capital=initial_capital,
        fee_pct=fee_pct,
    )

    # Inject on-chain metrics if configured
    if onchain_chain and onchain_token_address:
        try:
            from app.db.database import AsyncSessionLocal
            from app.onchain.services.pine_metrics import (
                load_onchain_metrics_for_script,
                inject_onchain_vars,
            )
            async with AsyncSessionLocal() as db:
                metrics = await load_onchain_metrics_for_script(
                    db, onchain_chain, onchain_token_address, len(timestamps),
                )
                inject_onchain_vars(ctx, metrics)
        except Exception as exc:
            logger.debug("On-chain metrics injection skipped: %s", exc)

    engine = RuntimeEngine()
    n = len(timestamps)
    all_signals: list[dict] = []

    for i in range(n):
        ctx.set_bar(i)
        engine.run(ast, ctx)
        ctx.strategy.check_bar_exits(
            float(candle_data["high"][i]),
            float(candle_data["low"][i]),
            float(candle_data["close"][i]),
            i,
            timestamps[i] if i < len(timestamps) else "",
        )
        for sig in ctx.strategy.flush_signals():
            all_signals.append(_signal_to_dict(sig))

        # Yield control periodically so we don't block the event loop
        if i % 500 == 0:
            await asyncio.sleep(0)

    # Collect cached indicator overlays + plot() overlays
    overlays: dict[str, list[float]] = {}
    for key, sv in ctx._indicator_cache.items():
        arr = sv.array()
        overlays[key] = [
            None if math.isnan(v) else round(float(v), 8)
            for v in arr
        ]
    for title, sv in ctx.plot_overlays.items():
        arr = sv.array()
        overlays[title] = [
            None if math.isnan(v) else round(float(v), 8)
            for v in arr
        ]

    return ExecutionResult(
        success=True,
        strategy_name=ctx.strategy_name,
        signals=all_signals,
        indicator_overlays=overlays,
        bars_executed=n,
    )


def _candles_to_arrays(
    candles: list[dict],
) -> tuple[dict[str, np.ndarray], list[str]]:
    opens, highs, lows, closes, volumes, timestamps = [], [], [], [], [], []
    for c in candles:
        opens.append(float(c.get("open", 0) or 0))
        highs.append(float(c.get("high", 0) or 0))
        lows.append(float(c.get("low", 0) or 0))
        closes.append(float(c.get("close", 0) or 0))
        volumes.append(float(c.get("volume", 0) or 0))
        timestamps.append(str(c.get("start", "")))

    return {
        "open": np.array(opens, dtype=float),
        "high": np.array(highs, dtype=float),
        "low": np.array(lows, dtype=float),
        "close": np.array(closes, dtype=float),
        "volume": np.array(volumes, dtype=float),
    }, timestamps


def _signal_to_dict(sig: Signal) -> dict:
    return {
        "bar_index": sig.bar_index,
        "timestamp": sig.timestamp,
        "signal_type": sig.signal_type,
        "label": sig.label,
        "price": sig.price,
        "direction": sig.direction,
        "metadata": sig.metadata,
    }
