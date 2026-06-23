"""Subscription records for Stripe and Razorpay."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Legacy Stripe columns (kept for backward compatibility)
    stripe_customer_id = Column(String(128), nullable=True, index=True)
    stripe_subscription_id = Column(String(128), nullable=True, unique=True)

    # Provider-agnostic billing fields
    payment_provider = Column(String(32), nullable=True)  # stripe | razorpay
    provider_customer_id = Column(String(128), nullable=True, index=True)
    provider_subscription_id = Column(String(128), nullable=True, unique=True)
    plan_id = Column(String(32), nullable=False, default="free")  # free | starter | pro
    tier = Column(String(32), nullable=False, default="free")  # mirrors plan_id for legacy code
    billing_interval = Column(String(16), nullable=False, default="month")
    currency = Column(String(8), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
