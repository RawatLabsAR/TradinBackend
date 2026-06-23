"""Email verification and password reset token management."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_refresh_token_value, hash_token
from app.models.auth_token import EmailVerificationToken, PasswordResetToken
from app.models.user import User


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def create_email_verification_token(db: AsyncSession, user_id: int) -> str:
    raw = _new_token()
    row = EmailVerificationToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(row)
    await db.flush()
    return raw


async def consume_email_verification_token(db: AsyncSession, raw_token: str) -> int | None:
    resolved = await resolve_email_verification_token(db, raw_token)
    if not resolved:
        return None
    user_id, _already_verified = resolved
    return user_id


async def resolve_email_verification_token(
    db: AsyncSession, raw_token: str
) -> tuple[int, bool] | None:
    """Return (user_id, already_verified) for valid tokens, else None."""
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    now = datetime.now(timezone.utc)
    if row.expires_at < now:
        return None

    user = await db.get(User, row.user_id)
    if not user:
        return None

    if row.used_at is not None:
        if user.is_verified:
            return row.user_id, True
        return None

    row.used_at = now
    return row.user_id, user.is_verified


async def create_password_reset_token(db: AsyncSession, user_id: int) -> str:
    raw = create_refresh_token_value()
    row = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(row)
    await db.flush()
    return raw


async def consume_password_reset_token(db: AsyncSession, raw_token: str) -> int | None:
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not row or row.used_at is not None or row.expires_at < now:
        return None
    row.used_at = now
    return row.user_id
