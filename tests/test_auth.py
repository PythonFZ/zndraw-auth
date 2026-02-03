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
