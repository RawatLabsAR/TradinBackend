"""Google OAuth auth tests."""

from unittest.mock import patch

import pytest

from app.services.google_auth_service import GoogleProfile


@pytest.mark.asyncio
async def test_google_config_disabled(client):
    with patch("app.api.routes.auth.google_oauth_enabled", return_value=False):
        resp = await client.get("/api/auth/google/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False


@pytest.mark.asyncio
async def test_google_login_creates_user(client):
    profile = GoogleProfile(
        google_id="google-sub-123",
        email="googleuser@example.com",
        email_verified=True,
        name="Google User",
    )

    with patch("app.api.routes.auth.google_oauth_enabled", return_value=True), patch(
        "app.api.routes.auth.verify_google_id_token",
        return_value=profile,
    ):
        resp = await client.post("/api/auth/google", json={"id_token": "fake-token"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["email"] == "googleuser@example.com"
    assert data["user"]["has_password"] is False
    assert data["user"]["auth_provider"] == "google"
    assert "access_token" in data


@pytest.mark.asyncio
async def test_google_login_invalid_token(client):
    with patch("app.api.routes.auth.google_oauth_enabled", return_value=True), patch(
        "app.api.routes.auth.verify_google_id_token",
        side_effect=ValueError("Invalid Google token"),
    ):
        resp = await client.post("/api/auth/google", json={"id_token": "bad-token-value"})

    assert resp.status_code == 401
