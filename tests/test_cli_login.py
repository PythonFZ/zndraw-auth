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


@pytest.mark.asyncio
async def test_poll_pending_challenge(client: AsyncClient) -> None:
    """GET /auth/cli-login/{code} returns pending when not yet approved."""
    create = await client.post("/auth/cli-login")
    data = create.json()

    response = await client.get(
        f"/auth/cli-login/{data['code']}",
        params={"secret": data["secret"]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json().get("token") is None


@pytest.mark.asyncio
async def test_poll_wrong_secret(client: AsyncClient) -> None:
    """GET /auth/cli-login/{code} with wrong secret returns 404."""
    create = await client.post("/auth/cli-login")
    data = create.json()

    response = await client.get(
        f"/auth/cli-login/{data['code']}",
        params={"secret": "wrong-secret"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_poll_nonexistent_code(client: AsyncClient) -> None:
    """GET /auth/cli-login/{code} with unknown code returns 404."""
    response = await client.get(
        "/auth/cli-login/ZZZZZZZZ",
        params={"secret": "doesnt-matter"},
    )
    assert response.status_code == 404
