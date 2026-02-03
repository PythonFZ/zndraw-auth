"""Database models and session management."""

import logging
import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from zndraw_auth.settings import AuthSettings, get_auth_settings

log = logging.getLogger(__name__)


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
    """Create all database tables and ensure default admin exists.

    Call this in your app's lifespan or startup.
    """
    if settings is None:
        settings = get_auth_settings()
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure default admin user exists (if configured)
    await ensure_default_admin(settings)


async def ensure_default_admin(settings: AuthSettings | None = None) -> None:
    """Create or promote the default admin user if configured.

    If DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD are set:
    - Creates the user with is_superuser=True if they don't exist
    - Promotes existing user to superuser if they exist but aren't one

    If not configured, does nothing (dev mode - all users are superusers).
    """
    if settings is None:
        settings = get_auth_settings()

    admin_email = settings.default_admin_email
    admin_password = settings.default_admin_password

    if admin_email is None:
        log.info("No default admin configured - running in dev mode")
        return

    if admin_password is None:
        log.warning(
            "DEFAULT_ADMIN_EMAIL is set but DEFAULT_ADMIN_PASSWORD is not - "
            "skipping admin creation"
        )
        return

    session_maker = get_session_maker(settings.database_url)
    password_helper = PasswordHelper()

    async with session_maker() as session:
        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == admin_email)  # type: ignore[arg-type]
        )
        existing_user = result.scalar_one_or_none()

        if existing_user is None:
            # Create new admin user
            hashed_password = password_helper.hash(admin_password.get_secret_value())
            admin_user = User(
                email=admin_email,
                hashed_password=hashed_password,
                is_active=True,
                is_superuser=True,
                is_verified=True,
            )
            session.add(admin_user)
            await session.commit()
            log.info(f"Created default admin user: {admin_email}")
        elif not existing_user.is_superuser:
            # Promote existing user to superuser
            existing_user.is_superuser = True
            await session.commit()
            log.info(f"Promoted user to superuser: {admin_email}")
        else:
            log.debug(f"Default admin already exists: {admin_email}")


async def get_async_session(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    session_maker = get_session_maker(settings.database_url)
    async with session_maker() as session:
        yield session


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
    """FastAPI dependency that yields the user database adapter."""
    yield SQLAlchemyUserDatabase[User, uuid.UUID](session, User)
