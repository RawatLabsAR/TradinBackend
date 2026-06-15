"""Crypto discovery REST endpoints — reads/writes in-memory cache only."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.discovery.services.discovery_service import discovery_service
from app.discovery.types import DiscoveryToken
from app.schemas.common import StatusResponse
from app.schemas.discovery import DiscoveryOverviewResponse, DiscoveryResponse, DiscoveryTokenSchema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discover", tags=["discovery"])

Category = Literal["new_dex", "new_cex", "surging", "trending"]


def _to_schema(token: DiscoveryToken) -> DiscoveryTokenSchema:
    return DiscoveryTokenSchema.model_validate(token.model_dump())


def _to_response(result) -> DiscoveryResponse:
    return DiscoveryResponse(
        category=result.category,
        total=len(result.items),
        items=[_to_schema(t) for t in result.items],
        sources_used=result.sources_used,
        scanned_at=result.scanned_at,
        cached=result.cached,
    )


@router.get("", response_model=DiscoveryResponse)
@router.get("/", response_model=DiscoveryResponse, include_in_schema=False)
async def discover(
    category: Category = Query("new_dex"),
    chain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    min_volume_change: float = Query(50, ge=0),
    refresh: bool = Query(False),
):
    result = await discovery_service.get_by_category(
        category,
        chain=chain,
        limit=limit,
        min_score=min_score,
        min_volume_change=min_volume_change,
        refresh=refresh,
    )
    return _to_response(result)


@router.get("/new", response_model=DiscoveryResponse)
async def discover_new_dex(
    chain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    refresh: bool = Query(False),
):
    result = await discovery_service.scan_new_dex(
        chain=chain, limit=limit, min_score=min_score, use_cache=not refresh,
    )
    return _to_response(result)


@router.get("/cex-new", response_model=DiscoveryResponse)
async def discover_new_cex(
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    refresh: bool = Query(False),
):
    result = await discovery_service.scan_new_cex(
        limit=limit, min_score=min_score, use_cache=not refresh,
    )
    return _to_response(result)


@router.get("/surging", response_model=DiscoveryResponse)
async def discover_surging(
    chain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    min_volume_change: float = Query(50, ge=0),
    refresh: bool = Query(False),
):
    result = await discovery_service.scan_surging(
        chain=chain, limit=limit, min_volume_change=min_volume_change, use_cache=not refresh,
    )
    return _to_response(result)


@router.get("/trending", response_model=DiscoveryResponse)
async def discover_trending(
    chain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    refresh: bool = Query(False),
):
    result = await discovery_service.scan_trending(
        chain=chain, limit=limit, min_score=min_score, use_cache=not refresh,
    )
    return _to_response(result)


@router.post("/scan", response_model=StatusResponse)
async def trigger_discovery_scan() -> StatusResponse:
    """Manually run a full discovery scan (in-memory cache only)."""
    try:
        await discovery_service.run_full_scan()
    except Exception as exc:
        logger.exception("Discovery scan endpoint error: %s", exc)
    return StatusResponse(status="ok")


@router.get("/overview", response_model=DiscoveryOverviewResponse)
async def discover_overview():
    from app.discovery.cache.discovery_cache import get_cached_discovery

    categories = ["new_dex", "new_cex", "surging", "trending"]
    counts: dict[str, int] = {}
    last_scanned = ""

    for cat in categories:
        cached = await get_cached_discovery(cat)
        if cached:
            counts[cat] = len(cached.items)
            if cached.scanned_at > last_scanned:
                last_scanned = cached.scanned_at
        else:
            counts[cat] = 0

    return DiscoveryOverviewResponse(
        new_dex_count=counts.get("new_dex", 0),
        new_cex_count=counts.get("new_cex", 0),
        surging_count=counts.get("surging", 0),
        trending_count=counts.get("trending", 0),
        last_scanned_at=last_scanned,
    )
