"""Subscription persistence and tier sync helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PlanId, normalize_plan_id
from app.models.billing_event import BillingEvent
from app.models.subscription import Subscription
from app.models.user import User


async def get_or_create_subscription(db: AsyncSession, user: User) -> Subscription:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub:
        if not sub.plan_id:
            sub.plan_id = sub.tier or PlanId.FREE.value
        return sub
    sub = Subscription(
        user_id=user.id,
        plan_id=PlanId.FREE.value,
        tier=PlanId.FREE.value,
        status="active",
    )
    db.add(sub)
    await db.flush()
    return sub


async def record_billing_event(
    db: AsyncSession, provider: str, event_id: str, event_type: str
) -> bool:
    """Return True if event was already processed."""
    if not event_id:
        return False
    result = await db.execute(
        select(BillingEvent).where(
            BillingEvent.provider == provider,
            BillingEvent.event_id == event_id,
        )
    )
    if result.scalar_one_or_none():
        return True
    db.add(BillingEvent(provider=provider, event_id=event_id, event_type=event_type))
    await db.flush()
    return False


async def apply_subscription_state(
    db: AsyncSession,
    sub: Subscription,
    user: User,
    *,
    plan_id: str,
    status: str,
    current_period_end: datetime | None = None,
) -> None:
    normalized = normalize_plan_id(plan_id)
    active_statuses = {"active", "trialing"}
    downgrade_statuses = {"canceled", "unpaid", "past_due", "incomplete_expired", "halted"}

    if status in active_statuses:
        sub.plan_id = normalized.value
        sub.tier = normalized.value
        sub.status = status
        user.subscription_tier = normalized.value
    elif status in downgrade_statuses:
        sub.plan_id = PlanId.FREE.value
        sub.tier = PlanId.FREE.value
        sub.status = status
        user.subscription_tier = PlanId.FREE.value
    else:
        sub.status = status

    if current_period_end:
        sub.current_period_end = current_period_end
    sub.updated_at = datetime.now(timezone.utc)
    await db.flush()
