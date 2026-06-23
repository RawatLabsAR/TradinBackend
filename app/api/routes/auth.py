"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    client_meta,
    create_access_token,
    create_refresh_token_value,
    get_current_user,
    hash_password,
    is_account_locked,
    record_failed_login,
    reset_failed_login,
    revoke_refresh_token,
    store_refresh_token,
    validate_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    GoogleAuthConfigResponse,
    GoogleAuthRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
    VerifyEmailRequest,
)
from app.services.activity_service import log_activity
from app.services.email_service import send_password_reset_email, send_verification_email
from app.services.google_auth_service import google_oauth_enabled, verify_google_id_token
from app.services.token_service import (
    consume_password_reset_token,
    create_email_verification_token,
    create_password_reset_token,
    resolve_email_verification_token,
)
from app.services.user_service import (
    create_user,
    delete_user_account,
    find_or_create_google_user,
    get_user_by_email,
    get_user_by_login,
    get_user_by_username,
    record_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user)
    refresh_raw = create_refresh_token_value()
    await store_refresh_token(db, user.id, refresh_raw)
    return access, refresh_raw


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(
    payload: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")

    try:
        user = await create_user(
            db,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            is_verified=not settings.REQUIRE_EMAIL_VERIFICATION,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=user,
        action="auth.register",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"User {user.username} registered",
        ip_address=ip,
        user_agent=ua,
    )

    verification_email: tuple[str, str, str] | None = None
    if settings.REQUIRE_EMAIL_VERIFICATION and user.email:
        token = await create_email_verification_token(db, user.id)
        verification_email = (user.email, user.username, token)

    await db.commit()

    if verification_email:
        to_email, username, token = verification_email
        background_tasks.add_task(send_verification_email, to_email, username, token)
    if settings.REQUIRE_EMAIL_VERIFICATION:
        return MessageResponse(message="Account created. Check your email to verify your address.")
    return MessageResponse(message="Account created. You can sign in now.")


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await get_user_by_login(db, payload.username)
    ip, ua = client_meta(request)

    if user and is_account_locked(user):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to failed login attempts",
        )

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        await record_failed_login(db, user)
        await log_activity(
            db,
            user=user,
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_verified and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in",
        )

    await reset_failed_login(db, user)
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

    access, refresh = await _issue_tokens(db, user)
    await db.commit()
    return LoginResponse(access_token=access, refresh_token=refresh, user=UserOut.from_user(user))


@router.get("/google/config", response_model=GoogleAuthConfigResponse)
async def google_auth_config() -> GoogleAuthConfigResponse:
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID.strip()
    return GoogleAuthConfigResponse(enabled=bool(client_id), client_id=client_id)


@router.post("/google", response_model=LoginResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def google_login(
    payload: GoogleAuthRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    if not google_oauth_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured")

    try:
        profile = verify_google_id_token(payload.id_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if not profile.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google account email is not verified",
        )

    try:
        user, created = await find_or_create_google_user(db, profile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    ip, ua = client_meta(request)
    await reset_failed_login(db, user)
    await record_login(db, user)
    await log_activity(
        db,
        user=user,
        action="auth.google.register" if created else "auth.google.login",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"User {user.username} signed in with Google",
        ip_address=ip,
        user_agent=ua,
    )

    access, refresh = await _issue_tokens(db, user)
    await db.commit()
    return LoginResponse(access_token=access, refresh_token=refresh, user=UserOut.from_user(user))


@router.post("/refresh", response_model=LoginResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def refresh_token(
    payload: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await validate_refresh_token(db, payload.refresh_token)
    access, refresh = await _issue_tokens(db, user)
    await db.commit()
    return LoginResponse(access_token=access, refresh_token=refresh, user=UserOut.from_user(user))


@router.post("/logout", response_model=MessageResponse)
async def logout(
    payload: RefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await revoke_refresh_token(db, payload.refresh_token)
    await db.commit()
    return MessageResponse(message="Logged out")


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    resolved = await resolve_email_verification_token(db, payload.token)
    if not resolved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    user_id, already_verified = resolved
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_verified:
        user.is_verified = True
    await db.commit()
    if already_verified:
        return MessageResponse(message="Email already verified. You can sign in.")
    return MessageResponse(message="Email verified successfully")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    user = await get_user_by_email(db, payload.email)
    if user and user.email:
        token = await create_password_reset_token(db, user.id)
        await db.commit()
        background_tasks.add_task(send_password_reset_email, user.email, user.username, token)
    return MessageResponse(message="If that email exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    user_id = await consume_password_reset_token(db, payload.token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.password_hash = hash_password(payload.password)
    await reset_failed_login(db, user)
    await db.commit()
    return MessageResponse(message="Password reset successfully")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No password set for this account. Use Google sign-in or forgot password to set one.",
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return MessageResponse(message="Password updated")


@router.delete("/account", response_model=MessageResponse)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await delete_user_account(db, user)
    await db.commit()
    return MessageResponse(message="Account deleted")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_user(user)
