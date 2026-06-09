"""SQLAlchemy models for on-chain analytics tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class OnchainTrade(Base):
    __tablename__ = "onchain_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY | SELL
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    usd_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    dex: Mapped[str] = mapped_column(String(64), default="")
    tx_hash: Mapped[str] = mapped_column(String(128), default="")
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_source: Mapped[str] = mapped_column(String(32), default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "chain", "tx_hash", "token_address", "wallet", "side",
            name="uq_onchain_trade_dedup",
        ),
        Index("idx_trades_token_time", "chain", "token_address", "timestamp"),
        Index("idx_trades_wallet_time", "chain", "wallet", "timestamp"),
        Index("idx_trades_usd_value", "usd_value"),
        Index("idx_trades_side", "chain", "token_address", "side"),
    )


class OnchainOhlcv(Base):
    __tablename__ = "onchain_ohlcv_candles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    pool_address: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    aggregate: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open_usd: Mapped[float] = mapped_column(Float, default=0.0)
    high_usd: Mapped[float] = mapped_column(Float, default=0.0)
    low_usd: Mapped[float] = mapped_column(Float, default=0.0)
    close_usd: Mapped[float] = mapped_column(Float, default=0.0)
    volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    raw_source: Mapped[str] = mapped_column(String(32), default="geckoterminal")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "chain", "token_address", "pool_address", "timeframe", "aggregate", "timestamp",
            name="uq_onchain_ohlcv_candle",
        ),
        Index("idx_ohlcv_token_time", "chain", "token_address", "timestamp"),
        Index("idx_ohlcv_pool_time", "chain", "pool_address", "timestamp"),
    )


class WalletStat(Base):
    __tablename__ = "wallet_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    buy_count: Mapped[int] = mapped_column(Integer, default=0)
    sell_count: Mapped[int] = mapped_column(Integer, default=0)
    total_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_roi_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trade_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    smart_money_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_whale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_smart_money: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sniper: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chain", "wallet", name="uq_wallet_stats"),
        Index("idx_wallet_stats_score", "smart_money_score"),
        Index("idx_wallet_stats_whale", "is_whale"),
        Index("idx_wallet_stats_smart", "is_smart_money"),
    )


class HolderSnapshot(Base):
    __tablename__ = "holder_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    holder_count: Mapped[int] = mapped_column(Integer, default=0)
    top10_pct: Mapped[float] = mapped_column(Float, default=0.0)
    top50_pct: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_holder_snap_token_time", "chain", "token_address", "snapshot_at"),
    )


class LiquidityEvent(Base):
    __tablename__ = "liquidity_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    pool_address: Mapped[str] = mapped_column(String(128), default="")
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ADD | REMOVE | SWAP
    wallet: Mapped[str] = mapped_column(String(128), default="")
    token_amount: Mapped[float] = mapped_column(Float, default=0.0)
    usd_value: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity_usd: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(128), default="")
    dex: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chain", "tx_hash", "token_address", "event_type", name="uq_liq_event"),
        Index("idx_liq_token_time", "chain", "token_address", "timestamp"),
        Index("idx_liq_event_type", "event_type"),
    )


class WhaleWallet(Base):
    __tablename__ = "whale_wallets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), default="")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    usd_value: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    tx_hash: Mapped[str] = mapped_column(String(128), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_whale_token_time", "chain", "token_address", "detected_at"),
        Index("idx_whale_wallet", "chain", "wallet"),
    )


class SmartMoneyWallet(Base):
    __tablename__ = "smart_money_wallets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_roi_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trade_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    total_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    last_trade_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chain", "wallet", "token_address", name="uq_smart_money"),
        Index("idx_smart_money_score", "score"),
        Index("idx_smart_money_token", "chain", "token_address"),
    )


class TokenMetric(Base):
    __tablename__ = "token_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    buy_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    sell_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    net_flow_usd: Mapped[float] = mapped_column(Float, default=0.0)
    unique_wallets: Mapped[int] = mapped_column(Integer, default=0)
    unique_buyers: Mapped[int] = mapped_column(Integer, default=0)
    unique_sellers: Mapped[int] = mapped_column(Integer, default=0)
    whale_buy_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    whale_sell_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    smart_money_score_avg: Mapped[float] = mapped_column(Float, default=0.0)
    holder_count: Mapped[int] = mapped_column(Integer, default=0)
    holder_growth_pct: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity_usd: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity_change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    early_buyer_count: Mapped[int] = mapped_column(Integer, default=0)
    sniper_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_token_metrics_token_period", "chain", "token_address", "period_end"),
    )


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # dune | dexscreener
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)  # trades | liquidity | holders
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_cursor: Mapped[str] = mapped_column(String(256), default="")
    records_synced: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle | running | error
    error_message: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "chain", "token_address", "source", "sync_type",
            name="uq_sync_checkpoint",
        ),
        Index("idx_sync_checkpoint_status", "status"),
    )
