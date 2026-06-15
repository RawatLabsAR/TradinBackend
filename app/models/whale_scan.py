"""Whale scanner cron job — candidate registry and run history."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WhaleScanCandidate(Base):
    __tablename__ = "whale_scan_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chain = Column(String(32), nullable=False)
    contract_address = Column(String(128), nullable=False)
    symbol = Column(String(32), nullable=True)
    token_name = Column(String(128), nullable=True)
    source = Column(String(64), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_scanned_at = Column(DateTime(timezone=True), nullable=True)
    liquidity_usd = Column(Float, nullable=False, default=0.0)
    volume_24h = Column(Float, nullable=False, default=0.0)
    age_hours = Column(Float, nullable=False, default=0.0)
    dex = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("chain", "contract_address", name="uq_whale_scan_candidate"),
        Index("ix_whale_scan_candidate_scan", "last_scanned_at"),
    )


class WhaleScanRun(Base):
    __tablename__ = "whale_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    candidates_found = Column(Integer, nullable=False, default=0)
    tokens_scanned = Column(Integer, nullable=False, default=0)
    whales_detected = Column(Integer, nullable=False, default=0)
    messages_sent = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="running")
    error = Column(Text, nullable=True)


class WhaleScanNotification(Base):
    __tablename__ = "whale_scan_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("whale_scan_runs.id", ondelete="SET NULL"), nullable=True)
    candidate_id = Column(
        Integer,
        ForeignKey("whale_scan_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(32), nullable=False, default="digest")
    usd_value = Column(Float, nullable=False, default=0.0)
    telegram_message_id = Column(Integer, nullable=True)
    notified_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_whale_scan_notify_candidate", "candidate_id", "notified_at"),
    )
