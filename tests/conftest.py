"""Test fixtures for zndraw-auth."""

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from zndraw_auth import (
    SessionDep,
    User,
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    current_active_user,
    current_optional_user,
    current_superuser,
    ensure_default_admin,
    fastapi_users,
    get_auth_settings,
    get_session,
    get_session_maker,
)
from zndraw_auth.db import Base
from zndraw_auth.settings import AuthSettings

# --- Shared Test Models ---


class LoginForm(BaseModel):
    """OAuth2 password login form data for testing.

    Uses grant_type=password for RFC 6749 OAuth2 password flow.
    """

    username: str  # email
    password: str
    grant_type: str = "password"
    scope: str = ""
    client_id: str | None = None
    client_secret: str | None = None


class TokenPair(BaseModel):
    """JWT token pair response."""

    access_token: str
    token_type: str = "bearer"


# --- Settings Fixtures ---


@pytest.fixture
def login_form_class() -> type:
    """Fixture that returns the LoginForm class for dependency injection."""
    return LoginForm


@pytest.fixture
def test_settings() -> AuthSettings:
    """Settings with in-memory database (production mode with admin configured)."""
    return AuthSettings(
        database_url="sqlite+aiosqlite://",
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
        database_url="sqlite+aiosqlite://",
        secret_key="test-secret-key",
        reset_password_token_secret="test-reset-secret",
        verification_token_secret="test-verify-secret",
        # Dev mode: no admin configured
    )


# --- App Fixtures ---


@pytest.fixture
async def app(test_settings: AuthSettings) -> AsyncGenerator[FastAPI, None]:
    """Create test FastAPI app with dependency overrides."""
    # Create test engine and session maker
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    app = FastAPI()

    # Store test engine in app.state
    app.state.engine = test_engine

    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create default admin user using the utility function
    async with test_session_maker() as session:
        await ensure_default_admin(session, test_settings)

    # Override settings dependency to use test settings
    app.dependency_overrides[get_auth_settings] = lambda: test_settings
    # Override session_maker to use test session_maker
    app.dependency_overrides[get_session_maker] = lambda: test_session_maker

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
    app.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
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
    async def optional_route(
        user: Annotated[User | None, Depends(current_optional_user)],
    ) -> dict[str, str | None]:
        """Route with optional authentication."""
        if user:
            return {"user_id": str(user.id), "authenticated": "true"}
        return {"user_id": None, "authenticated": "false"}

    @app.get("/test/session")
    async def session_route(
        session: SessionDep,
    ) -> dict[str, str]:
        """Route using async session dependency."""
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        return {"db_check": str(value)}

    yield app

    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async test client.

    HTTPX AsyncClient with ASGITransport automatically triggers the app's lifespan.
    """
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
    # Create test engine and session maker
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    app = FastAPI()

    # Store test engine in app.state
    app.state.engine = test_engine

    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # In dev mode, no admin is created (all users become superusers)

    # Override settings dependency to use test settings
    app.dependency_overrides[get_auth_settings] = lambda: test_settings_dev_mode
    # Override session_maker to use test session_maker
    app.dependency_overrides[get_session_maker] = lambda: test_session_maker

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
    app.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
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

    yield app

    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    app.dependency_overrides.clear()


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
