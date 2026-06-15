"""Admin-only user management and activity audit."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_meta, hash_password, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ActivityFilterOptions,
    ActivityListResponse,
    ActivityLogOut,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.services.activity_service import (
    KNOWN_ACTIONS,
    get_activity_filter_options,
    list_activity,
    log_activity,
)
from app.services.user_service import create_user, list_users

router = APIRouter(prefix="/admin", tags=["admin"])


def _activity_out(entry) -> ActivityLogOut:
    data = ActivityLogOut.model_validate(entry)
    data.action_label = KNOWN_ACTIONS.get(entry.action, entry.action)
    return data


@router.get("/users", response_model=UserListResponse)
async def admin_list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    users, total = await list_users(db, limit=limit, offset=offset)
    return UserListResponse(
        users=[UserOut.model_validate(u) for u in users],
        total=total,
    )


@router.post("/users", response_model=UserOut, status_code=201)
async def admin_create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    try:
        user = await create_user(
            db,
            username=payload.username,
            password=payload.password,
            role="user",
            telegram_number=payload.telegram_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=admin,
        action="admin.user.create",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"Created user {user.username}",
        metadata={"telegram_number": payload.telegram_number},
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.id != admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate admin accounts from this endpoint")

    if payload.telegram_number is not None:
        user.telegram_number = payload.telegram_number or None
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)

    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=admin,
        action="admin.user.update",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"Updated user {user.username}",
        metadata=payload.model_dump(exclude_unset=True, exclude={"password"}),
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/activity/filters", response_model=ActivityFilterOptions)
async def admin_activity_filters(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActivityFilterOptions:
    options = await get_activity_filter_options(db)
    return ActivityFilterOptions.model_validate(options)


@router.get("/activity", response_model=ActivityListResponse)
async def admin_list_activity(
    user_id: int | None = Query(None),
    username: str | None = Query(None, description="Partial username match"),
    action: str | None = Query(None, description="Exact action code"),
    action_prefix: str | None = Query(None, description="Action prefix e.g. alert, script"),
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None, description="Partial resource id match"),
    search: str | None = Query(None, description="Search detail, username, action, resource"),
    date_from: str | None = Query(None, description="ISO date or datetime (inclusive)"),
    date_to: str | None = Query(None, description="ISO date or datetime (inclusive)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActivityListResponse:
    items, total = await list_activity(
        db,
        user_id=user_id,
        username=username,
        action=action,
        action_prefix=action_prefix,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    pages = max(1, math.ceil(total / page_size)) if total else 1
    return ActivityListResponse(
        items=[_activity_out(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
