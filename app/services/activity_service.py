"""Centralized user activity audit logging."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Request
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_meta
from app.models.activity_log import ActivityLog
from app.models.user import User

# Human-readable labels for filter dropdowns (frontend mirrors this list).
KNOWN_ACTIONS: dict[str, str] = {
    "auth.login": "Login",
    "auth.login.failed": "Failed login",
    "alert.create": "Create price alert",
    "alert.update": "Update price alert",
    "alert.delete": "Delete price alert",
    "script.create": "Create strategy script",
    "script.update": "Update strategy script",
    "script.delete": "Delete strategy script",
    "script.run": "Run strategy",
    "script.backtest": "Run backtest",
    "broadcast.send": "Send broadcast",
    "broadcast.schedule": "Schedule broadcast",
    "broadcast.cancel": "Cancel broadcast",
    "broadcast.template.create": "Create broadcast template",
    "broadcast.template.update": "Update broadcast template",
    "broadcast.template.delete": "Delete broadcast template",
    "broadcast.signal": "Broadcast trading signal",
    "discovery.scan": "Run discovery scan",
    "onchain.sync": "Sync on-chain data",
    "token.broadcast": "Broadcast token alert",
    "token.search.record": "Record token search",
    "telegram.channel.create": "Add Telegram channel",
    "telegram.channel.update": "Update Telegram channel",
    "telegram.channel.delete": "Remove Telegram channel",
    "admin.user.create": "Create user (admin)",
    "admin.user.update": "Update user (admin)",
    "paper.open": "Open paper trade",
    "paper.close": "Close paper trade",
}


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


async def log_request_action(
    db: AsyncSession,
    request: Request,
    user: User,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActivityLog:
    """Log a user action with request IP and user-agent."""
    ip, ua = client_meta(request)
    return await log_activity(
        db,
        user=user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        metadata=metadata,
        ip_address=ip,
        user_agent=ua,
    )


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(value)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _apply_filters(
    q,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    action_prefix: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    if user_id is not None:
        q = q.where(ActivityLog.user_id == user_id)
    if username:
        q = q.where(ActivityLog.username.ilike(f"%{username.strip()}%"))
    if action:
        q = q.where(ActivityLog.action == action)
    elif action_prefix:
        q = q.where(ActivityLog.action.like(f"{action_prefix.strip()}%"))
    if resource_type:
        q = q.where(ActivityLog.resource_type == resource_type)
    if resource_id:
        q = q.where(ActivityLog.resource_id.ilike(f"%{resource_id.strip()}%"))
    if search:
        pattern = f"%{search.strip()}%"
        q = q.where(
            or_(
                ActivityLog.detail.ilike(pattern),
                ActivityLog.username.ilike(pattern),
                ActivityLog.action.ilike(pattern),
                ActivityLog.resource_id.ilike(pattern),
            )
        )
    since = _parse_date(date_from)
    if since:
        q = q.where(ActivityLog.created_at >= since)
    until = _parse_date(date_to, end_of_day=True)
    if until:
        q = q.where(ActivityLog.created_at <= until)
    return q


async def list_activity(
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    action_prefix: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ActivityLog], int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 500)
    offset = (page - 1) * page_size

    q = select(ActivityLog)
    count_q = select(func.count(ActivityLog.id))

    q = _apply_filters(
        q,
        user_id=user_id,
        username=username,
        action=action,
        action_prefix=action_prefix,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    count_q = _apply_filters(
        count_q,
        user_id=user_id,
        username=username,
        action=action,
        action_prefix=action_prefix,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_activity_filter_options(db: AsyncSession) -> dict[str, Any]:
    """Distinct values for admin activity log filter dropdowns."""
    actions_result = await db.execute(
        select(ActivityLog.action)
        .distinct()
        .order_by(ActivityLog.action)
    )
    actions = [row[0] for row in actions_result.all()]

    resource_types_result = await db.execute(
        select(ActivityLog.resource_type)
        .where(ActivityLog.resource_type.isnot(None))
        .distinct()
        .order_by(ActivityLog.resource_type)
    )
    resource_types = [row[0] for row in resource_types_result.all() if row[0]]

    users_result = await db.execute(
        select(ActivityLog.user_id, ActivityLog.username)
        .where(ActivityLog.user_id.isnot(None))
        .distinct()
        .order_by(ActivityLog.username)
    )
    users = [
        {"id": row[0], "username": row[1]}
        for row in users_result.all()
        if row[0] is not None and row[1]
    ]

    return {
        "actions": actions,
        "action_labels": {a: KNOWN_ACTIONS.get(a, a) for a in actions},
        "resource_types": resource_types,
        "users": users,
        "action_prefixes": sorted({a.split(".")[0] for a in actions}),
    }
