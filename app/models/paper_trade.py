"""Simulated paper trades per user."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(32), nullable=False, index=True)
    side = Column(String(8), nullable=False)  # long | short
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    fee_pct = Column(Float, nullable=False, default=0.001)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    source = Column(String(32), nullable=True)  # manual | coin_detail | strategy
    order_type = Column(String(16), nullable=False, default="market")  # market | limit
    limit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    script_id = Column(Integer, nullable=True)
    is_pending = Column(Integer, nullable=False, default=0)  # 1 = unfilled limit order
    opened_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_paper_trades_user_open", "user_id", "closed_at"),
    )
