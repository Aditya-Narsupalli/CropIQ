"""
Async SQLAlchemy setup for the PostgreSQL-backed market price history table.

This is intentionally lightweight (no Alembic migrations) since the app only
needs a single table today. `init_db()` creates the table if it doesn't
already exist and is called once on FastAPI startup.
"""
import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

Base = declarative_base()

# pool_pre_ping avoids handing out dead connections after the DB restarts /
# the connection idles out.
engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create tables that don't exist yet. Safe to call on every startup."""
    # Import models here so they're registered on Base.metadata before
    # create_all runs, without creating a circular import at module load.
    from app.models import market  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified/created successfully.")
    except Exception as e:
        logger.error(
            f"Could not initialize the database (is PostgreSQL running and "
            f"DATABASE_URL correct?): {e}"
        )
        raise


@asynccontextmanager
async def get_session():
    """Async context-manager session, for use outside of FastAPI's DI system
    (e.g. from the multi-agent classes and background jobs)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_db():
    """FastAPI dependency-injectable session generator."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
