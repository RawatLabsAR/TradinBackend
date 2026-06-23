"""Stripe subscription billing provider."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PlanId, stripe_enabled, stripe_price_id
from app.models.billing_event import BillingEvent
from app.models.subscription import Subscription
from app.models.user import User
from app.services.billing.subscription_sync import (
    apply_subscription_state,
    get_or_create_subscription,
    record_billing_event,
)

logger = logging.getLogger(__name__)


class StripeProvider:
    name = "stripe"

    def is_configured(self) -> bool:
        return stripe_enabled()

    def plan_available(self, plan_id: PlanId) -> bool:
        return bool(stripe_price_id(plan_id))

    def _configure(self) -> None:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def create_checkout(self, db: AsyncSession, user: User, plan_id: PlanId) -> str:
        if not self.is_configured():
            raise RuntimeError("Stripe is not configured")
        price_id = stripe_price_id(plan_id)
        if not price_id:
            raise RuntimeError(f"Stripe price not configured for {plan_id.value}")

        self._configure()
        sub = await get_or_create_subscription(db, user)

        customer_id = sub.provider_customer_id or sub.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"user_id": str(user.id), "username": user.username},
            )
            customer_id = customer.id
            sub.provider_customer_id = customer_id
            sub.stripe_customer_id = customer_id
            sub.payment_provider = self.name
            await db.flush()

        success_url = settings.STRIPE_SUCCESS_URL or f"{settings.FRONTEND_URL.rstrip('/')}/account?billing=success"
        cancel_url = settings.STRIPE_CANCEL_URL or f"{settings.FRONTEND_URL.rstrip('/')}/account?billing=cancel"

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(user.id), "plan_id": plan_id.value},
            subscription_data={"metadata": {"user_id": str(user.id), "plan_id": plan_id.value}},
        )
        return session.url

    async def create_portal(self, db: AsyncSession, user: User) -> str | None:
        if not self.is_configured():
            return None
        sub = await get_or_create_subscription(db, user)
        customer_id = sub.provider_customer_id or sub.stripe_customer_id
        if not customer_id:
            return None
        self._configure()
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.FRONTEND_URL.rstrip('/')}/account",
        )
        return session.url

    async def handle_webhook(self, db: AsyncSession, payload: bytes, signature: str) -> None:
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise RuntimeError("Stripe webhook secret not configured")

        self._configure()
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
        event_id = event.get("id", "")
        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {})

        if await record_billing_event(db, self.name, event_id, event_type):
            return

        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(db, data)
        elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
            await _handle_subscription_updated(db, data)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(db, data)

        await db.flush()


async def _handle_checkout_completed(db: AsyncSession, session: dict) -> None:
    user_id = int(session.get("metadata", {}).get("user_id", 0) or 0)
    plan_id = session.get("metadata", {}).get("plan_id", PlanId.PRO.value)
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    if not user_id:
        return

    user = await db.get(User, user_id)
    if not user:
        return

    sub = await get_or_create_subscription(db, user)
    sub.payment_provider = "stripe"
    sub.provider_customer_id = customer_id
    sub.stripe_customer_id = customer_id
    sub.provider_subscription_id = subscription_id
    sub.stripe_subscription_id = subscription_id
    sub.currency = "usd"
    sub.billing_interval = "month"
    await apply_subscription_state(db, sub, user, plan_id=plan_id, status="active")


async def _handle_subscription_updated(db: AsyncSession, stripe_sub: dict) -> None:
    subscription_id = stripe_sub.get("id")
    result = await db.execute(
        select(Subscription).where(
            (Subscription.provider_subscription_id == subscription_id)
            | (Subscription.stripe_subscription_id == subscription_id)
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    user = await db.get(User, sub.user_id)
    if not user:
        return

    status = stripe_sub.get("status", "active")
    plan_id = stripe_sub.get("metadata", {}).get("plan_id") or sub.plan_id
    period_end = stripe_sub.get("current_period_end")
    period_end_dt = (
        datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
    )
    await apply_subscription_state(
        db, sub, user, plan_id=plan_id, status=status, current_period_end=period_end_dt
    )


async def _handle_payment_failed(db: AsyncSession, invoice: dict) -> None:
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return
    result = await db.execute(
        select(Subscription).where(
            (Subscription.provider_subscription_id == subscription_id)
            | (Subscription.stripe_subscription_id == subscription_id)
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return
    user = await db.get(User, sub.user_id)
    if not user:
        return
    sub.status = "past_due"
    await db.flush()
