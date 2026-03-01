# CLI Authentication Endpoints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add CLI login (device-code flow) and admin token minting endpoints to zndraw-auth.

**Architecture:** Two new APIRouters (`cli_login_router`, `admin_token_router`) with a new `CLILoginChallenge` SQLModel table. JWT minting uses pyjwt directly (same secret/algo as fastapi-users `JWTStrategy`). All new code follows the existing pure-DI pattern (settings/session from `app.state`).

**Tech Stack:** FastAPI, SQLModel, pyjwt, fastapi-users dependencies, pytest + httpx for testing.

---

### Task 1: Add CLILoginChallenge Model

**Files:**
- Modify: `src/zndraw_auth/db.py:20` (add import) and after line 45 (add model)

**Step 1: Write the failing test**

Create `tests/test_cli_login.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_login.py::test_create_cli_login_challenge -v`
Expected: FAIL — 404 because the endpoint doesn't exist yet.

**Step 3: Write the model**

In `src/zndraw_auth/db.py`, add after the `User` class (after line 45):

```python
import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel  # SQLModel already imported at line 20


class CLILoginChallenge(SQLModel, table=True):
    """Challenge for device-code style CLI login flow.

    Lifecycle: pending -> approved -> redeemed
    On redeem: token and secret are nulled, row kept for audit.
    """

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    secret: str | None = None
    status: str = "pending"
    token: str | None = None
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    created_at: datetime
    expires_at: datetime
```

Note: `uuid` is already imported at line 4. `SQLModel` is already imported at line 20. Add `Field` to the existing `from sqlmodel import SQLModel` import and add `from datetime import datetime`.

**Step 4: Write the schemas**

In `src/zndraw_auth/schemas.py`, add after line 42:

```python
from typing import Literal


class CLILoginCreateResponse(BaseModel):
    """Response from creating a CLI login challenge."""

    code: str
    secret: str
    approve_url: str


class CLILoginStatusResponse(BaseModel):
    """Response from polling a CLI login challenge."""

    status: str
    token: str | None = None


class ImpersonationTokenResponse(BaseModel):
    """Response from admin token minting."""

    access_token: str
    token_type: str = "bearer"
```

**Step 5: Write the minimal router (POST only)**

Create `src/zndraw_auth/cli_login.py`:

```python
"""CLI login (device-code flow) router."""

import logging
import secrets
import string
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from zndraw_auth.db import CLILoginChallenge, get_session
from zndraw_auth.schemas import CLILoginCreateResponse

log = logging.getLogger(__name__)

cli_login_router = APIRouter()

CHALLENGE_LIFETIME_SECONDS = 300  # 5 minutes
CODE_LENGTH = 8
CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@cli_login_router.post("", response_model=CLILoginCreateResponse)
async def create_cli_login_challenge(
    session: AsyncSession = Depends(get_session),
) -> CLILoginCreateResponse:
    """Create a CLI login challenge (no auth required)."""
    now = datetime.now(timezone.utc)
    code = _generate_code()
    secret = secrets.token_urlsafe(32)

    challenge = CLILoginChallenge(
        code=code,
        secret=secret,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(seconds=CHALLENGE_LIFETIME_SECONDS),
    )
    session.add(challenge)
    await session.commit()

    return CLILoginCreateResponse(
        code=code,
        secret=secret,
        approve_url=f"/auth/cli-login/{code}",
    )
```

**Step 6: Update conftest.py to include the new router**

In `tests/conftest.py`, add import after line 27:

```python
from zndraw_auth.cli_login import cli_login_router
```

In `_create_test_app`, add after line 133 (after users router include):

```python
    app.include_router(cli_login_router, prefix="/auth/cli-login", tags=["auth"])
```

**Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_login.py::test_create_cli_login_challenge -v`
Expected: PASS

**Step 8: Run all existing tests to verify no regressions**

Run: `uv run pytest -v`
Expected: All existing tests pass.

**Step 9: Commit**

```bash
git add src/zndraw_auth/db.py src/zndraw_auth/schemas.py src/zndraw_auth/cli_login.py tests/conftest.py tests/test_cli_login.py
git commit -m "feat: add CLILoginChallenge model and POST /auth/cli-login endpoint"
```

---

### Task 2: CLI Login Poll Endpoint (GET)

**Files:**
- Modify: `src/zndraw_auth/cli_login.py` (add GET endpoint)
- Modify: `tests/test_cli_login.py` (add poll tests)

**Step 1: Write failing tests**

Add to `tests/test_cli_login.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_login.py -k "poll" -v`
Expected: FAIL — 405 Method Not Allowed (GET not implemented).

**Step 3: Write the GET endpoint**

Add to `src/zndraw_auth/cli_login.py`:

```python
from fastapi import HTTPException, Query
from sqlalchemy import select
from zndraw_auth.schemas import CLILoginStatusResponse


@cli_login_router.get("/{code}", response_model=CLILoginStatusResponse)
async def poll_cli_login_challenge(
    code: str,
    secret: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> CLILoginStatusResponse:
    """Poll a CLI login challenge status (no auth, secret required)."""
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(CLILoginChallenge).where(CLILoginChallenge.code == code)
    )
    challenge = result.scalar_one_or_none()

    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.secret != secret:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if now > challenge.expires_at:
        raise HTTPException(status_code=410, detail="Challenge expired")

    if challenge.status == "redeemed":
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.status == "approved" and challenge.token is not None:
        token = challenge.token
        # Redeem: null sensitive fields, keep row for audit
        challenge.token = None
        challenge.secret = None
        challenge.status = "redeemed"
        await session.commit()
        return CLILoginStatusResponse(status="approved", token=token)

    return CLILoginStatusResponse(status="pending")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_login.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/zndraw_auth/cli_login.py tests/test_cli_login.py
git commit -m "feat: add GET /auth/cli-login/{code} poll endpoint"
```

---

### Task 3: CLI Login Approve Endpoint (PATCH)

**Files:**
- Modify: `src/zndraw_auth/cli_login.py` (add PATCH endpoint)
- Modify: `tests/test_cli_login.py` (add approve + full flow tests)

**Step 1: Write failing tests**

We need a helper to get an auth header. Reuse the pattern from `tests/test_auth.py:72-81`:

Add to `tests/test_cli_login.py`:

```python
from zndraw_auth import TokenResponse, UserCreate


async def _get_auth_header(
    client: AsyncClient, email: str, password: str
) -> dict[str, str]:
    """Register, login, return auth header."""
    user_data = UserCreate(email=email, password=password)
    await client.post("/auth/register", json=user_data.model_dump())
    response = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password, "grant_type": "password"},
    )
    token = TokenResponse.model_validate(response.json())
    return {"Authorization": f"Bearer {token.access_token}"}


@pytest.mark.asyncio
async def test_approve_challenge(client: AsyncClient) -> None:
    """PATCH /auth/cli-login/{code} approves and mints a token."""
    # Create challenge
    create = await client.post("/auth/cli-login")
    data = create.json()

    # Approve as authenticated user
    headers = await _get_auth_header(client, "cli-user@test.com", "password123")
    response = await client.patch(
        f"/auth/cli-login/{data['code']}",
        headers=headers,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_approve_requires_auth(client: AsyncClient) -> None:
    """PATCH /auth/cli-login/{code} without auth returns 401."""
    create = await client.post("/auth/cli-login")
    data = create.json()

    response = await client.patch(f"/auth/cli-login/{data['code']}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_full_cli_login_flow(client: AsyncClient) -> None:
    """Full flow: create -> approve -> poll gets token -> token works."""
    # 1. CLI creates challenge
    create = await client.post("/auth/cli-login")
    challenge = create.json()

    # 2. Browser user approves
    headers = await _get_auth_header(client, "browser@test.com", "password123")
    approve = await client.patch(
        f"/auth/cli-login/{challenge['code']}",
        headers=headers,
    )
    assert approve.status_code == 200

    # 3. CLI polls and gets token
    poll = await client.get(
        f"/auth/cli-login/{challenge['code']}",
        params={"secret": challenge["secret"]},
    )
    assert poll.status_code == 200
    poll_data = poll.json()
    assert poll_data["status"] == "approved"
    assert poll_data["token"] is not None

    # 4. Token works for authenticated endpoints
    cli_headers = {"Authorization": f"Bearer {poll_data['token']}"}
    me = await client.get("/test/protected", headers=cli_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "browser@test.com"


@pytest.mark.asyncio
async def test_poll_after_redeem_returns_404(client: AsyncClient) -> None:
    """Second poll after redeem returns 404 (one-time retrieval)."""
    # Create + approve
    create = await client.post("/auth/cli-login")
    challenge = create.json()
    headers = await _get_auth_header(client, "redeem@test.com", "password123")
    await client.patch(
        f"/auth/cli-login/{challenge['code']}",
        headers=headers,
    )

    # First poll: gets token
    poll1 = await client.get(
        f"/auth/cli-login/{challenge['code']}",
        params={"secret": challenge["secret"]},
    )
    assert poll1.status_code == 200
    assert poll1.json()["status"] == "approved"

    # Second poll: 404
    poll2 = await client.get(
        f"/auth/cli-login/{challenge['code']}",
        params={"secret": challenge["secret"]},
    )
    assert poll2.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_login.py -k "approve or full_cli or redeem" -v`
Expected: FAIL — 405 Method Not Allowed (PATCH not implemented).

**Step 3: Write the PATCH endpoint**

Add to `src/zndraw_auth/cli_login.py`:

```python
import uuid
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends

from zndraw_auth.db import User
from zndraw_auth.settings import AuthSettings, get_auth_settings
from zndraw_auth.users import current_active_user


@cli_login_router.patch("/{code}", status_code=200)
async def approve_cli_login_challenge(
    code: str,
    user: Annotated[User, Depends(current_active_user)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Approve a CLI login challenge (browser user, auth required)."""
    result = await session.execute(
        select(CLILoginChallenge).where(CLILoginChallenge.code == code)
    )
    challenge = result.scalar_one_or_none()

    if challenge is None or challenge.status != "pending":
        raise HTTPException(status_code=404, detail="Challenge not found")

    now = datetime.now(timezone.utc)
    if now > challenge.expires_at:
        raise HTTPException(status_code=410, detail="Challenge expired")

    # Mint JWT for the approving user
    token = _mint_jwt(
        user_id=user.id,
        secret=settings.secret_key.get_secret_value(),
        lifetime_seconds=settings.token_lifetime_seconds,
    )

    challenge.token = token
    challenge.user_id = user.id
    challenge.status = "approved"
    await session.commit()

    log.info("CLI login approved: user %s, code %s", user.id, code)
    return {"status": "approved"}


def _mint_jwt(
    user_id: uuid.UUID,
    secret: str,
    lifetime_seconds: int,
    *,
    extra_claims: dict | None = None,
) -> str:
    """Mint a JWT compatible with fastapi-users JWTStrategy."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "aud": "fastapi-users:auth",
        "iat": now,
        "exp": now + timedelta(seconds=lifetime_seconds),
    }
    if extra_claims:
        payload.update(extra_claims)
    return pyjwt.encode(payload, secret, algorithm="HS256")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_login.py -v`
Expected: All pass.

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

**Step 6: Commit**

```bash
git add src/zndraw_auth/cli_login.py tests/test_cli_login.py
git commit -m "feat: add PATCH /auth/cli-login/{code} approve endpoint with full flow"
```

---

### Task 4: CLI Login Reject Endpoint (DELETE)

**Files:**
- Modify: `src/zndraw_auth/cli_login.py` (add DELETE endpoint)
- Modify: `tests/test_cli_login.py` (add reject tests)

**Step 1: Write failing test**

Add to `tests/test_cli_login.py`:

```python
@pytest.mark.asyncio
async def test_reject_challenge(client: AsyncClient) -> None:
    """DELETE /auth/cli-login/{code} rejects, subsequent poll returns 404."""
    create = await client.post("/auth/cli-login")
    challenge = create.json()

    headers = await _get_auth_header(client, "rejector@test.com", "password123")
    response = await client.delete(
        f"/auth/cli-login/{challenge['code']}",
        headers=headers,
    )
    assert response.status_code == 204

    # Poll returns 404
    poll = await client.get(
        f"/auth/cli-login/{challenge['code']}",
        params={"secret": challenge["secret"]},
    )
    assert poll.status_code == 404


@pytest.mark.asyncio
async def test_reject_requires_auth(client: AsyncClient) -> None:
    """DELETE /auth/cli-login/{code} without auth returns 401."""
    create = await client.post("/auth/cli-login")
    challenge = create.json()

    response = await client.delete(f"/auth/cli-login/{challenge['code']}")
    assert response.status_code == 401
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_login.py -k "reject" -v`
Expected: FAIL — 405 Method Not Allowed.

**Step 3: Write the DELETE endpoint**

Add to `src/zndraw_auth/cli_login.py`:

```python
from fastapi import Response


@cli_login_router.delete("/{code}", status_code=204)
async def reject_cli_login_challenge(
    code: str,
    user: Annotated[User, Depends(current_active_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Reject a CLI login challenge (browser user, auth required)."""
    result = await session.execute(
        select(CLILoginChallenge).where(CLILoginChallenge.code == code)
    )
    challenge = result.scalar_one_or_none()

    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    await session.delete(challenge)
    await session.commit()

    log.info("CLI login rejected: by user %s, code %s", user.id, code)
    return Response(status_code=204)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_login.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/zndraw_auth/cli_login.py tests/test_cli_login.py
git commit -m "feat: add DELETE /auth/cli-login/{code} reject endpoint"
```

---

### Task 5: Expired Challenge Handling

**Files:**
- Modify: `tests/test_cli_login.py` (add expiry tests)
- Modify: `src/zndraw_auth/cli_login.py` (add cleanup in POST)

**Step 1: Write failing test**

Add to `tests/test_cli_login.py`:

```python
from unittest.mock import patch
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_poll_expired_challenge(client: AsyncClient) -> None:
    """GET /auth/cli-login/{code} returns 410 when challenge is expired."""
    create = await client.post("/auth/cli-login")
    challenge = create.json()

    # Fast-forward time past expiry
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    with patch("zndraw_auth.cli_login.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        response = await client.get(
            f"/auth/cli-login/{challenge['code']}",
            params={"secret": challenge["secret"]},
        )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_approve_expired_challenge(client: AsyncClient) -> None:
    """PATCH /auth/cli-login/{code} returns 410 when challenge is expired."""
    create = await client.post("/auth/cli-login")
    challenge = create.json()

    headers = await _get_auth_header(client, "expired@test.com", "password123")

    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    with patch("zndraw_auth.cli_login.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        response = await client.patch(
            f"/auth/cli-login/{challenge['code']}",
            headers=headers,
        )
    assert response.status_code == 410
```

**Step 2: Run tests to verify they pass**

These tests should already pass because the GET and PATCH endpoints already check `expires_at`. Run to confirm:

Run: `uv run pytest tests/test_cli_login.py -k "expired" -v`
Expected: PASS (if the datetime mock works correctly with the existing expiry checks). If not, adjust the mock or the endpoint code.

**Step 3: Commit**

```bash
git add tests/test_cli_login.py
git commit -m "test: add expiry tests for CLI login challenge"
```

---

### Task 6: Admin Token Minting Endpoint

**Files:**
- Create: `src/zndraw_auth/admin.py`
- Create: `tests/test_admin_token.py`
- Modify: `tests/conftest.py` (include admin router)

**Step 1: Write failing tests**

Create `tests/test_admin_token.py`:

```python
"""Tests for admin token minting."""

import pytest
from httpx import AsyncClient

from zndraw_auth import TokenResponse, UserCreate, UserRead


async def _get_auth_header(
    client: AsyncClient, email: str, password: str
) -> dict[str, str]:
    """Register, login, return auth header."""
    user_data = UserCreate(email=email, password=password)
    await client.post("/auth/register", json=user_data.model_dump())
    response = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password, "grant_type": "password"},
    )
    token = TokenResponse.model_validate(response.json())
    return {"Authorization": f"Bearer {token.access_token}"}


async def _get_admin_header(client: AsyncClient) -> dict[str, str]:
    """Login as the pre-created admin (admin@test.com / admin-password)."""
    response = await client.post(
        "/auth/jwt/login",
        data={
            "username": "admin@test.com",
            "password": "admin-password",
            "grant_type": "password",
        },
    )
    token = TokenResponse.model_validate(response.json())
    return {"Authorization": f"Bearer {token.access_token}"}


@pytest.mark.asyncio
async def test_admin_mint_token_for_user(client: AsyncClient) -> None:
    """Superuser can mint a token for another user."""
    # Create a regular user
    user_data = UserCreate(email="target@test.com", password="password123")
    reg = await client.post("/auth/register", json=user_data.model_dump())
    target_user = UserRead.model_validate(reg.json())

    # Admin mints token for the target user
    admin_headers = await _get_admin_header(client)
    response = await client.post(
        f"/admin/users/{target_user.id}/token",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # The minted token works as the target user
    cli_headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await client.get("/test/protected", headers=cli_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "target@test.com"


@pytest.mark.asyncio
async def test_admin_mint_token_non_superuser_forbidden(
    client: AsyncClient,
) -> None:
    """Non-superuser cannot mint tokens."""
    # Create regular user and get their header
    headers = await _get_auth_header(client, "regular@test.com", "password123")

    # Register another user to target
    user_data = UserCreate(email="other@test.com", password="password123")
    reg = await client.post("/auth/register", json=user_data.model_dump())
    target = UserRead.model_validate(reg.json())

    response = await client.post(
        f"/admin/users/{target.id}/token",
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_mint_token_target_not_found(client: AsyncClient) -> None:
    """Minting token for nonexistent user returns 404."""
    admin_headers = await _get_admin_header(client)
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/admin/users/{fake_id}/token",
        headers=admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_mint_token_has_impersonated_by_claim(
    client: AsyncClient,
) -> None:
    """Minted token contains impersonated_by claim with admin's UUID."""
    import jwt as pyjwt

    # Create target user
    user_data = UserCreate(email="claimed@test.com", password="password123")
    reg = await client.post("/auth/register", json=user_data.model_dump())
    target = UserRead.model_validate(reg.json())

    # Admin mints token
    admin_headers = await _get_admin_header(client)
    response = await client.post(
        f"/admin/users/{target.id}/token",
        headers=admin_headers,
    )
    data = response.json()

    # Decode without verification to inspect claims
    claims = pyjwt.decode(
        data["access_token"],
        options={"verify_signature": False},
    )
    assert claims["sub"] == str(target.id)
    assert "impersonated_by" in claims


@pytest.mark.asyncio
async def test_admin_mint_token_unauthenticated(client: AsyncClient) -> None:
    """Unauthenticated request to admin endpoint returns 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(f"/admin/users/{fake_id}/token")
    assert response.status_code == 401
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_token.py -v`
Expected: FAIL — 404 because the admin router doesn't exist.

**Step 3: Write the admin router**

Create `src/zndraw_auth/admin.py`:

```python
"""Admin token minting router."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from zndraw_auth.db import User, get_session
from zndraw_auth.schemas import ImpersonationTokenResponse
from zndraw_auth.settings import AuthSettings, get_auth_settings
from zndraw_auth.users import current_superuser

log = logging.getLogger(__name__)

admin_token_router = APIRouter()


@admin_token_router.post(
    "/users/{user_id}/token",
    response_model=ImpersonationTokenResponse,
)
async def mint_token_for_user(
    user_id: uuid.UUID,
    admin: Annotated[User, Depends(current_superuser)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    session: AsyncSession = Depends(get_session),
) -> ImpersonationTokenResponse:
    """Mint a JWT for the target user (superuser only)."""
    target = await session.get(User, user_id)

    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(target.id),
        "aud": "fastapi-users:auth",
        "iat": now,
        "exp": now + timedelta(seconds=settings.token_lifetime_seconds),
        "impersonated_by": str(admin.id),
    }
    token = pyjwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm="HS256"
    )

    log.info("Admin %s minted token for user %s", admin.id, target.id)

    return ImpersonationTokenResponse(access_token=token)
```

**Step 4: Update conftest.py to include admin router**

In `tests/conftest.py`, add import after the cli_login_router import:

```python
from zndraw_auth.admin import admin_token_router
```

In `_create_test_app`, add after the cli_login_router include:

```python
    app.include_router(admin_token_router, prefix="/admin", tags=["admin"])
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_token.py -v`
Expected: All pass.

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

**Step 7: Commit**

```bash
git add src/zndraw_auth/admin.py tests/test_admin_token.py tests/conftest.py
git commit -m "feat: add POST /admin/users/{user_id}/token impersonation endpoint"
```

---

### Task 7: Update Exports

**Files:**
- Modify: `src/zndraw_auth/__init__.py`
- Modify: `src/zndraw_auth/schemas.py` (verify imports work)

**Step 1: Write failing test**

Add to `tests/test_cli_login.py` (at the top, as a module-level import test):

```python
@pytest.mark.asyncio
async def test_routers_importable_from_package() -> None:
    """cli_login_router and admin_token_router are importable from zndraw_auth."""
    from zndraw_auth import admin_token_router, cli_login_router

    assert cli_login_router is not None
    assert admin_token_router is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_login.py::test_routers_importable_from_package -v`
Expected: FAIL — ImportError because `__init__.py` doesn't export them yet.

**Step 3: Update `__init__.py`**

In `src/zndraw_auth/__init__.py`, add imports after line 38 (schemas import):

```python
from zndraw_auth.admin import admin_token_router
from zndraw_auth.cli_login import cli_login_router
from zndraw_auth.schemas import (
    CLILoginCreateResponse,
    CLILoginStatusResponse,
    ImpersonationTokenResponse,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
```

Replace the existing line 38 (`from zndraw_auth.schemas import ...`).

Add to `__all__` list:

```python
    # Routers
    "cli_login_router",
    "admin_token_router",
    # CLI Login Schemas
    "CLILoginCreateResponse",
    "CLILoginStatusResponse",
    "ImpersonationTokenResponse",
```

Also export `CLILoginChallenge` from db:

```python
from zndraw_auth.db import (
    Base,
    CLILoginChallenge,
    SessionDep,
    ...
)
```

Add `"CLILoginChallenge"` to `__all__`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_login.py::test_routers_importable_from_package -v`
Expected: PASS.

**Step 5: Run full test suite + linter**

Run: `uv run pytest -v && uv run ruff check src/ tests/`
Expected: All pass, no lint errors.

**Step 6: Commit**

```bash
git add src/zndraw_auth/__init__.py
git commit -m "feat: export cli_login_router, admin_token_router, and new schemas"
```

---

### Task 8: Final Verification

**Step 1: Run full test suite**

Run: `uv run pytest -v --tb=short`
Expected: All tests pass.

**Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors.

**Step 3: Run ruff format**

Run: `uv run ruff format src/ tests/`

**Step 4: Verify no regressions in existing tests**

Run: `uv run pytest tests/test_auth.py tests/test_users_router.py tests/test_scoped_session.py -v`
Expected: All pass unchanged.

**Step 5: Commit any formatting fixes**

```bash
git add -u
git commit -m "style: format with ruff"
```
