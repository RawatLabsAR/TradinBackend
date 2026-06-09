"""Price alert model — one-shot threshold notifications."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String(32), nullable=False, index=True)
    target_price = Column(Float, nullable=False)
    direction = Column(String(8), nullable=False, default="above")
    # direction: "above" | "below"
    message = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notify_telegram = Column(Boolean, nullable=False, default=False)
    channel_id = Column(Integer, ForeignKey("telegram_channels.id"), nullable=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_price_alerts_product_active", "product_id", "is_active"),
    )
