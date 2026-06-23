"""Billing orchestration — provider selection, tier sync, usage."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import (
    PAID_PLANS,
    PlanId,
    billing_configured,
    currency_for_country,
    display_price,
    normalize_plan_id,
    provider_plan_configured,
    razorpay_enabled,
    resolve_payment_provider,
    stripe_enabled,
    PLAN_FEATURES,
)
from app.core.quotas import QUOTA_KEYS, _get_or_create_quota, _tier_limit
from app.models.user import User
from app.services.billing.providers.razorpay_provider import RazorpayProvider
from app.services.billing.providers.stripe_provider import StripeProvider
from app.services.billing.subscription_sync import get_or_create_subscription

_stripe = StripeProvider()
_razorpay = RazorpayProvider()


def get_provider(name: str):
    if name == "razorpay":
        return _razorpay
    return _stripe


async def create_checkout(
    db: AsyncSession,
    user: User,
    plan_id: PlanId,
    provider_name: str,
) -> str:
    if plan_id not in PAID_PLANS:
        raise ValueError("Cannot checkout for free plan")
    provider = get_provider(provider_name)
    if not provider.is_configured() or not provider.plan_available(plan_id):
        raise RuntimeError(f"{provider_name} not configured for {plan_id.value}")
    return await provider.create_checkout(db, user, plan_id)


async def create_portal(db: AsyncSession, user: User) -> str | None:
    sub = await get_or_create_subscription(db, user)
    provider_name = sub.payment_provider or "stripe"
    provider = get_provider(provider_name)
    if not provider.is_configured():
        return None
    return await provider.create_portal(db, user)


def build_plans_response(country_code: str | None) -> dict:
    currency = currency_for_country(country_code)
    provider = resolve_payment_provider(country_code)
    plans = []
    for plan_id in PlanId:
        price = display_price(plan_id, currency)
        available = plan_id == PlanId.FREE or provider_plan_configured(provider, plan_id)
        plans.append(
            {
                "id": plan_id.value,
                "name": plan_id.value.capitalize(),
                "price": price,
                "currency": currency,
                "interval": "month",
                "features": PLAN_FEATURES[plan_id],
                "available": available,
            }
        )
    return {
        "plans": plans,
        "currency": currency,
        "provider": provider,
        "billing_configured": billing_configured(),
        "stripe_enabled": stripe_enabled(),
        "razorpay_enabled": razorpay_enabled(),
    }


async def get_usage_summary(db: AsyncSession, user: User) -> dict:
    today = datetime.now(timezone.utc).date()
    usage = {}
    for quota_key in QUOTA_KEYS:
        limit = _tier_limit(user, quota_key)
        row = await _get_or_create_quota(db, user.id, quota_key, today)
        usage[quota_key] = {
            "used": row.count,
            "limit": limit,
            "remaining": max(0, limit - row.count),
        }
    tier = normalize_plan_id(user.subscription_tier).value
    next_tier = None
    if tier == PlanId.FREE.value:
        next_tier = PlanId.STARTER.value
    elif tier == PlanId.STARTER.value:
        next_tier = PlanId.PRO.value
    return {"tier": tier, "next_tier": next_tier, "quotas": usage}

