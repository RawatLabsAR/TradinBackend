"""User watchlist and portfolio — persisted in Supabase Postgres."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.user_data import (
    PortfolioHoldingCreate,
    PortfolioHoldingOut,
    PortfolioHoldingUpdate,
    PortfolioReplace,
    PortfolioResponse,
    WatchlistReplace,
    WatchlistResponse,
)
from app.services import portfolio_service, watchlist_service

router = APIRouter(prefix="/user", tags=["user-data"])


def _portfolio_response(holdings) -> PortfolioResponse:
    return PortfolioResponse(
        holdings=[PortfolioHoldingOut.model_validate(h) for h in holdings],
    )


@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistResponse:
    items = await watchlist_service.list_product_ids(db, user.id)
    return WatchlistResponse(items=items)


@router.put("/watchlist", response_model=WatchlistResponse)
async def replace_watchlist(
    payload: WatchlistReplace,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistResponse:
    items = await watchlist_service.replace_items(db, user.id, payload.items)
    return WatchlistResponse(items=items)


@router.post("/watchlist/{product_id}", response_model=WatchlistResponse)
async def add_watchlist_item(
    product_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistResponse:
    items = await watchlist_service.add_item(db, user.id, product_id)
    return WatchlistResponse(items=items)


@router.delete("/watchlist/{product_id}", response_model=WatchlistResponse)
async def remove_watchlist_item(
    product_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistResponse:
    items = await watchlist_service.remove_item(db, user.id, product_id)
    return WatchlistResponse(items=items)


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioResponse:
    holdings = await portfolio_service.list_holdings(db, user.id)
    return _portfolio_response(holdings)


@router.put("/portfolio", response_model=PortfolioResponse)
async def replace_portfolio(
    payload: PortfolioReplace,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioResponse:
    rows = [
        {
            "product_id": h.product_id,
            "quantity": h.quantity,
            "avg_cost": h.avg_cost,
            "added_at": h.added_at.isoformat() if h.added_at else None,
        }
        for h in payload.holdings
    ]
    holdings = await portfolio_service.replace_holdings(db, user.id, rows)
    return _portfolio_response(holdings)


@router.post("/portfolio", response_model=PortfolioHoldingOut, status_code=201)
async def add_portfolio_holding(
    payload: PortfolioHoldingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioHoldingOut:
    holding = await portfolio_service.add_or_merge(
        db,
        user.id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
    )
    return PortfolioHoldingOut.model_validate(holding)


@router.patch("/portfolio/{product_id}", response_model=PortfolioHoldingOut)
async def update_portfolio_holding(
    product_id: str,
    payload: PortfolioHoldingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioHoldingOut:
    holding = await portfolio_service.update_holding(
        db,
        user.id,
        product_id,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
    )
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    return PortfolioHoldingOut.model_validate(holding)


@router.delete("/portfolio/{product_id}", status_code=204)
async def delete_portfolio_holding(
    product_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    removed = await portfolio_service.remove_holding(db, user.id, product_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Holding not found")


@router.delete("/portfolio", status_code=204)
async def clear_portfolio(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await portfolio_service.clear_all(db, user.id)
