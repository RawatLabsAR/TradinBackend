"""Persisted discovery scan results — survives restarts on Supabase."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, UniqueConstraint

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DiscoverySnapshot(Base):
    __tablename__ = "discovery_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(32), nullable=False)
    chain = Column(String(32), nullable=False, default="")
    payload = Column(JSON, nullable=False)
    sources_used = Column(JSON, nullable=False, default=list)
    scanned_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("category", "chain", name="uq_discovery_category_chain"),
        Index("ix_discovery_scanned", "scanned_at"),
    )
