"""Whale scanner REST endpoints — read persisted cron results."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.common import StatusResponse
from app.schemas.whale_scan import (
    WhaleScanDetailResponse,
    WhaleScanEventSummary,
    WhaleScanHitSchema,
    WhaleScanHitsResponse,
    WhaleScanOverviewResponse,
    WhaleScanRunStatusResponse,
)
from app.schemas.onchain import WhaleEventSchema
from app.whale_scanner import api_service
from app.whale_scanner import progress
from app.whale_scanner.runner import background_task_running, start_background_scan
from app.whale_scanner.settings import whale_scan_settings

router = APIRouter(prefix="/whale-scan", tags=["whale-scan"])


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _hit_to_schema(hit: api_service.WhaleScanHit) -> WhaleScanHitSchema:
    return WhaleScanHitSchema(
        chain=hit.chain,
        contract_address=hit.contract_address,
        symbol=hit.symbol,
        token_name=hit.token_name,
        dex=hit.dex,
        liquidity_usd=hit.liquidity_usd,
        volume_24h=hit.volume_24h,
        age_hours=hit.age_hours,
        last_scanned_at=_iso(hit.last_scanned_at),
        max_usd=hit.max_usd,
        score=hit.score,
        event_summary=[
            WhaleScanEventSummary(event_type=item.event_type, count=item.count)
            for item in hit.event_summary
        ],
        notified_at=_iso(hit.notified_at),
    )


@router.get("/run/status", response_model=WhaleScanRunStatusResponse)
async def whale_scan_run_status():
    return WhaleScanRunStatusResponse(**progress.snapshot())


@router.post("/scan", response_model=StatusResponse)
async def trigger_whale_scan(
    admin: User = Depends(require_admin),
    limit: Optional[int] = Query(None, ge=1, le=200),
    dry_run: bool = Query(False),
):
    """Start a whale scan in the background. Poll GET /whale-scan/run/status for progress."""
    if progress.is_running() or background_task_running():
        raise HTTPException(status_code=409, detail="Whale scan already running")

    try:
        await start_background_scan(limit=limit, dry_run=dry_run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StatusResponse(status="started")


@router.get("/overview", response_model=WhaleScanOverviewResponse)
async def whale_scan_overview(
    hours: Optional[int] = Query(None, ge=1, le=8760),
    db: AsyncSession = Depends(get_db),
):
    overview = await api_service.get_overview(db, hours=hours)
    return WhaleScanOverviewResponse(
        last_run_at=overview.last_run_at,
        last_run_status=overview.last_run_status,
        tokens_scanned=overview.tokens_scanned,
        whales_detected=overview.whales_detected,
        hits_count=overview.hits_count,
        threshold_usd=overview.threshold_usd,
        lookback_hours=overview.lookback_hours,
        max_age_days=overview.max_age_days,
    )


@router.get("/hits", response_model=WhaleScanHitsResponse)
async def whale_scan_hits(
    chain: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    db: AsyncSession = Depends(get_db),
):
    items, total, scanned_at = await api_service.get_hits(
        db,
        chain=chain.lower() if chain else None,
        page=page,
        page_size=page_size,
        hours=hours,
    )
    return WhaleScanHitsResponse(
        total=total,
        items=[_hit_to_schema(item) for item in items],
        scanned_at=scanned_at,
        page=page,
        page_size=page_size,
    )


@router.get("/{chain}/{address}", response_model=WhaleScanDetailResponse)
async def whale_scan_detail(
    chain: str,
    address: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    db: AsyncSession = Depends(get_db),
):
    detail = await api_service.get_candidate_detail(
        db,
        chain,
        address,
        page=page,
        page_size=page_size,
        hours=hours,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Token not in whale scan registry")

    candidate = detail.candidate
    lookback = hours or whale_scan_settings.WHALE_LOOKBACK_HOURS
    return WhaleScanDetailResponse(
        chain=candidate.chain,
        contract_address=candidate.contract_address,
        symbol=candidate.symbol,
        token_name=candidate.token_name,
        dex=candidate.dex,
        liquidity_usd=candidate.liquidity_usd,
        volume_24h=candidate.volume_24h,
        age_hours=candidate.age_hours,
        last_scanned_at=_iso(candidate.last_scanned_at),
        max_usd=detail.max_usd,
        score=detail.score,
        event_summary=[
            WhaleScanEventSummary(event_type=item.event_type, count=item.count)
            for item in detail.event_summary
        ],
        events=[WhaleEventSchema.model_validate(event) for event in detail.events],
        total_events=detail.total_events,
        page=page,
        page_size=page_size,
        threshold_usd=whale_scan_settings.WHALE_THRESHOLD_USD,
        lookback_hours=lookback,
    )
