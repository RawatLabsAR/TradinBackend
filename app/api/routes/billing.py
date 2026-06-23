"""Billing endpoints — Stripe + Razorpay."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.plans import PlanId, billing_configured
from app.db.database import get_db
from app.models.user import User
from app.services.billing.billing_service import (
    build_plans_response,
    create_checkout,
    create_portal,
    get_usage_summary,
)
from app.services.billing.providers.razorpay_provider import RazorpayProvider
from app.services.billing.providers.stripe_provider import StripeProvider
from app.services.billing.region import country_from_request, resolve_provider_for_checkout
from app.services.billing.subscription_sync import get_or_create_subscription

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

_stripe = StripeProvider()
_razorpay = RazorpayProvider()


class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern="^(starter|pro)$")
    country: str | None = None


class CheckoutResponse(BaseModel):
    url: str
    provider: str


class SubscriptionOut(BaseModel):
    tier: str
    plan_id: str
    status: str
    payment_provider: str | None = None
    currency: str | None = None
    current_period_end: datetime | None = None
    billing_configured: bool


class PortalResponse(BaseModel):
    url: str


@router.get("/plans")
async def list_plans(
    request: Request,
    country: str | None = Query(None, max_length=2),
) -> dict[str, Any]:
    country_code = (country or country_from_request(request) or "").upper() or None
    return build_plans_response(country_code)


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    sub = await get_or_create_subscription(db, user)
    return SubscriptionOut(
        tier=sub.tier,
        plan_id=sub.plan_id or sub.tier,
        status=sub.status,
        payment_provider=sub.payment_provider,
        currency=sub.currency,
        current_period_end=sub.current_period_end,
        billing_configured=billing_configured(),
    )


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await get_usage_summary(db, user)


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    body: CheckoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    if not billing_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing not configured")

    try:
        plan_id = PlanId(body.plan)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plan") from exc

    provider_name = resolve_provider_for_checkout(request, user, body.country)
    try:
        url = await create_checkout(db, user, plan_id, provider_name)
        await db.commit()
    except Exception as exc:
        logger.error("Checkout failed (%s/%s): %s", provider_name, plan_id.value, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Checkout failed") from exc

    return CheckoutResponse(url=url, provider=provider_name)


@router.post("/portal", response_model=PortalResponse)
async def billing_portal(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalResponse:
    url = await create_portal(db, user)
    if not url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing portal unavailable")
    await db.commit()
    return PortalResponse(url=url)


@router.post("/webhook/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        await _stripe.handle_webhook(db, payload, sig)
        await db.commit()
    except Exception as exc:
        logger.error("Stripe webhook error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook error") from exc
    return {"received": True}


@router.post("/webhook/razorpay", include_in_schema=False)
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await request.body()
    sig = request.headers.get("x-razorpay-signature", "")
    try:
        await _razorpay.handle_webhook(db, payload, sig)
        await db.commit()
    except Exception as exc:
        logger.error("Razorpay webhook error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook error") from exc
    return {"received": True}


# Legacy webhook path
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook_legacy(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    return await stripe_webhook(request, db)
