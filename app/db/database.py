from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _build_connect_args() -> dict:
    args: dict = {}
    # Transaction poolers on :6543 disable prepared statements.
    if ":6543" in settings.DATABASE_URL:
        args["statement_cache_size"] = 0
    return args


def _build_engine() -> Optional[AsyncEngine]:
    url = settings.database_url
    if url is None:
        return None

    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.DEBUG)

    return create_async_engine(
        url,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        connect_args=_build_connect_args(),
    )


engine = _build_engine()

AsyncSessionLocal = (
    async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    if engine is not None
    else None
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it in .env to enable persistence."
        )
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_optional_db() -> AsyncGenerator[AsyncSession | None, None]:
    """Yield a DB session when configured, otherwise None (in-memory-only mode)."""
    if AsyncSessionLocal is None:
        yield None
        return
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_auth_columns()
    await ensure_user_saas_columns()
    await ensure_oauth_columns()
    await ensure_billing_columns()
    await ensure_discovery_snapshot_schema()


async def ensure_user_saas_columns() -> None:
    """Add SaaS user columns and new tables (idempotent on PostgreSQL)."""
    if engine is None:
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(32) NOT NULL DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email) WHERE email IS NOT NULL",
        "UPDATE users SET is_verified = true WHERE role = 'admin' AND is_verified = false",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def ensure_auth_columns() -> None:
    """Add user_id columns to existing tables (idempotent on PostgreSQL)."""
    if engine is None:
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE scripts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def ensure_oauth_columns() -> None:
    """Add Google OAuth columns (idempotent on PostgreSQL)."""
    if engine is None:
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(128)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(16) NOT NULL DEFAULT 'local'",
        "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id) WHERE google_id IS NOT NULL",
        "UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL OR auth_provider = ''",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def ensure_billing_columns() -> None:
    """Add provider-agnostic billing columns (idempotent on PostgreSQL)."""
    if engine is None:
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(32)",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_customer_id VARCHAR(128)",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_subscription_id VARCHAR(128)",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_id VARCHAR(32) NOT NULL DEFAULT 'free'",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS billing_interval VARCHAR(16) NOT NULL DEFAULT 'month'",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS currency VARCHAR(8)",
        "UPDATE subscriptions SET plan_id = tier WHERE plan_id IS NULL OR plan_id = ''",
        "UPDATE subscriptions SET provider_customer_id = stripe_customer_id WHERE provider_customer_id IS NULL AND stripe_customer_id IS NOT NULL",
        "UPDATE subscriptions SET provider_subscription_id = stripe_subscription_id WHERE provider_subscription_id IS NULL AND stripe_subscription_id IS NOT NULL",
        "UPDATE subscriptions SET payment_provider = 'stripe' WHERE payment_provider IS NULL AND stripe_subscription_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_subscriptions_provider_subscription_id ON subscriptions (provider_subscription_id) WHERE provider_subscription_id IS NOT NULL",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def ensure_discovery_snapshot_schema() -> None:
    """Align legacy discovery_snapshots tables with the current ORM schema."""
    if engine is None:
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS category VARCHAR(32)",
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS chain VARCHAR(32) NOT NULL DEFAULT ''",
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS payload JSONB",
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS sources_used JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS scanned_at TIMESTAMPTZ",
        "ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "UPDATE discovery_snapshots SET category = 'new_dex' WHERE category IS NULL",
        "UPDATE discovery_snapshots SET chain = '' WHERE chain IS NULL",
        "UPDATE discovery_snapshots SET sources_used = '[]'::jsonb WHERE sources_used IS NULL",
        "UPDATE discovery_snapshots SET scanned_at = COALESCE(scanned_at, created_at, NOW()) WHERE scanned_at IS NULL",
        """
        DO $$ BEGIN
            ALTER TABLE discovery_snapshots
                ADD CONSTRAINT uq_discovery_category_chain UNIQUE (category, chain);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def dispose_engine() -> None:
    if engine is not None:
        await engine.dispose()


def database_available() -> bool:
    return engine is not None
