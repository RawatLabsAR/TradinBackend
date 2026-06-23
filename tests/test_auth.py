"""Auth flow tests."""

import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    reg = await client.post(
        "/api/auth/register",
        json={"username": "testuser", "email": "test@example.com", "password": "secret12"},
    )
    assert reg.status_code == 201

    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "secret12"},
    )
    assert login.status_code == 200
    data = login.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "testuser"


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client):
    await client.post(
        "/api/auth/register",
        json={"username": "refreshuser", "email": "refresh@example.com", "password": "secret12"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "refreshuser", "password": "secret12"},
    )
    refresh_token = login.json()["refresh_token"]
    refreshed = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    assert "access_token" in refreshed.json()
