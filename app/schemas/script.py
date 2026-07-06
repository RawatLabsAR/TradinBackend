"""
Pydantic schemas for the Pine Script DSL API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────── Script CRUD ─────────────────────────────────────

class ScriptCreate(BaseModel):
    name: str = Field(default="Untitled Script", max_length=255)
    description: Optional[str] = None
    source: str = Field(..., min_length=1)
    overlay: bool = True
    is_public: bool = False


class ScriptUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    source: Optional[str] = None
    overlay: Optional[bool] = None
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None


class ScriptResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    source: str
    language: str
    is_active: bool
    is_public: bool
    strategy_name: Optional[str]
    indicators_used: Optional[list[str]]
    overlay: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScriptListResponse(BaseModel):
    scripts: list[ScriptResponse]
    total: int
    page: int
    page_size: int


# ─────────────────────────── Validation ──────────────────────────────────────

class ValidateRequest(BaseModel):
    source: str = Field(..., min_length=1)


class CompilerErrorSchema(BaseModel):
    line: int
    col: int
    message: str
    severity: str = "error"
    source: str = "parser"


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[CompilerErrorSchema] = []
    warnings: list[CompilerErrorSchema] = []
    strategy_name: Optional[str] = None
    indicators_used: list[str] = []


# ─────────────────────────── Execution / Run ─────────────────────────────────

class RunRequest(BaseModel):
    source: str
    timeframe: str = "1D"
    limit: int = Field(default=300, ge=10, le=2000)
    initial_capital: float = Field(default=10_000.0, ge=100.0)
    fee_pct: float = Field(default=0, ge=0.0, le=0.1)
    broadcast_telegram: bool = True


class SignalSchema(BaseModel):
    bar_index: int
    timestamp: str
    signal_type: str
    label: str
    price: float
    direction: str
    metadata: dict[str, Any] = {}


class RunResponse(BaseModel):
    success: bool
    strategy_name: str
    symbol: str
    timeframe: str
    signals: list[SignalSchema] = []
    indicator_overlays: dict[str, list[Optional[float]]] = {}
    bars_executed: int
    execution_ms: float
    errors: list[str] = []


# ─────────────────────────── Backtest ────────────────────────────────────────

class BacktestRequest(BaseModel):
    source: str
    timeframe: str = "1D"
    limit: int = Field(default=500, ge=30, le=2000)
    initial_capital: float = Field(default=10_000.0, ge=100.0)
    fee_pct: float = Field(default=0, ge=0.0, le=0.1)


class TradeSchema(BaseModel):
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    label: str
    pnl_pct: float
    entry_timestamp: str = ""
    exit_timestamp: str = ""


class BacktestResponse(BaseModel):
    success: bool
    strategy_name: str
    symbol: str
    timeframe: str

    initial_capital: float
    final_capital: float
    net_profit_pct: float
    gross_profit_pct: float
    gross_loss_pct: float

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_consecutive_wins: int
    max_consecutive_losses: int

    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    trades: list[TradeSchema] = []
    signals: list[SignalSchema] = []
    indicator_overlays: dict[str, list[Optional[float]]] = {}
    equity_curve: list[float] = []

    bars_tested: int
    execution_ms: float
    errors: list[str] = []


class SignalListResponse(BaseModel):
    signals: list[SignalSchema]
