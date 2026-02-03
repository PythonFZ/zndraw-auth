"""Database models and session management."""

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from zndraw_auth.settings import AuthSettings, get_auth_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    """User model for authentication.

    Inherits from fastapi-users base which provides:
    - id: UUID (primary key)
    - email: str (unique, indexed)
    - hashed_password: str
    - is_active: bool (default True)
    - is_superuser: bool (default False)
    - is_verified: bool (default False)
    """

    pass


@lru_cache
def get_engine(database_url: str) -> AsyncEngine:
    """Get or create the async engine (cached by URL)."""
    return create_async_engine(database_url, echo=False)


@lru_cache
def get_session_maker(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Get or create the session maker (cached by URL)."""
    engine = get_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables(settings: AuthSettings | None = None) -> None:
    """Create all database tables.

    Call this in your app's lifespan or startup.
    """
    if settings is None:
        settings = get_auth_settings()
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    session_maker = get_session_maker(settings.database_url)
    async with session_maker() as session:
        yield session


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    """FastAPI dependency that yields the user database adapter."""
    yield SQLAlchemyUserDatabase(session, User)
