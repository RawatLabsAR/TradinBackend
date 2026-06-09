"""SQLAlchemy models for token discovery."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class TokenRegistry(Base):
    """Canonical registry of discovered tokens (identity = chain + contract_address)."""

    __tablename__ = "token_registry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    token_name: Mapped[str] = mapped_column(String(128), default="")
    symbol: Mapped[str] = mapped_column(String(32), default="")
    logo_url: Mapped[str] = mapped_column(String(512), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_dex: Mapped[str] = mapped_column(String(64), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("chain", "contract_address", name="uq_token_registry"),
        Index("idx_token_registry_symbol", "symbol"),
        Index("idx_token_registry_name", "token_name"),
        Index("idx_token_registry_search_count", "search_count"),
    )


class TokenSearchCache(Base):
    """Cached search query results."""

    __tablename__ = "token_search_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_normalized: Mapped[str] = mapped_column(String(128), nullable=False)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_used: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_search_cache_query", "query_normalized"),
        Index("idx_search_cache_expires", "expires_at"),
    )


class TokenMetadata(Base):
    """Extended metadata snapshot per token."""

    __tablename__ = "token_metadata"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h: Mapped[float] = mapped_column(Float, default=0.0)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    price_change_24h: Mapped[float] = mapped_column(Float, default=0.0)
    holder_count: Mapped[int] = mapped_column(Integer, default=0)
    dex: Mapped[str] = mapped_column(String(64), default="")
    pair_address: Mapped[str] = mapped_column(String(128), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_token_metadata_identity", "chain", "contract_address"),
        Index("idx_token_metadata_expires", "expires_at"),
    )


class TrendingToken(Base):
    """Trending tokens ranked by search + volume signals."""

    __tablename__ = "trending_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    token_name: Mapped[str] = mapped_column(String(128), default="")
    symbol: Mapped[str] = mapped_column(String(32), default="")
    logo_url: Mapped[str] = mapped_column(String(512), default="")
    volume_24h: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    trend_score: Mapped[float] = mapped_column(Float, default=0.0)
    dex: Mapped[str] = mapped_column(String(64), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    rank_position: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_trending_score", "trend_score"),
        Index("idx_trending_computed", "computed_at"),
    )


class SearchHistory(Base):
    """Anonymous search history (session-based)."""

    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), default="")
    query: Mapped[str] = mapped_column(String(128), nullable=False)
    selected_chain: Mapped[str] = mapped_column(String(32), default="")
    selected_address: Mapped[str] = mapped_column(String(128), default="")
    selected_symbol: Mapped[str] = mapped_column(String(32), default="")
    searched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_search_history_session", "session_id", "searched_at"),
        Index("idx_search_history_query", "query"),
    )
