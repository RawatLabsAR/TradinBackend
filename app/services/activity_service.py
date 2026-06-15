"""Centralized user activity audit logging."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.user import User


async def log_activity(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail,
        meta=metadata or {},
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_activity(
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ActivityLog], int]:
    q = select(ActivityLog)
    count_q = select(func.count(ActivityLog.id))

    if user_id is not None:
        q = q.where(ActivityLog.user_id == user_id)
        count_q = count_q.where(ActivityLog.user_id == user_id)
    if action:
        q = q.where(ActivityLog.action == action)
        count_q = count_q.where(ActivityLog.action == action)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit)
        )
    ).scalars().all()
    return list(rows), total
