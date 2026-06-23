"""Paper trading — simulated long/short positions per user."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.paper_trade import PaperTrade
from app.models.user import User
from app.schemas.paper_trade import (
    PaperJournalAnalytics,
    PaperMarkToMarketItem,
    PaperMarkToMarketResponse,
    PaperTradeClose,
    PaperTradeCreate,
    PaperTradeListResponse,
    PaperTradeOut,
    PaperTradeStats,
)
from app.services.activity_service import log_request_action
from app.services.market_service import get_product_detail
from app.services.paper_trade_service import (
    build_journal_analytics,
    build_stats,
    compute_closed_pnl,
    compute_unrealized_pnl,
    list_trades,
    trade_to_dict,
)

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


def _out(trade: PaperTrade) -> PaperTradeOut:
    return PaperTradeOut.model_validate(trade_to_dict(trade))


@router.get("", response_model=PaperTradeListResponse)
async def get_paper_trades(
    status: str = Query("all", pattern="^(all|open|closed|pending)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperTradeListResponse:
    trades = await list_trades(db, user.id, status=status)
    stats = build_stats(trades)
    return PaperTradeListResponse(
        items=[_out(t) for t in trades],
        total=len(trades),
        stats=PaperTradeStats.model_validate(stats),
    )


@router.get("/mark-to-market", response_model=PaperMarkToMarketResponse)
async def mark_to_market(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperMarkToMarketResponse:
    trades = await list_trades(db, user.id, status="open")
    items: list[PaperMarkToMarketItem] = []
    total = 0.0

    for trade in trades:
        product = await get_product_detail(trade.product_id)
        if not product:
            continue
        current = float(product.get("price") or 0)
        if current <= 0:
            continue
        pnl, pnl_pct = compute_unrealized_pnl(
            trade.side, trade.entry_price, current, trade.quantity, trade.fee_pct,
        )
        total += pnl
        items.append(PaperMarkToMarketItem(
            id=trade.id,
            product_id=trade.product_id,
            side=trade.side,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            current_price=current,
            unrealized_pnl=round(pnl, 4),
            unrealized_pnl_pct=round(pnl_pct, 4),
        ))

    return PaperMarkToMarketResponse(
        items=items,
        total_unrealized_pnl=round(total, 2),
    )


@router.get("/journal", response_model=PaperJournalAnalytics)
async def journal_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperJournalAnalytics:
    trades = await list_trades(db, user.id, status="all")
    data = build_journal_analytics(trades)
    return PaperJournalAnalytics.model_validate(data)


@router.post("", response_model=PaperTradeOut, status_code=201)
async def open_paper_trade(
    payload: PaperTradeCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    is_pending = payload.order_type == "limit"
    trade = PaperTrade(
        user_id=user.id,
        product_id=payload.product_id.upper(),
        side=payload.side,
        entry_price=payload.limit_price if is_pending else payload.entry_price,
        quantity=payload.quantity,
        fee_pct=payload.fee_pct,
        notes=payload.notes,
        source=payload.source,
        order_type=payload.order_type,
        limit_price=payload.limit_price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        script_id=payload.script_id,
        is_pending=1 if is_pending else 0,
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
        detail=f"Paper {payload.side} {trade.product_id} @ {trade.entry_price}",
        metadata={
            "product_id": trade.product_id,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "quantity": trade.quantity,
            "source": payload.source,
            "order_type": payload.order_type,
        },
    )
    await db.commit()
    await db.refresh(trade)
    return _out(trade)


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
    if trade.is_pending:
        raise HTTPException(status_code=400, detail="Cannot close a pending limit order — cancel it instead")

    close_qty = payload.quantity if payload.quantity is not None else trade.quantity
    if close_qty <= 0 or close_qty > trade.quantity:
        raise HTTPException(status_code=400, detail="Invalid close quantity")

    pnl, pnl_pct = compute_closed_pnl(
        trade.side,
        trade.entry_price,
        payload.exit_price,
        close_qty,
        trade.fee_pct,
    )

    if close_qty < trade.quantity:
        remainder = trade.quantity - close_qty
        closed = PaperTrade(
            user_id=user.id,
            product_id=trade.product_id,
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=payload.exit_price,
            quantity=close_qty,
            fee_pct=trade.fee_pct,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            notes=trade.notes,
            source=trade.source,
            order_type=trade.order_type,
            script_id=trade.script_id,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            is_pending=0,
            opened_at=trade.opened_at,
            closed_at=datetime.now(timezone.utc),
        )
        trade.quantity = remainder
        db.add(closed)
        await db.flush()
        await log_request_action(
            db,
            request,
            user,
            action="paper.partial_close",
            resource_type="paper_trade",
            resource_id=str(trade.id),
            detail=f"Partial close {close_qty} of {trade.product_id}",
            metadata={"exit_price": payload.exit_price, "pnl": pnl},
        )
        await db.commit()
        await db.refresh(closed)
        return _out(closed)

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
    return _out(trade)


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
