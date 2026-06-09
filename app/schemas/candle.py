from pydantic import BaseModel
from typing import Literal


TIMEFRAME_CONFIG: dict[str, dict] = {
    "1m": {
        "granularity": "ONE_MINUTE",
        "gate_interval": "1m",
        "interval_seconds": 60,
        "default_bars": 300,
    },
    "5m": {
        "granularity": "FIVE_MINUTE",
        "gate_interval": "5m",
        "interval_seconds": 300,
        "default_bars": 300,
    },
    "15m": {
        "granularity": "FIFTEEN_MINUTE",
        "gate_interval": "15m",
        "interval_seconds": 900,
        "default_bars": 300,
    },
    "1H": {
        "granularity": "ONE_HOUR",
        "gate_interval": "1h",
        "interval_seconds": 3600,
        "default_bars": 300,
    },
    "4H": {
        "granularity": "FOUR_HOUR",
        "gate_interval": "4h",
        "interval_seconds": 14400,
        "default_bars": 300,
    },
    "1D": {
        "granularity": "ONE_DAY",
        "gate_interval": "1d",
        "interval_seconds": 86400,
        "default_bars": 365,
    },
    "1W": {
        "granularity": "ONE_WEEK",
        "gate_interval": "1w",
        "interval_seconds": 604800,
        "default_bars": 104,
    },
    "1M": {
        "granularity": "ONE_MONTH",
        "gate_interval": "1M",
        "interval_seconds": 2592000,
        "default_bars": 60,
    },
}

# Gate.io interval strings matching each timeframe key
GATE_GRANULARITY_MAP: dict[str, str] = {
    tf: cfg["gate_interval"] for tf, cfg in TIMEFRAME_CONFIG.items()
}

# Coinbase does not support every bar interval natively
COINBASE_GRANULARITY_MAP: dict[str, str] = {
    "FOUR_HOUR": "ONE_HOUR",
    "ONE_WEEK": "ONE_DAY",
    "ONE_MONTH": "ONE_DAY",
}

TimeframeType = Literal["1m", "5m", "15m", "1H", "4H", "1D", "1W", "1M"]


class CandleSchema(BaseModel):
    start: str
    low: str
    high: str
    open: str
    close: str
    volume: str

    model_config = {"from_attributes": True}


class CandleResponse(BaseModel):
    product_id: str
    timeframe: str
    granularity: str
    candles: list[CandleSchema]
    count: int


class TimeframeEntry(BaseModel):
    granularity: str
    interval_seconds: int
    default_bars: int


class TimeframeConfigResponse(BaseModel):
    timeframes: dict[str, TimeframeEntry]
