"""Tests for CLI login (device-code) flow."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_cli_login_challenge(client: AsyncClient) -> None:
    """POST /auth/cli-login creates a challenge with code and secret."""
    response = await client.post("/auth/cli-login")
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert "secret" in data
    assert "approve_url" in data
    assert len(data["code"]) == 8
