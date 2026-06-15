"""User CRUD and bootstrap admin."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username.strip().lower())
    )
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role: str = "user",
    telegram_number: str | None = None,
) -> User:
    username = username.strip().lower()
    existing = await get_user_by_username(db, username)
    if existing:
        raise ValueError(f"Username '{username}' already exists")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        telegram_number=telegram_number,
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
    )
    logger.info("Bootstrap admin user '%s' created", admin_username)


async def record_login(db: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
