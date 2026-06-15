from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _build_connect_args() -> dict:
    args: dict = {}
    # Transaction poolers (e.g. Supabase Supavisor on :6543) disable prepared statements.
    if ":6543" in settings.DATABASE_URL:
        args["statement_cache_size"] = 0
    if "supabase.co" in settings.DATABASE_URL:
        args["ssl"] = "require"
    return args


def _build_engine() -> Optional[AsyncEngine]:
    url = settings.database_url
    if url is None:
        return None

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


async def dispose_engine() -> None:
    if engine is not None:
        await engine.dispose()
