"""Permission boundary tests."""

import pytest


@pytest.mark.asyncio
async def test_analytics_requires_auth(client):
    resp = await client.get("/api/analytics/fear-greed")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_routes_require_auth(client):
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin(client):
    await client.post(
        "/api/auth/register",
        json={"username": "regular", "email": "regular@example.com", "password": "secret12"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": "secret12"},
    )
    token = login.json()["access_token"]
    resp = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
