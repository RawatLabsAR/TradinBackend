"""Per-user portfolio holdings — synced via PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(32), nullable=False)
    quantity = Column(Float, nullable=False)
    avg_cost = Column(Float, nullable=False)
    added_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_portfolio_user_product"),
        Index("ix_portfolio_user", "user_id"),
    )
