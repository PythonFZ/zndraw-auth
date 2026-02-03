"""Test fixtures for zndraw-auth."""

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from zndraw_auth import (
    User,
    UserCreate,
    UserRead,
    auth_backend,
    create_db_and_tables,
    current_active_user,
    current_optional_user,
    current_superuser,
    fastapi_users,
    get_async_session,
    get_auth_settings,
)
from zndraw_auth.db import Base, get_engine
from zndraw_auth.settings import AuthSettings


@pytest.fixture
def test_settings() -> AuthSettings:
    """Settings with in-memory database (production mode with admin configured)."""
    return AuthSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="test-secret-key",
        reset_password_token_secret="test-reset-secret",
        verification_token_secret="test-verify-secret",
        # Production mode: admin configured, new users are NOT superusers
        default_admin_email="admin@test.com",
        default_admin_password="admin-password",
    )


@pytest.fixture
def test_settings_dev_mode() -> AuthSettings:
    """Settings in dev mode (no admin configured, all users become superusers)."""
    return AuthSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="test-secret-key",
        reset_password_token_secret="test-reset-secret",
        verification_token_secret="test-verify-secret",
        # Dev mode: no admin configured
    )


@pytest.fixture
async def app(test_settings: AuthSettings) -> AsyncGenerator[FastAPI, None]:
    """Create test FastAPI app with dependency overrides."""
    app = FastAPI()

    # Override settings dependency to use test settings
    app.dependency_overrides[get_auth_settings] = lambda: test_settings

    # Create tables for this test's database
    await create_db_and_tables(test_settings)

    # Include auth routers
    app.include_router(
        fastapi_users.get_auth_router(auth_backend),
        prefix="/auth/jwt",
        tags=["auth"],
    )
    app.include_router(
        fastapi_users.get_register_router(UserRead, UserCreate),
        prefix="/auth",
        tags=["auth"],
    )

    # Test routes for dependency injection
    @app.get("/test/protected")
    async def protected_route(
        user: Annotated[User, Depends(current_active_user)],
    ) -> dict[str, str]:
        """Route requiring authenticated active user."""
        return {"user_id": str(user.id), "email": user.email}

    @app.get("/test/superuser")
    async def superuser_route(
        user: Annotated[User, Depends(current_superuser)],
    ) -> dict[str, str]:
        """Route requiring superuser."""
        return {"user_id": str(user.id), "is_superuser": str(user.is_superuser)}

    @app.get("/test/optional")
    async def optional_auth_route(
        user: Annotated[User | None, Depends(current_optional_user)],
    ) -> dict[str, str | None]:
        """Route with optional authentication."""
        if user:
            return {"user_id": str(user.id), "authenticated": "true"}
        return {"user_id": None, "authenticated": "false"}

    @app.get("/test/session")
    async def session_route(
        session: Annotated[AsyncSession, Depends(get_async_session)],
    ) -> dict[str, str]:
        """Route using async session dependency."""
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        return {"db_check": str(value)}

    yield app

    # Cleanup: drop all tables and clear caches
    engine = get_engine(test_settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Clear lru_cache to ensure fresh engine/session for next test
    get_engine.cache_clear()
    from zndraw_auth.db import get_session_maker

    get_session_maker.cache_clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def app_dev_mode(
    test_settings_dev_mode: AuthSettings,
) -> AsyncGenerator[FastAPI, None]:
    """Create test FastAPI app in dev mode (all users become superusers)."""
    app = FastAPI()

    # Override settings dependency to use test settings
    settings = test_settings_dev_mode
    app.dependency_overrides[get_auth_settings] = lambda: settings

    # Create tables for this test's database
    await create_db_and_tables(test_settings_dev_mode)

    # Include auth routers
    app.include_router(
        fastapi_users.get_auth_router(auth_backend),
        prefix="/auth/jwt",
        tags=["auth"],
    )
    app.include_router(
        fastapi_users.get_register_router(UserRead, UserCreate),
        prefix="/auth",
        tags=["auth"],
    )

    # Test route for superuser check
    @app.get("/test/superuser")
    async def superuser_route(
        user: Annotated[User, Depends(current_superuser)],
    ) -> dict[str, str]:
        """Route requiring superuser."""
        return {"user_id": str(user.id), "is_superuser": str(user.is_superuser)}

    yield app

    # Cleanup: drop all tables and clear caches
    engine = get_engine(test_settings_dev_mode.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Clear lru_cache to ensure fresh engine/session for next test
    get_engine.cache_clear()
    from zndraw_auth.db import get_session_maker

    get_session_maker.cache_clear()


@pytest.fixture
async def client_dev_mode(
    app_dev_mode: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    """Async test client in dev mode (all users become superusers)."""
    async with AsyncClient(
        transport=ASGITransport(app=app_dev_mode),
        base_url="http://test",
    ) as client:
        yield client
