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
