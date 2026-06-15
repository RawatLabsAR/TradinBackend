"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    client_meta,
    create_access_token,
    get_current_user,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, UserOut
from app.services.activity_service import log_activity
from app.services.user_service import get_user_by_username, record_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await get_user_by_username(db, payload.username)
    ip, ua = client_meta(request)
    if not user or not verify_password(payload.password, user.password_hash):
        await log_activity(
            db,
            user=None,
            action="auth.login.failed",
            resource_type="user",
            resource_id=payload.username.strip().lower(),
            detail=f"Failed login attempt for {payload.username.strip().lower()}",
            metadata={"username": payload.username.strip().lower()},
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        await log_activity(
            db,
            user=user,
            action="auth.login.failed",
            resource_type="user",
            resource_id=str(user.id),
            detail=f"Login blocked — account disabled ({user.username})",
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    await record_login(db, user)
    await log_activity(
        db,
        user=user,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"User {user.username} logged in",
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()

    token = create_access_token(user)
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
