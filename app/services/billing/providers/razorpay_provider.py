"""Razorpay subscription billing provider."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import razorpay
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PlanId, razorpay_enabled, razorpay_plan_id
from app.models.subscription import Subscription
from app.models.user import User
from app.services.billing.subscription_sync import (
    apply_subscription_state,
    get_or_create_subscription,
    record_billing_event,
)

logger = logging.getLogger(__name__)


class RazorpayProvider:
    name = "razorpay"

    def _client(self) -> razorpay.Client:
        return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    def is_configured(self) -> bool:
        return razorpay_enabled()

    def plan_available(self, plan_id: PlanId) -> bool:
        return bool(razorpay_plan_id(plan_id))

    async def create_checkout(self, db: AsyncSession, user: User, plan_id: PlanId) -> str:
        if not self.is_configured():
            raise RuntimeError("Razorpay is not configured")
        rp_plan_id = razorpay_plan_id(plan_id)
        if not rp_plan_id:
            raise RuntimeError(f"Razorpay plan not configured for {plan_id.value}")

        client = self._client()
        sub = await get_or_create_subscription(db, user)

        notes = {"user_id": str(user.id), "plan_id": plan_id.value}
        payload = {
            "plan_id": rp_plan_id,
            "total_count": 120,
            "quantity": 1,
            "customer_notify": 1,
            "notes": notes,
        }

        if user.email:
            payload["notify_info"] = {"notify_email": user.email}

        subscription = client.subscription.create(payload)
        sub_id = subscription.get("id")
        short_url = subscription.get("short_url")
        if not sub_id or not short_url:
            raise RuntimeError("Razorpay subscription creation failed")

        sub.payment_provider = self.name
        sub.provider_subscription_id = sub_id
        sub.currency = "inr"
        sub.billing_interval = "month"
        sub.plan_id = plan_id.value
        sub.tier = plan_id.value
        await db.flush()
        return short_url

    async def create_portal(self, db: AsyncSession, user: User) -> str | None:
        # Razorpay has no hosted portal — return account page with manage instructions
        return f"{settings.FRONTEND_URL.rstrip('/')}/account?billing=manage"

    async def handle_webhook(self, db: AsyncSession, payload: bytes, signature: str) -> None:
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            raise RuntimeError("Razorpay webhook secret not configured")

        client = self._client()
        try:
            client.utility.verify_webhook_signature(
                payload.decode(),
                signature,
                settings.RAZORPAY_WEBHOOK_SECRET,
            )
        except razorpay.errors.SignatureVerificationError as exc:
            raise ValueError("Invalid Razorpay webhook signature") from exc

        body = json.loads(payload.decode())
        event_id = body.get("event_id") or body.get("id") or str(hash(payload))
        event_type = body.get("event", "")
        payload_entity = body.get("payload", {}).get("subscription", {}).get("entity", {})

        if await record_billing_event(db, self.name, str(event_id), event_type):
            return

        if event_type in {"subscription.activated", "subscription.charged", "subscription.completed"}:
            await _handle_subscription_active(db, payload_entity)
        elif event_type in {"subscription.cancelled", "subscription.halted", "subscription.pending"}:
            await _handle_subscription_inactive(db, payload_entity, event_type)

        await db.flush()


async def _handle_subscription_active(db: AsyncSession, rp_sub: dict) -> None:
    notes = rp_sub.get("notes") or {}
    user_id = int(notes.get("user_id", 0) or 0)
    plan_id = notes.get("plan_id", PlanId.STARTER.value)
    subscription_id = rp_sub.get("id")

    sub: Subscription | None = None
    if user_id:
        user = await db.get(User, user_id)
        if user:
            sub = await get_or_create_subscription(db, user)
    elif subscription_id:
        result = await db.execute(
            select(Subscription).where(Subscription.provider_subscription_id == subscription_id)
        )
        sub = result.scalar_one_or_none()
        user = await db.get(User, sub.user_id) if sub else None
    else:
        return

    if not sub or not user:
        return

    sub.payment_provider = "razorpay"
    sub.provider_subscription_id = subscription_id
    sub.currency = "inr"
    current_end = rp_sub.get("current_end")
    period_end = datetime.fromtimestamp(current_end, tz=timezone.utc) if current_end else None
    await apply_subscription_state(
        db, sub, user, plan_id=plan_id, status="active", current_period_end=period_end
    )


async def _handle_subscription_inactive(db: AsyncSession, rp_sub: dict, event_type: str) -> None:
    subscription_id = rp_sub.get("id")
    if not subscription_id:
        return
    result = await db.execute(
        select(Subscription).where(Subscription.provider_subscription_id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return
    user = await db.get(User, sub.user_id)
    if not user:
        return

    if event_type == "subscription.pending":
        sub.status = "past_due"
        await db.flush()
        return

    await apply_subscription_state(db, sub, user, plan_id=PlanId.FREE.value, status="canceled")
