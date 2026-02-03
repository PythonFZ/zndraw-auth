"""Test fixtures for zndraw-auth."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from zndraw_auth import (
    UserCreate,
    UserRead,
    auth_backend,
    create_db_and_tables,
    fastapi_users,
    get_auth_settings,
)
from zndraw_auth.db import Base, get_engine
from zndraw_auth.settings import AuthSettings


@pytest.fixture
def test_settings() -> AuthSettings:
    """Settings with in-memory database."""
    return AuthSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="test-secret-key",
        reset_password_token_secret="test-reset-secret",
        verification_token_secret="test-verify-secret",
    )


@pytest.fixture
async def app(test_settings: AuthSettings) -> FastAPI:
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
async def client(app: FastAPI) -> AsyncClient:
    """Async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
