"""
FastAPI routes for the Pine Script DSL engine.

All script execution is sandboxed — no eval/exec of Python code.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.script import (
    Script, ScriptVersion, StrategyRun, SignalHistory,
    BacktestResult as BacktestResultModel,
)
from app.schemas.script import (
    ScriptCreate, ScriptUpdate, ScriptResponse,
    ScriptListResponse,
    ValidateRequest, ValidateResponse, CompilerErrorSchema,
    RunRequest, RunResponse, SignalSchema, SignalListResponse,
    BacktestRequest, BacktestResponse, TradeSchema,
)
from app.schemas.candle import TIMEFRAME_CONFIG
from app.pinescript.validators.syntax_validator import validate
from app.pinescript.executor.strategy_executor import execute_script
from app.pinescript.backtesting.backtest_runner import run_backtest
from app.services.market_service import get_candles
from app.broadcast.services.signal_broadcast_service import broadcast_strategy_signal
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scripts", tags=["scripts"])


# ─────────────────────────── CRUD ────────────────────────────────────────────

@router.get("/", response_model=ScriptListResponse)
async def list_scripts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    total_q = await db.execute(select(func.count(Script.id)).where(Script.is_active == True))
    total = total_q.scalar() or 0

    result = await db.execute(
        select(Script)
        .where(Script.is_active == True)
        .order_by(Script.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    scripts = result.scalars().all()

    return ScriptListResponse(
        scripts=[ScriptResponse.model_validate(s) for s in scripts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=ScriptResponse, status_code=201)
async def create_script(
    payload: ScriptCreate,
    db: AsyncSession = Depends(get_db),
):
    # Validate before storing
    vr = validate(payload.source)
    script = Script(
        name=payload.name,
        description=payload.description,
        source=payload.source,
        is_public=payload.is_public,
        overlay=payload.overlay,
        strategy_name=vr.strategy_name,
        indicators_used=vr.indicators_used,
    )
    db.add(script)
    await db.flush()

    # Store initial version
    version = ScriptVersion(script_id=script.id, version=1, source=payload.source)
    db.add(version)
    await db.commit()
    await db.refresh(script)
    return ScriptResponse.model_validate(script)


@router.get("/{script_id}", response_model=ScriptResponse)
async def get_script(script_id: int, db: AsyncSession = Depends(get_db)):
    script = await _get_or_404(db, script_id)
    return ScriptResponse.model_validate(script)


@router.put("/{script_id}", response_model=ScriptResponse)
async def update_script(
    script_id: int,
    payload: ScriptUpdate,
    db: AsyncSession = Depends(get_db),
):
    script = await _get_or_404(db, script_id)
    updates = payload.model_dump(exclude_none=True)

    if "source" in updates:
        vr = validate(updates["source"])
        updates["strategy_name"] = vr.strategy_name
        updates["indicators_used"] = vr.indicators_used

        # Store new version
        vers_q = await db.execute(
            select(func.max(ScriptVersion.version)).where(
                ScriptVersion.script_id == script_id
            )
        )
        max_v = vers_q.scalar() or 0
        new_v = ScriptVersion(
            script_id=script_id,
            version=max_v + 1,
            source=updates["source"],
        )
        db.add(new_v)

    for k, v in updates.items():
        setattr(script, k, v)

    await db.commit()
    await db.refresh(script)
    return ScriptResponse.model_validate(script)


@router.delete("/{script_id}", status_code=204)
async def delete_script(script_id: int, db: AsyncSession = Depends(get_db)):
    script = await _get_or_404(db, script_id)
    script.is_active = False
    await db.commit()


# ─────────────────────────── Validation ──────────────────────────────────────

@router.post("/validate", response_model=ValidateResponse)
async def validate_source(payload: ValidateRequest):
    """
    Validate Pine Script DSL source without executing it.
    Safe to call frequently from the editor.
    """
    vr = validate(payload.source)
    return ValidateResponse(
        valid=vr.valid,
        errors=[_err_schema(e) for e in vr.errors],
        warnings=[_err_schema(w) for w in vr.warnings],
        strategy_name=vr.strategy_name,
        indicators_used=vr.indicators_used,
    )


# ─────────────────────────── Execution ───────────────────────────────────────

@router.post("/run/{symbol}", response_model=RunResponse)
async def run_script(
    symbol: str,
    payload: RunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute a Pine Script DSL script against historical candles for `symbol`."""
    return await _execute_run(symbol, payload, db, script_id=None)


@router.post("/{script_id}/run/{symbol}", response_model=RunResponse)
async def run_saved_script(
    script_id: int,
    symbol: str,
    payload: RunRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _execute_run(symbol, payload, db, script_id=script_id)


# ─────────────────────────── Backtesting ─────────────────────────────────────

@router.post("/backtest/{symbol}", response_model=BacktestResponse)
async def backtest_script(
    symbol: str,
    payload: BacktestRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _execute_backtest(symbol, payload, db, script_id=None)


@router.post("/{script_id}/backtest/{symbol}", response_model=BacktestResponse)
async def backtest_saved_script(
    script_id: int,
    symbol: str,
    payload: BacktestRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _execute_backtest(symbol, payload, db, script_id=script_id)


# ─────────────────────────── Signals ─────────────────────────────────────────

@router.get("/{script_id}/signals/{symbol}", response_model=SignalListResponse)
async def get_signals(
    script_id: int,
    symbol: str,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the most recent signals generated for a script+symbol pair."""
    result = await db.execute(
        select(SignalHistory)
        .join(StrategyRun, SignalHistory.run_id == StrategyRun.id)
        .where(StrategyRun.script_id == script_id, StrategyRun.symbol == symbol)
        .order_by(SignalHistory.id.desc())
        .limit(limit)
    )
    sigs = result.scalars().all()
    return SignalListResponse(signals=[_db_sig_to_schema(s) for s in sigs])


# ─────────────────────────── Helpers ─────────────────────────────────────────

async def _get_or_404(db: AsyncSession, script_id: int) -> Script:
    result = await db.execute(
        select(Script).where(Script.id == script_id, Script.is_active == True)
    )
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(status_code=404, detail=f"Script {script_id} not found")
    return script


async def _resolve_source(
    payload: RunRequest | BacktestRequest,
    db: AsyncSession,
    script_id: int | None = None,
) -> str:
    if script_id is None:
        return payload.source
    script = await _get_or_404(db, script_id)
    return payload.source or script.source


async def _execute_run(
    symbol: str,
    payload: RunRequest,
    db: AsyncSession,
    script_id: int | None,
) -> RunResponse:
    source = await _resolve_source(payload, db, script_id)
    candles = await _fetch_candles(symbol, payload.timeframe, payload.limit)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candle data for {symbol}")

    result = await execute_script(
        source=source,
        candles=candles,
        symbol=symbol,
        initial_capital=payload.initial_capital,
        fee_pct=payload.fee_pct,
    )

    await _persist_run(
        db=db,
        script_id=script_id,
        symbol=symbol,
        timeframe=payload.timeframe,
        run_type="historical",
        bars=result.bars_executed,
        exec_ms=result.execution_ms,
        capital=payload.initial_capital,
        fee=payload.fee_pct,
        error=result.errors[0] if result.errors else None,
        signals=result.signals,
    )

    if result.success and payload.broadcast_telegram:
        await _maybe_broadcast_run_signals(
            db=db,
            symbol=symbol,
            timeframe=payload.timeframe,
            strategy_name=result.strategy_name,
            signals=result.signals,
            script_id=script_id,
        )

    return RunResponse(
        success=result.success,
        strategy_name=result.strategy_name,
        symbol=symbol,
        timeframe=payload.timeframe,
        signals=[_sig_schema(s) for s in result.signals],
        indicator_overlays=result.indicator_overlays,
        bars_executed=result.bars_executed,
        execution_ms=result.execution_ms,
        errors=result.errors,
    )


async def _execute_backtest(
    symbol: str,
    payload: BacktestRequest,
    db: AsyncSession,
    script_id: int | None,
) -> BacktestResponse:
    source = await _resolve_source(payload, db, script_id)
    candles = await _fetch_candles(symbol, payload.timeframe, payload.limit)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candle data for {symbol}")

    result = await run_backtest(
        source=source,
        candles=candles,
        symbol=symbol,
        timeframe=payload.timeframe,
        initial_capital=payload.initial_capital,
        fee_pct=payload.fee_pct,
    )

    if result.success and script_id is not None:
        run = await _persist_run(
            db=db, script_id=script_id, symbol=symbol,
            timeframe=payload.timeframe, run_type="backtest",
            bars=result.bars_tested, exec_ms=result.execution_ms,
            capital=payload.initial_capital, fee=payload.fee_pct,
            error=None, signals=result.signals,
        )
        bt = BacktestResultModel(
            run_id=run.id,
            initial_capital=result.initial_capital,
            final_capital=result.final_capital,
            net_profit_pct=result.net_profit_pct,
            gross_profit_pct=result.gross_profit_pct,
            gross_loss_pct=result.gross_loss_pct,
            total_trades=result.total_trades,
            winning_trades=result.winning_trades,
            losing_trades=result.losing_trades,
            win_rate_pct=result.win_rate_pct,
            avg_win_pct=result.avg_win_pct,
            avg_loss_pct=result.avg_loss_pct,
            profit_factor=result.profit_factor,
            max_consecutive_wins=result.max_consecutive_wins,
            max_consecutive_losses=result.max_consecutive_losses,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            sortino_ratio=result.sortino_ratio,
            calmar_ratio=result.calmar_ratio,
            trades_json=result.trades,
            equity_curve_json=result.equity_curve,
        )
        db.add(bt)
        await db.commit()

    return _backtest_response(result, symbol)


async def _fetch_candles(symbol: str, timeframe: str, limit: int) -> list[dict]:
    # Map timeframe to a supported one; default to 1D
    tf = timeframe if timeframe in TIMEFRAME_CONFIG else "1D"
    try:
        candles = await get_candles(symbol, tf)
        # Candles are dicts with string values — our executor handles conversion
        return candles[:limit] if limit else candles
    except Exception as exc:
        logger.warning("Could not fetch candles for %s: %s", symbol, exc)
        return []


async def _persist_run(
    db: AsyncSession,
    script_id: Optional[int],
    symbol: str,
    timeframe: str,
    run_type: str,
    bars: int,
    exec_ms: float,
    capital: float,
    fee: float,
    error: Optional[str],
    signals: list[dict],
) -> StrategyRun:
    now = datetime.now(timezone.utc)
    run = StrategyRun(
        script_id=script_id,
        symbol=symbol,
        timeframe=timeframe,
        run_type=run_type,
        status="completed" if not error else "failed",
        bars_tested=bars,
        execution_ms=exec_ms,
        initial_capital=capital,
        fee_pct=fee,
        error_message=error,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    await db.flush()

    for sig in signals[:500]:   # cap stored signals per run
        ts_raw = sig.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else None
        except (ValueError, AttributeError):
            ts = None
        sh = SignalHistory(
            run_id=run.id,
            bar_index=sig.get("bar_index", 0),
            timestamp=ts,
            signal_type=sig.get("signal_type", ""),
            label=sig.get("label", ""),
            price=sig.get("price", 0.0),
            direction=sig.get("direction", ""),
            metadata_=sig.get("metadata", {}),
        )
        db.add(sh)

    await db.commit()
    return run


def _map_broadcast_signal_type(sig: dict) -> Optional[str]:
    """Map Pine executor signal → Telegram BUY/SELL/EXIT."""
    stype = str(sig.get("signal_type", "")).lower()
    direction = str(sig.get("direction", "")).lower()
    if stype in ("exit", "close"):
        return "EXIT"
    if direction == "buy":
        return "BUY"
    if direction == "sell":
        return "SELL"
    return None


async def _maybe_broadcast_run_signals(
    db: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    strategy_name: str,
    signals: list[dict],
    script_id: Optional[int] = None,
) -> None:
    """Broadcast actionable signals on the latest bar to Telegram."""
    if not signals or not strategy_name:
        return

    max_bar = max(s.get("bar_index", 0) for s in signals)
    latest = [s for s in signals if s.get("bar_index") == max_bar]

    for sig in latest:
        signal_type = _map_broadcast_signal_type(sig)
        if not signal_type:
            continue

        await broadcast_strategy_signal(
            db=db,
            symbol=symbol.upper(),
            signal_type=signal_type,
            strategy_name=strategy_name,
            timeframe=timeframe,
            price=sig.get("price"),
            reason=sig.get("label") or None,
            script_id=script_id,
        )

        await ws_manager.broadcast_signal(
            symbol.upper(),
            {
                "symbol": symbol.upper(),
                "signal_type": signal_type,
                "strategy": strategy_name,
                "timeframe": timeframe,
                "price": sig.get("price"),
                "label": sig.get("label", ""),
                "direction": sig.get("direction", ""),
                "bar_index": sig.get("bar_index", 0),
                "script_id": script_id,
            },
        )


def _err_schema(e) -> CompilerErrorSchema:
    return CompilerErrorSchema(
        line=e.line, col=e.col,
        message=e.message, severity=e.severity, source=e.source,
    )


def _sig_schema(s: dict) -> SignalSchema:
    return SignalSchema(
        bar_index=s["bar_index"],
        timestamp=s["timestamp"],
        signal_type=s["signal_type"],
        label=s["label"],
        price=s["price"],
        direction=s["direction"],
        metadata=s.get("metadata", {}),
    )


def _db_sig_to_schema(s: SignalHistory) -> SignalSchema:
    return SignalSchema(
        bar_index=s.bar_index,
        timestamp=s.timestamp.isoformat() if s.timestamp else "",
        signal_type=s.signal_type,
        label=s.label,
        price=s.price,
        direction=s.direction,
        metadata=s.metadata_ or {},
    )


def _backtest_response(result, symbol: str) -> BacktestResponse:
    return BacktestResponse(
        success=result.success,
        strategy_name=result.strategy_name,
        symbol=symbol,
        timeframe=result.timeframe,
        initial_capital=result.initial_capital,
        final_capital=result.final_capital,
        net_profit_pct=result.net_profit_pct,
        gross_profit_pct=result.gross_profit_pct,
        gross_loss_pct=result.gross_loss_pct,
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate_pct=result.win_rate_pct,
        avg_win_pct=result.avg_win_pct,
        avg_loss_pct=result.avg_loss_pct,
        profit_factor=result.profit_factor,
        max_consecutive_wins=result.max_consecutive_wins,
        max_consecutive_losses=result.max_consecutive_losses,
        max_drawdown_pct=result.max_drawdown_pct,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio,
        calmar_ratio=result.calmar_ratio,
        trades=[TradeSchema(**t) if isinstance(t, dict) else TradeSchema(**t.__dict__) for t in result.trades],
        signals=[_sig_schema(s) if isinstance(s, dict) else _sig_schema(s.__dict__) for s in result.signals],
        indicator_overlays=result.indicator_overlays,
        equity_curve=result.equity_curve,
        bars_tested=result.bars_tested,
        execution_ms=result.execution_ms,
        errors=result.errors,
    )
