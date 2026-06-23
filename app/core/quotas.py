"""Per-user daily usage quotas for costly operations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PlanId, normalize_plan_id
from app.db.database import get_db
from app.models.usage_quota import UsageQuota
from app.models.user import User
from app.core.plans import upgrade_message_for_tier

QUOTA_KEYS = {
    "ai_insight": (
        "QUOTA_AI_INSIGHTS_FREE",
        "QUOTA_AI_INSIGHTS_STARTER",
        "QUOTA_AI_INSIGHTS_PRO",
    ),
    "script_run": (
        "QUOTA_SCRIPT_RUN_FREE",
        "QUOTA_SCRIPT_RUN_STARTER",
        "QUOTA_SCRIPT_RUN_PRO",
    ),
    "script_backtest": (
        "QUOTA_SCRIPT_BACKTEST_FREE",
        "QUOTA_SCRIPT_BACKTEST_STARTER",
        "QUOTA_SCRIPT_BACKTEST_PRO",
    ),
}


def _tier_limit(user: User, quota_key: str) -> int:
    if user.role == "admin":
        return getattr(settings, QUOTA_KEYS[quota_key][2])

    tier = normalize_plan_id(user.subscription_tier)
    if tier == PlanId.PRO:
        return getattr(settings, QUOTA_KEYS[quota_key][2])
    if tier == PlanId.STARTER:
        return getattr(settings, QUOTA_KEYS[quota_key][1])
    return getattr(settings, QUOTA_KEYS[quota_key][0])


async def _get_or_create_quota(
    db: AsyncSession, user_id: int, quota_key: str, usage_date: date
) -> UsageQuota:
    result = await db.execute(
        select(UsageQuota).where(
            UsageQuota.user_id == user_id,
            UsageQuota.quota_key == quota_key,
            UsageQuota.usage_date == usage_date,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return row
    row = UsageQuota(user_id=user_id, quota_key=quota_key, usage_date=usage_date, count=0)
    db.add(row)
    await db.flush()
    return row


async def check_and_increment_quota(
    db: AsyncSession,
    user: User,
    quota_key: str,
) -> None:
    if user.role == "admin":
        return

    if quota_key not in QUOTA_KEYS:
        raise ValueError(f"Unknown quota key: {quota_key}")

    limit = _tier_limit(user, quota_key)
    today = datetime.now(timezone.utc).date()
    row = await _get_or_create_quota(db, user.id, quota_key, today)

    if row.count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily {quota_key.replace('_', ' ')} limit reached ({limit}/day). "
            f"{upgrade_message_for_tier(user.subscription_tier or 'free')}",
        )

    row.count += 1
    row.updated_at = datetime.now(timezone.utc)


def require_quota(quota_key: str):
    async def _dependency(
        user: User,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await check_and_increment_quota(db, user, quota_key)
        return user

    return _dependency
