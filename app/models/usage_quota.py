"""Per-user daily usage counters for costly API operations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UsageQuota(Base):
    __tablename__ = "usage_quotas"
    __table_args__ = (
        UniqueConstraint("user_id", "quota_key", "usage_date", name="uq_usage_user_key_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    quota_key = Column(String(64), nullable=False)
    usage_date = Column(Date, nullable=False, default=date.today)
    count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
