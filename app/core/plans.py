"""Subscription plan catalog — single source of truth for tiers and features."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from app.core.config import settings

PaymentProvider = Literal["stripe", "razorpay"]


class PlanId(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"


PAID_PLANS = {PlanId.STARTER, PlanId.PRO}
TIER_ORDER = {PlanId.FREE: 0, PlanId.STARTER: 1, PlanId.PRO: 2}


PLAN_FEATURES: dict[PlanId, list[str]] = {
    PlanId.FREE: [
        "All research tabs",
        "Paper trading",
        "Live WebSocket charts",
        f"{settings.QUOTA_AI_INSIGHTS_FREE} AI insights / day",
        f"{settings.QUOTA_SCRIPT_RUN_FREE} script runs / day",
        f"{settings.QUOTA_SCRIPT_BACKTEST_FREE} backtests / day",
    ],
    PlanId.STARTER: [
        "Everything in Free",
        f"{settings.QUOTA_AI_INSIGHTS_STARTER} AI insights / day",
        f"{settings.QUOTA_SCRIPT_RUN_STARTER} script runs / day",
        f"{settings.QUOTA_SCRIPT_BACKTEST_STARTER} backtests / day",
        "Up to 25 watchlist items",
        "Up to 5 price alerts",
    ],
    PlanId.PRO: [
        "Everything in Starter",
        f"{settings.QUOTA_AI_INSIGHTS_PRO} AI insights / day",
        f"{settings.QUOTA_SCRIPT_RUN_PRO} script runs / day",
        f"{settings.QUOTA_SCRIPT_BACKTEST_PRO} backtests / day",
        "Up to 100 watchlist items",
        "Unlimited price alerts",
        "Priority AI processing",
    ],
}


def plan_rank(plan_id: str) -> int:
    try:
        return TIER_ORDER[PlanId(plan_id)]
    except ValueError:
        return 0


def normalize_plan_id(value: str | None) -> PlanId:
    try:
        return PlanId(value or PlanId.FREE.value)
    except ValueError:
        return PlanId.FREE


def display_price(plan_id: PlanId, currency: str) -> int:
    if plan_id == PlanId.FREE:
        return 0
    if currency == "inr":
        if plan_id == PlanId.STARTER:
            return settings.PLAN_STARTER_INR
        return settings.PLAN_PRO_INR
    if plan_id == PlanId.STARTER:
        return settings.PLAN_STARTER_USD
    return settings.PLAN_PRO_USD


def currency_for_country(country_code: str | None) -> str:
    if (country_code or "").upper() == "IN":
        return "inr"
    return "usd"


def resolve_payment_provider(country_code: str | None) -> PaymentProvider:
    if (country_code or "").upper() == "IN":
        return "razorpay"
    return "stripe"


def stripe_price_id(plan_id: PlanId) -> str:
    if plan_id == PlanId.STARTER:
        return settings.STRIPE_PRICE_ID_STARTER
    if plan_id == PlanId.PRO:
        return settings.STRIPE_PRICE_ID_PRO
    return ""


def razorpay_plan_id(plan_id: PlanId) -> str:
    if plan_id == PlanId.STARTER:
        return settings.RAZORPAY_PLAN_ID_STARTER
    if plan_id == PlanId.PRO:
        return settings.RAZORPAY_PLAN_ID_PRO
    return ""


def stripe_enabled() -> bool:
    return bool(settings.STRIPE_SECRET_KEY and (
        settings.STRIPE_PRICE_ID_STARTER or settings.STRIPE_PRICE_ID_PRO
    ))


def razorpay_enabled() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET and (
        settings.RAZORPAY_PLAN_ID_STARTER or settings.RAZORPAY_PLAN_ID_PRO
    ))


def provider_plan_configured(provider: PaymentProvider, plan_id: PlanId) -> bool:
    if plan_id == PlanId.FREE:
        return True
    if provider == "stripe":
        return bool(stripe_price_id(plan_id))
    return bool(razorpay_plan_id(plan_id))


def billing_configured() -> bool:
    return stripe_enabled() or razorpay_enabled()


def upgrade_message_for_tier(tier: str) -> str:
    current = normalize_plan_id(tier)
    if current == PlanId.FREE:
        return "Upgrade to Starter or Pro for higher limits."
    if current == PlanId.STARTER:
        return "Upgrade to Pro for higher limits."
    return "Daily limit reached."
