# ZnDraw-Auth: Shared FastAPI-Users Authentication Package

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a shared authentication package using fastapi-users that zndraw-fastapi and zndraw-joblib can import from directly.

**Architecture:** Follow the fastapi-users recommended structure with `db.py` (User model, session), `schemas.py` (Pydantic schemas), `users.py` (UserManager, auth backends, FastAPIUsers instance). Export `current_active_user`, `current_superuser`, `get_async_session` for other packages to use with `Depends()`.

**Tech Stack:** fastapi-users[sqlalchemy], SQLAlchemy async, pydantic-settings, pytest

---

## Package Structure

```
zndraw-auth/
├── pyproject.toml
├── src/
│   └── zndraw_auth/
│       ├── __init__.py      # Public exports
│       ├── db.py            # User model, engine, session
│       ├── schemas.py       # UserRead, UserCreate, UserUpdate
│       ├── users.py         # UserManager, auth backends, fastapi_users instance
│       └── settings.py      # Configuration (secrets, DB URL)
└── tests/
    ├── conftest.py
    └── test_auth.py
```

---

## Task 1: Update pyproject.toml

**Files:**
- Modify: `/Users/fzills/tools/zndraw-auth/pyproject.toml`

**Step 1: Add dependencies and package config**

```toml
[project]
name = "zndraw-auth"
version = "0.1.0"
description = "Shared authentication for ZnDraw using fastapi-users"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.128.0",
    "fastapi-users[sqlalchemy]>=14.0.0",
    "pydantic-settings>=2.0.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "aiosqlite>=0.19.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/zndraw_auth"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create src directory structure**

```bash
cd /Users/fzills/tools/zndraw-auth
mkdir -p src/zndraw_auth tests
touch src/zndraw_auth/__init__.py
rm main.py  # Remove skeleton file
```

**Step 3: Sync dependencies**

Run: `cd /Users/fzills/tools/zndraw-auth && uv sync`

**Step 4: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add -A
git commit -m "chore: set up package structure with fastapi-users"
```

---

## Task 2: Create Settings Module

**Files:**
- Create: `/Users/fzills/tools/zndraw-auth/src/zndraw_auth/settings.py`

**Step 1: Create settings.py**

```python
"""Configuration settings for zndraw-auth."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication settings loaded from environment variables.

    All settings can be overridden with ZNDRAW_AUTH_ prefix.
    Example: ZNDRAW_AUTH_SECRET_KEY=your-secret-key
    """

    model_config = SettingsConfigDict(
        env_prefix="ZNDRAW_AUTH_",
        env_file=".env",
        extra="ignore",
    )

    # JWT settings
    secret_key: SecretStr = SecretStr("CHANGE-ME-IN-PRODUCTION")
    token_lifetime_seconds: int = 3600  # 1 hour

    # Database
    database_url: str = "sqlite+aiosqlite:///./zndraw_auth.db"

    # Password reset / verification tokens
    reset_password_token_secret: SecretStr = SecretStr("CHANGE-ME-RESET")
    verification_token_secret: SecretStr = SecretStr("CHANGE-ME-VERIFY")


from functools import lru_cache

@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
```

**Step 2: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add src/zndraw_auth/settings.py
git commit -m "feat: add AuthSettings configuration"
```

---

## Task 3: Create Database Module

**Files:**
- Create: `/Users/fzills/tools/zndraw-auth/src/zndraw_auth/db.py`

**Step 1: Create db.py with User model and session**

```python
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
```

**Step 2: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add src/zndraw_auth/db.py
git commit -m "feat: add User model and database session management"
```

---

## Task 4: Create Schemas Module

**Files:**
- Create: `/Users/fzills/tools/zndraw-auth/src/zndraw_auth/schemas.py`

**Step 1: Create schemas.py**

```python
"""Pydantic schemas for user operations."""

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schema for reading user data (responses)."""

    pass


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user."""

    pass


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating an existing user."""

    pass
```

**Step 2: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add src/zndraw_auth/schemas.py
git commit -m "feat: add user schemas"
```

---

## Task 5: Create Users Module (Core)

**Files:**
- Create: `/Users/fzills/tools/zndraw-auth/src/zndraw_auth/users.py`

**Step 1: Create users.py with UserManager, backends, and FastAPIUsers**

```python
"""FastAPI-Users configuration and exported dependencies.

This module exports the key dependencies that other packages should import:
- current_active_user: Depends() for authenticated active user
- current_superuser: Depends() for authenticated superuser
- fastapi_users: The FastAPIUsers instance for including routers
- auth_backend: The JWT authentication backend

Example usage in other packages:
    from zndraw_auth import current_active_user, User

    @router.get("/protected")
    async def protected_route(user: User = Depends(current_active_user)):
        return {"user_id": str(user.id)}
"""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase

from zndraw_auth.db import User, get_user_db
from zndraw_auth.settings import AuthSettings, get_auth_settings


# --- User Manager ---


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Custom user manager with lifecycle hooks.

    Token secrets are set via dependency injection in get_user_manager.
    """

    reset_password_token_secret: str
    verification_token_secret: str

    async def on_after_register(
        self, user: User, request: Request | None = None
    ) -> None:
        """Called after successful registration."""
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Called after password reset requested."""
        print(f"User {user.id} forgot password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Called after verification requested."""
        print(f"Verification requested for {user.id}. Token: {token}")


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> UserManager:
    """FastAPI dependency that yields the user manager."""
    manager = UserManager(user_db)
    manager.reset_password_token_secret = settings.reset_password_token_secret.get_secret_value()
    manager.verification_token_secret = settings.verification_token_secret.get_secret_value()
    yield manager


# --- Authentication Backend ---


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> JWTStrategy:
    """Get JWT strategy with settings."""
    return JWTStrategy(
        secret=settings.secret_key.get_secret_value(),
        lifetime_seconds=settings.token_lifetime_seconds,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


# --- FastAPI Users Instance ---


fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)


# --- Exported Dependencies ---
# These are the main exports that other packages should use

current_active_user = fastapi_users.current_user(active=True)
"""Dependency for routes requiring an authenticated active user.

Usage:
    @router.get("/protected")
    async def route(user: User = Depends(current_active_user)):
        ...
"""

current_superuser = fastapi_users.current_user(active=True, superuser=True)
"""Dependency for routes requiring superuser privileges.

Usage:
    @router.get("/admin")
    async def route(user: User = Depends(current_superuser)):
        ...
"""

current_optional_user = fastapi_users.current_user(active=True, optional=True)
"""Dependency for routes with optional authentication.

Usage:
    @router.get("/public")
    async def route(user: User | None = Depends(current_optional_user)):
        ...
"""
```

**Step 2: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add src/zndraw_auth/users.py
git commit -m "feat: add UserManager, auth backend, and FastAPIUsers instance"
```

---

## Task 6: Create Public API (__init__.py)

**Files:**
- Modify: `/Users/fzills/tools/zndraw-auth/src/zndraw_auth/__init__.py`

**Step 1: Export public API**

```python
"""ZnDraw Auth - Shared authentication for ZnDraw ecosystem.

Example usage:
    from zndraw_auth import (
        current_active_user,
        current_superuser,
        fastapi_users,
        auth_backend,
        get_async_session,
        create_db_and_tables,
        User,
        UserRead,
        UserCreate,
    )

    # In your FastAPI app:
    app.include_router(
        fastapi_users.get_auth_router(auth_backend),
        prefix="/auth/jwt",
        tags=["auth"],
    )

    @app.get("/protected")
    async def protected(user: User = Depends(current_active_user)):
        return {"user_id": str(user.id)}
"""

from zndraw_auth.db import (
    User,
    create_db_and_tables,
    get_async_session,
    get_user_db,
)
from zndraw_auth.schemas import UserCreate, UserRead, UserUpdate
from zndraw_auth.settings import AuthSettings, get_auth_settings
from zndraw_auth.users import (
    UserManager,
    auth_backend,
    current_active_user,
    current_optional_user,
    current_superuser,
    fastapi_users,
    get_user_manager,
)

__all__ = [
    # User model
    "User",
    # Database
    "create_db_and_tables",
    "get_async_session",
    "get_user_db",
    # Schemas
    "UserCreate",
    "UserRead",
    "UserUpdate",
    # Settings
    "AuthSettings",
    "get_auth_settings",
    # User manager
    "UserManager",
    "get_user_manager",
    # Auth backend
    "auth_backend",
    # FastAPIUsers instance
    "fastapi_users",
    # Dependencies for Depends()
    "current_active_user",
    "current_superuser",
    "current_optional_user",
]
```

**Step 2: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add src/zndraw_auth/__init__.py
git commit -m "feat: export public API"
```

---

## Task 7: Create Tests

**Files:**
- Create: `/Users/fzills/tools/zndraw-auth/tests/conftest.py`
- Create: `/Users/fzills/tools/zndraw-auth/tests/test_auth.py`

**Step 1: Create conftest.py**

```python
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
```

**Step 2: Create test_auth.py**

```python
"""Tests for authentication flows."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """Test user registration."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "testpassword123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data
    assert data["is_active"] is True
    assert data["is_superuser"] is False


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    """Test user login."""
    # Register first
    await client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "testpassword123"},
    )

    # Login
    response = await client.post(
        "/auth/jwt/login",
        data={"username": "login@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    """Test login with wrong password."""
    # Register
    await client.post(
        "/auth/register",
        json={"email": "wrong@example.com", "password": "correctpassword"},
    )

    # Login with wrong password
    response = await client.post(
        "/auth/jwt/login",
        data={"username": "wrong@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test registering with existing email."""
    # Register first user
    await client.post(
        "/auth/register",
        json={"email": "dupe@example.com", "password": "password123"},
    )

    # Try to register again
    response = await client.post(
        "/auth/register",
        json={"email": "dupe@example.com", "password": "password456"},
    )
    assert response.status_code == 400
```

**Step 3: Commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add tests/
git commit -m "test: add authentication tests"
```

---

## Task 8: Run Tests and Verify

**Step 1: Install dev dependencies**

Run: `cd /Users/fzills/tools/zndraw-auth && uv sync --extra dev`

**Step 2: Run tests**

Run: `cd /Users/fzills/tools/zndraw-auth && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 3: Verify imports work**

Run: `cd /Users/fzills/tools/zndraw-auth && uv run python -c "from zndraw_auth import current_active_user, User, fastapi_users; print('OK')"`

**Step 4: Final commit**

```bash
cd /Users/fzills/tools/zndraw-auth
git add -A
git commit -m "chore: complete zndraw-auth package"
```

---

## Summary: What zndraw-auth Exports

Other packages import like this:

```python
from zndraw_auth import (
    # For Depends() in routes
    current_active_user,    # Active authenticated user
    current_superuser,      # Superuser only
    current_optional_user,  # User | None
    get_async_session,      # Database session

    # For type hints
    User,                   # User model

    # For including auth routers
    fastapi_users,          # FastAPIUsers instance
    auth_backend,           # JWT backend

    # For schemas
    UserRead,
    UserCreate,
    UserUpdate,

    # For app setup
    create_db_and_tables,
)
```

**Next steps after this plan:**
1. Update zndraw-joblib to import from zndraw-auth
2. Update zndraw-fastapi to import from zndraw-auth
