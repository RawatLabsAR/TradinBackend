"""
Broadcast REST API routes.

POST /api/broadcast/send             — instant broadcast
POST /api/broadcast/schedule         — schedule future broadcast
GET  /api/broadcast/history          — paginated message history
GET  /api/broadcast/history/{id}     — single message detail
DELETE /api/broadcast/{id}           — cancel a pending/scheduled broadcast

GET  /api/broadcast/templates        — list templates
POST /api/broadcast/templates        — create template
PUT  /api/broadcast/templates/{id}   — update template
DELETE /api/broadcast/templates/{id} — delete template
POST /api/broadcast/templates/render — preview rendered template

POST /api/signals/broadcast          — manual signal broadcast trigger
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from app.core.auth import client_meta, get_current_user
from app.models.user import User
from app.services.activity_service import log_activity
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.broadcast import BroadcastMessage, BroadcastLog, ScheduledBroadcast
from app.broadcast.services.broadcast_service import broadcast_service
from app.broadcast.templates.template_engine import template_engine
from app.schemas.broadcast import (
    BroadcastSendRequest,
    BroadcastScheduleRequest,
    BroadcastMessageOut,
    BroadcastLogOut,
    TemplateCreate,
    TemplateUpdate,
    TemplateOut,
    SignalBroadcastRequest,
    PaginatedBroadcastHistory,
    TemplateRenderRequest,
    TemplateRenderResponse,
    SignalBroadcastResponse,
)
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/broadcast", tags=["broadcast"])
signal_router = APIRouter(prefix="/signals", tags=["signals"])


# ── Send ─────────────────────────────────────────────────────────────────────

@router.post("/send", response_model=BroadcastMessageOut, status_code=201)
async def send_broadcast(
    payload: BroadcastSendRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastMessageOut:
    """Queue an instant broadcast to one or more Telegram channels."""
    message = await broadcast_service.send_manual(
        db=db,
        content=payload.content,
        title=payload.title,
        parse_mode=payload.parse_mode,
        channel_ids=payload.channel_ids,
        template_id=payload.template_id,
        template_variables=payload.template_variables,
    )
    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=user,
        action="broadcast.send",
        resource_type="broadcast",
        resource_id=str(message.id),
        detail=payload.title or "Manual broadcast",
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(message)

    # Enqueue AFTER commit so the worker finds the row in the DB
    await broadcast_service.enqueue_committed_message(message)

    # Notify frontend via WebSocket
    background_tasks.add_task(
        ws_manager.broadcast_all,
        {
            "type": "broadcast_queued",
            "data": {"id": message.id, "status": message.status, "title": message.title},
        },
    )

    return BroadcastMessageOut.model_validate(message)


@router.post("/schedule", response_model=BroadcastMessageOut, status_code=201)
async def schedule_broadcast(
    payload: BroadcastScheduleRequest,
    db: AsyncSession = Depends(get_db),
) -> BroadcastMessageOut:
    """Schedule a broadcast for future delivery."""
    message = await broadcast_service.send_manual(
        db=db,
        content=payload.content,
        title=payload.title,
        parse_mode=payload.parse_mode,
        channel_ids=payload.channel_ids,
        scheduled_at=payload.scheduled_at,
        template_id=payload.template_id,
        template_variables=payload.template_variables,
    )
    await db.commit()
    await db.refresh(message)
    return BroadcastMessageOut.model_validate(message)


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", response_model=PaginatedBroadcastHistory)
async def get_broadcast_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    message_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedBroadcastHistory:
    """Return paginated broadcast message history."""
    result = await broadcast_service.get_history(
        db, page=page, page_size=page_size,
        message_type=message_type, status=status,
    )
    return PaginatedBroadcastHistory(
        items=[BroadcastMessageOut.model_validate(m) for m in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        pages=result["pages"],
    )


@router.get("/history/{message_id}", response_model=BroadcastMessageOut)
async def get_broadcast_detail(
    message_id: int,
    db: AsyncSession = Depends(get_db),
) -> BroadcastMessageOut:
    result = await db.execute(
        select(BroadcastMessage).where(BroadcastMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Broadcast message not found")
    return BroadcastMessageOut.model_validate(msg)


@router.get("/history/{message_id}/logs", response_model=list[BroadcastLogOut])
async def get_broadcast_logs(
    message_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[BroadcastLogOut]:
    result = await db.execute(
        select(BroadcastLog)
        .where(BroadcastLog.message_id == message_id)
        .order_by(desc(BroadcastLog.created_at))
    )
    logs = result.scalars().all()
    return [BroadcastLogOut.model_validate(lg) for lg in logs]


@router.delete("/{message_id}", status_code=204)
async def cancel_broadcast(
    message_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(BroadcastMessage).where(BroadcastMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Broadcast message not found")
    if msg.status not in ("pending", "queued"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel message with status '{msg.status}'")
    msg.status = "cancelled"
    # Cancel scheduled entry if it exists
    sched_result = await db.execute(
        select(ScheduledBroadcast).where(ScheduledBroadcast.message_id == message_id)
    )
    sched = sched_result.scalar_one_or_none()
    if sched:
        sched.status = "cancelled"
    await db.commit()


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateOut]:
    templates = await template_engine.list_templates(db, category=category)
    return [TemplateOut.model_validate(t) for t in templates]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    tpl = await template_engine.create_template(
        db,
        name=payload.name,
        content=payload.content,
        category=payload.category,
        variables=payload.variables,
        parse_mode=payload.parse_mode,
    )
    await db.commit()
    await db.refresh(tpl)
    return TemplateOut.model_validate(tpl)


@router.put("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    tpl = await template_engine.update_template(
        db, template_id, **payload.model_dump(exclude_unset=True)
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.commit()
    await db.refresh(tpl)
    return TemplateOut.model_validate(tpl)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    ok = await template_engine.delete_template(db, template_id)
    if not ok:
        raise HTTPException(404, detail="Template not found")
    await db.commit()


@router.post("/templates/render", response_model=TemplateRenderResponse)
async def render_template_preview(
    payload: TemplateRenderRequest,
) -> TemplateRenderResponse:
    """Preview a template with provided variables (no DB write)."""
    rendered = template_engine.render(payload.content, payload.variables)
    return TemplateRenderResponse(rendered=rendered)


# ── Signal broadcast ──────────────────────────────────────────────────────────

@signal_router.post("/broadcast", response_model=SignalBroadcastResponse, status_code=202)
async def trigger_signal_broadcast(
    payload: SignalBroadcastRequest,
    db: AsyncSession = Depends(get_db),
) -> SignalBroadcastResponse:
    """Manually trigger a signal broadcast (for testing or admin override)."""
    message = await broadcast_service.send_signal_broadcast(
        db=db,
        symbol=payload.symbol,
        signal_type=payload.signal_type,
        strategy=payload.strategy,
        timeframe=payload.timeframe,
        price=payload.price,
        reason=payload.reason,
        sentiment=payload.sentiment,
        ai_commentary=payload.ai_commentary,
    )
    if message is None:
        await db.commit()
        return SignalBroadcastResponse(
            ok=False,
            detail="Signal broadcasting disabled or duplicate suppressed",
        )

    dedup_key = f"signal:{payload.symbol}:{payload.signal_type}:{payload.strategy}:{payload.timeframe}"
    await db.commit()
    await broadcast_service.enqueue_committed_message(message, dedup_key=dedup_key)
    return SignalBroadcastResponse(ok=True, message_id=message.id, status=message.status)
