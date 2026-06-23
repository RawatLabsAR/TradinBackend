"""User CRUD and bootstrap admin."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.config import settings
from app.models.user import User
from app.services.google_auth_service import GoogleProfile

logger = logging.getLogger(__name__)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_login(db: AsyncSession, login: str) -> User | None:
    """Resolve a user from username or email."""
    value = login.strip().lower()
    if "@" in value:
        return await get_user_by_email(db, value)
    return await get_user_by_username(db, value)


async def get_user_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()


async def _generate_username(db: AsyncSession, email: str, name: str | None) -> str:
    base = (name or email.split("@", 1)[0]).strip().lower()
    base = re.sub(r"[^a-z0-9_-]+", "", base.replace(".", "_").replace(" ", "_"))
    base = base[:48] or "user"
    candidate = base
    for _ in range(20):
        existing = await get_user_by_username(db, candidate)
        if not existing:
            return candidate
        candidate = f"{base}_{secrets.token_hex(2)}"
    return f"user_{secrets.token_hex(4)}"


async def find_or_create_google_user(db: AsyncSession, profile: GoogleProfile) -> tuple[User, bool]:
    """Return (user, created). Links Google to an existing email account when safe."""
    existing_google = await get_user_by_google_id(db, profile.google_id)
    if existing_google:
        if profile.email_verified and not existing_google.is_verified:
            existing_google.is_verified = True
        if not existing_google.email:
            existing_google.email = profile.email
        return existing_google, False

    by_email = await get_user_by_email(db, profile.email)
    if by_email:
        if by_email.google_id and by_email.google_id != profile.google_id:
            raise ValueError("This email is linked to a different Google account")
        by_email.google_id = profile.google_id
        if by_email.auth_provider == "local":
            by_email.auth_provider = "local"  # keep local; Google becomes alternate sign-in
        if profile.email_verified:
            by_email.is_verified = True
        return by_email, False

    username = await _generate_username(db, profile.email, profile.name)
    user = User(
        username=username,
        email=profile.email,
        password_hash=None,
        google_id=profile.google_id,
        auth_provider="google",
        is_verified=profile.email_verified,
    )
    db.add(user)
    await db.flush()
    return user, True


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    email: str | None = None,
    role: str = "user",
    telegram_number: str | None = None,
    is_verified: bool = False,
) -> User:
    username = username.strip().lower()
    existing = await get_user_by_username(db, username)
    if existing:
        raise ValueError(f"Username '{username}' already exists")
    if email:
        email = email.strip().lower()
        existing_email = await get_user_by_email(db, email)
        if existing_email:
            raise ValueError(f"Email '{email}' already registered")
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
        telegram_number=telegram_number,
        is_verified=is_verified,
    )
    db.add(user)
    await db.flush()
    return user


async def list_users(db: AsyncSession, *, limit: int = 100, offset: int = 0) -> tuple[list[User], int]:
    total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    rows = (
        await db.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return list(rows), total


async def ensure_admin_user(db: AsyncSession) -> None:
    """Create bootstrap admin from env if no admin exists."""
    admin_username = (settings.ADMIN_USERNAME or "").strip().lower()
    admin_password = settings.ADMIN_PASSWORD or ""
    if not admin_username or not admin_password:
        logger.warning("ADMIN_USERNAME/ADMIN_PASSWORD not set — skipping admin bootstrap")
        return

    result = await db.execute(select(User).where(User.role == "admin"))
    if result.scalars().first():
        return

    existing = await get_user_by_username(db, admin_username)
    if existing:
        existing.role = "admin"
        existing.is_active = True
        logger.info("Promoted existing user '%s' to admin", admin_username)
        return

    await create_user(
        db,
        username=admin_username,
        password=admin_password,
        role="admin",
        is_verified=True,
    )
    logger.info("Bootstrap admin user '%s' created", admin_username)


async def record_login(db: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)


async def delete_user_account(db: AsyncSession, user: User) -> None:
    await db.delete(user)
