"""Rate limit and public endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_health_is_public(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_news_requires_auth(client):
    resp = await client.get("/api/news/BTC")
    assert resp.status_code == 401
