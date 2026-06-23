"""Billing, quotas, and region routing tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.plans import resolve_payment_provider, upgrade_message_for_tier
from app.core.quotas import _tier_limit
from app.models.billing_event import BillingEvent
from app.models.user import User
from app.services.billing.region import country_from_request
from app.services.billing.subscription_sync import (
    apply_subscription_state,
    get_or_create_subscription,
    record_billing_event,
)


def test_resolve_payment_provider_india():
    assert resolve_payment_provider("IN") == "razorpay"
    assert resolve_payment_provider("in") == "razorpay"


def test_resolve_payment_provider_global():
    assert resolve_payment_provider("US") == "stripe"
    assert resolve_payment_provider(None) == "stripe"


def test_upgrade_message_by_tier():
    assert "Starter" in upgrade_message_for_tier("free")
    assert "Pro" in upgrade_message_for_tier("starter")
    assert upgrade_message_for_tier("pro") == "Daily limit reached."


def test_tier_limits_three_tiers():
    free_user = User(username="f", password_hash="x", subscription_tier="free", role="user")
    starter_user = User(username="s", password_hash="x", subscription_tier="starter", role="user")
    pro_user = User(username="p", password_hash="x", subscription_tier="pro", role="user")

    assert _tier_limit(free_user, "ai_insight") < _tier_limit(starter_user, "ai_insight")
    assert _tier_limit(starter_user, "ai_insight") < _tier_limit(pro_user, "ai_insight")


@pytest.mark.asyncio
async def test_get_plans_endpoint(client):
    res = await client.get("/api/billing/plans")
    assert res.status_code == 200
    data = res.json()
    assert len(data["plans"]) == 3
    assert data["plans"][0]["id"] == "free"
    assert data["provider"] in {"stripe", "razorpay"}


@pytest.mark.asyncio
async def test_get_plans_india(client):
    res = await client.get("/api/billing/plans", params={"country": "IN"})
    assert res.status_code == 200
    assert res.json()["provider"] == "razorpay"
    assert res.json()["currency"] == "inr"


@pytest.mark.asyncio
async def test_subscription_and_usage_authenticated(client):
    reg = await client.post(
        "/api/auth/register",
        json={"username": "billuser", "email": "bill@example.com", "password": "secret12"},
    )
    assert reg.status_code == 201

    login = await client.post("/api/auth/login", json={"username": "billuser", "password": "secret12"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sub = await client.get("/api/billing/subscription", headers=headers)
    assert sub.status_code == 200
    assert sub.json()["plan_id"] == "free"

    usage = await client.get("/api/billing/usage", headers=headers)
    assert usage.status_code == 200
    assert "ai_insight" in usage.json()["quotas"]
    assert usage.json()["next_tier"] == "starter"


@pytest.mark.asyncio
async def test_checkout_unconfigured_returns_503(client):
    await client.post(
        "/api/auth/register",
        json={"username": "checkoutuser", "email": "checkout@example.com", "password": "secret12"},
    )
    login = await client.post("/api/auth/login", json={"username": "checkoutuser", "password": "secret12"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post("/api/billing/checkout", json={"plan": "pro"}, headers=headers)
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_apply_subscription_state_and_idempotency(client):
    from app.db.database import get_db

    async def run_with_db():
        override = app.dependency_overrides[get_db]
        gen = override()
        db = await gen.__anext__()
        try:
            user = User(username="sync", password_hash="x", email="sync@t.com", subscription_tier="free", role="user")
            db.add(user)
            await db.flush()

            sub = await get_or_create_subscription(db, user)
            assert sub.plan_id == "free"

            await apply_subscription_state(db, sub, user, plan_id="starter", status="active")
            assert user.subscription_tier == "starter"
            assert sub.plan_id == "starter"

            first = await record_billing_event(db, "stripe", "evt_123", "checkout.session.completed")
            assert first is False
            second = await record_billing_event(db, "stripe", "evt_123", "checkout.session.completed")
            assert second is True

            result = await db.execute(select(BillingEvent).where(BillingEvent.event_id == "evt_123"))
            assert result.scalar_one_or_none() is not None
        finally:
            await gen.aclose()

    from app.main import app
    await run_with_db()


def test_country_from_request_header():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"cf-ipcountry", b"IN")],
    }
    request = Request(scope)
    assert country_from_request(request) == "IN"
