"""Tests for authentication flows."""

import pytest
from httpx import AsyncClient

from zndraw_auth import UserCreate, UserRead


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """Test user registration."""
    user_data = UserCreate(email="test@example.com", password="testpassword123")
    response = await client.post(
        "/auth/register",
        json=user_data.model_dump(),
    )
    assert response.status_code == 201
    user = UserRead.model_validate(response.json())
    assert user.email == "test@example.com"
    assert user.id is not None
    assert user.is_active is True
    assert user.is_superuser is False


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    """Test user login."""
    # Register first
    user_data = UserCreate(email="login@example.com", password="testpassword123")
    await client.post("/auth/register", json=user_data.model_dump())

    # Login
    response = await client.post(
        "/auth/jwt/login",
        data={"username": user_data.email, "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    """Test login with wrong password."""
    # Register
    user_data = UserCreate(email="wrong@example.com", password="correctpassword")
    await client.post("/auth/register", json=user_data.model_dump())

    # Login with wrong password
    response = await client.post(
        "/auth/jwt/login",
        data={"username": user_data.email, "password": "wrongpassword"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test registering with existing email."""
    # Register first user
    user_data = UserCreate(email="dupe@example.com", password="password123")
    await client.post("/auth/register", json=user_data.model_dump())

    # Try to register again with same email
    duplicate_data = UserCreate(email="dupe@example.com", password="password456")
    response = await client.post("/auth/register", json=duplicate_data.model_dump())
    assert response.status_code == 400


# --- Tests for exported dependency injections ---


async def _get_auth_header(
    client: AsyncClient, email: str, password: str
) -> dict[str, str]:
    """Helper to register, login, and return auth header."""
    user_data = UserCreate(email=email, password=password)
    await client.post("/auth/register", json=user_data.model_dump())
    response = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_current_active_user_dependency(client: AsyncClient):
    """Test current_active_user dependency injection."""
    headers = await _get_auth_header(client, "active@example.com", "password123")

    response = await client.get("/test/protected", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "active@example.com"
    assert "user_id" in data


@pytest.mark.asyncio
async def test_current_active_user_unauthorized(client: AsyncClient):
    """Test current_active_user rejects unauthenticated requests."""
    response = await client.get("/test/protected")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_current_superuser_forbidden(client: AsyncClient):
    """Test current_superuser rejects non-superusers."""
    headers = await _get_auth_header(client, "regular@example.com", "password123")

    response = await client.get("/test/superuser", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_current_optional_user_authenticated(client: AsyncClient):
    """Test current_optional_user with authenticated user."""
    headers = await _get_auth_header(client, "optional@example.com", "password123")

    response = await client.get("/test/optional", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] == "true"
    assert data["user_id"] is not None


@pytest.mark.asyncio
async def test_current_optional_user_anonymous(client: AsyncClient):
    """Test current_optional_user without authentication."""
    response = await client.get("/test/optional")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] == "false"
    assert data["user_id"] is None


@pytest.mark.asyncio
async def test_get_async_session_dependency(client: AsyncClient):
    """Test get_async_session dependency injection."""
    response = await client.get("/test/session")
    assert response.status_code == 200
    data = response.json()
    assert data["db_check"] == "1"
