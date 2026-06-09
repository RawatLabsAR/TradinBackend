from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _build_connect_args() -> dict:
    args: dict = {}
    # Supabase Supavisor (transaction pooler) does not support prepared statements.
    if ":6543" in settings.DATABASE_URL:
        args["statement_cache_size"] = 0
    # Supabase requires SSL for all Postgres connections.
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
        pool_size=10,
        max_overflow=20,
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


async def get_db() -> AsyncSession:
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. "
            "Set it in backend/.env from Supabase Dashboard → Database."
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


async def create_tables() -> None:
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    if engine is not None:
        await engine.dispose()
