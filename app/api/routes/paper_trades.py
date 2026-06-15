"""Paper trading — simulated long/short positions per user."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_meta, get_current_user
from app.db.database import get_db
from app.models.paper_trade import PaperTrade
from app.models.user import User
from app.schemas.paper_trade import (
    PaperTradeClose,
    PaperTradeCreate,
    PaperTradeListResponse,
    PaperTradeOut,
    PaperTradeStats,
)
from app.services.activity_service import log_request_action
from app.services.paper_trade_service import build_stats, compute_closed_pnl, list_trades

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


@router.get("", response_model=PaperTradeListResponse)
async def get_paper_trades(
    status: str = Query("all", pattern="^(all|open|closed)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperTradeListResponse:
    trades = await list_trades(db, user.id, status=status)
    stats = build_stats(trades)
    return PaperTradeListResponse(
        items=[PaperTradeOut.model_validate(t) for t in trades],
        total=len(trades),
        stats=PaperTradeStats.model_validate(stats),
    )


@router.post("", response_model=PaperTradeOut, status_code=201)
async def open_paper_trade(
    payload: PaperTradeCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    trade = PaperTrade(
        user_id=user.id,
        product_id=payload.product_id.upper(),
        side=payload.side,
        entry_price=payload.entry_price,
        quantity=payload.quantity,
        fee_pct=payload.fee_pct,
        notes=payload.notes,
        source=payload.source,
    )
    db.add(trade)
    await db.flush()
    await log_request_action(
        db,
        request,
        user,
        action="paper.open",
        resource_type="paper_trade",
        resource_id=str(trade.id),
        detail=f"Paper {payload.side} {trade.product_id} @ {payload.entry_price}",
        metadata={
            "product_id": trade.product_id,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "quantity": trade.quantity,
            "source": payload.source,
        },
    )
    await db.commit()
    await db.refresh(trade)
    return PaperTradeOut.model_validate(trade)


@router.post("/{trade_id}/close", response_model=PaperTradeOut)
async def close_paper_trade(
    trade_id: int,
    payload: PaperTradeClose,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    trade = await db.get(PaperTrade, trade_id)
    if not trade or trade.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper trade not found")
    if trade.closed_at:
        raise HTTPException(status_code=400, detail="Trade already closed")

    pnl, pnl_pct = compute_closed_pnl(
        trade.side,
        trade.entry_price,
        payload.exit_price,
        trade.quantity,
        trade.fee_pct,
    )
    trade.exit_price = payload.exit_price
    trade.pnl = round(pnl, 4)
    trade.pnl_pct = round(pnl_pct, 4)
    trade.closed_at = datetime.now(timezone.utc)

    await log_request_action(
        db,
        request,
        user,
        action="paper.close",
        resource_type="paper_trade",
        resource_id=str(trade.id),
        detail=f"Closed paper {trade.side} {trade.product_id} PnL ${pnl:.2f}",
        metadata={"exit_price": payload.exit_price, "pnl": pnl, "pnl_pct": pnl_pct},
    )
    await db.commit()
    await db.refresh(trade)
    return PaperTradeOut.model_validate(trade)


@router.delete("/{trade_id}", status_code=204)
async def delete_paper_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    trade = await db.get(PaperTrade, trade_id)
    if not trade or trade.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper trade not found")
    await db.delete(trade)
    await db.commit()


@router.delete("/history/closed", status_code=204)
async def clear_closed_trades(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    trades = await list_trades(db, user.id, status="closed")
    for t in trades:
        await db.delete(t)
    await db.commit()
