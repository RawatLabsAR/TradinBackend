"""Processed billing webhook events for idempotency."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_billing_event_provider_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, index=True)
    event_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=_now)
