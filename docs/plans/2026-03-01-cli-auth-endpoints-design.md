# CLI Authentication Endpoints (zndraw-auth scope)

Date: 2026-03-01

## Problem

The CLI creates a separate guest identity from the browser user. Session
filtering by owner means the CLI sees zero sessions and cannot control browser
sessions.

## Solution (zndraw-auth scope)

Two new routers exported from zndraw-auth:

1. **cli_login_router** -- device-code style flow for browser-based CLI login
2. **admin_token_router** -- superuser token minting for automation/CI

The host app mounts these alongside the existing fastapi-users routers.
Token storage, CLI commands, and browser approval UI live in zndraw-fastapi
(out of scope for this document).

## Module Structure

```
src/zndraw_auth/
  cli_login.py     NEW  cli_login_router (POST/GET/PATCH/DELETE)
  admin.py         NEW  admin_token_router (POST mint token)
  db.py            ADD  CLILoginChallenge model
  schemas.py       ADD  CLI login + admin token schemas
  __init__.py      ADD  exports for new routers
  settings.py      no changes
  users.py         no changes

tests/
  conftest.py      UPDATE  include new routers in test app
  test_cli_login.py   NEW
  test_admin_token.py  NEW
```

## CLILoginChallenge Model (db.py)

```python
class CLILoginChallenge(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)       # 8-char alphanumeric
    secret: str | None = None                         # random, only CLI knows; nulled on redeem
    status: str = "pending"                           # pending | approved | redeemed
    token: str | None = None                          # minted JWT; nulled on redeem
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    created_at: datetime
    expires_at: datetime                              # created_at + 5 min
```

Uses SQLModel with `table=True` (shares `SQLModel.metadata` = `Base.metadata`).
FK on `user_id` to `user.id` for referential integrity.

### Lifecycle

```
pending  ──PATCH──>  approved  ──GET (redeem)──>  redeemed
pending  ──DELETE──> (row deleted)
pending  ──expired──> (cleanup deletes or 410 on poll)
```

On redeem: `token` and `secret` are set to `None`, `status` set to `"redeemed"`.
Row is kept for audit (who, when, how often).

## CLI Login Router (cli_login.py)

Exported as `cli_login_router`. Host mounts at `/auth/cli-login`.

### POST / (create challenge)

- Auth: none
- Generates 8-char alphanumeric code + random secret
- Creates CLILoginChallenge with 5-minute expiry
- Opportunistically deletes expired challenges
- Returns: `{code, secret, approve_url}`

### GET /{code} (poll / redeem)

- Auth: none; `secret` as query parameter
- Validates secret matches challenge
- Expired → 410 Gone
- Pending → `{status: "pending"}`
- Approved → `{status: "approved", token: "eyJ..."}`, then redeems
  (sets status=redeemed, nulls token+secret)
- Redeemed/not found → 404
- **One-time retrieval**: token can only be read once

### PATCH /{code} (approve)

- Auth: `current_active_user` (browser user with JWT)
- Validates challenge exists and is pending
- Mints JWT for the browser user via pyjwt (same secret/algo as JWTStrategy)
- Sets `challenge.token`, `challenge.user_id`, `challenge.status = "approved"`
- Returns 200

### DELETE /{code} (reject)

- Auth: `current_active_user`
- Deletes the challenge row
- Returns 204

## Admin Token Router (admin.py)

Exported as `admin_token_router`. Host mounts at `/admin`.

### POST /users/{user_id}/token

- Auth: `current_superuser`
- Looks up target user by UUID; 404 if not found or inactive
- Mints JWT directly via pyjwt with extra `impersonated_by` claim:
  ```json
  {
    "sub": "target-user-uuid",
    "aud": "fastapi-users:auth",
    "exp": "...",
    "impersonated_by": "admin-user-uuid"
  }
  ```
- Logs: `"Admin {admin.id} minted token for user {target.id}"`
- Returns: `{access_token, token_type: "bearer"}`

### Safeguards

- Superuser-only via `current_superuser` dependency
- Target must exist and be active
- Audit trail in JWT claim + server log
- Same lifetime as normal tokens

## Schemas (schemas.py additions)

```python
class CLILoginCreateResponse(BaseModel):
    code: str
    secret: str
    approve_url: str

class CLILoginStatusResponse(BaseModel):
    status: str  # "pending" | "approved"
    token: str | None = None

class ImpersonationTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

## Exports (__init__.py additions)

```python
from zndraw_auth.cli_login import cli_login_router
from zndraw_auth.admin import admin_token_router
```

Host app usage:
```python
app.include_router(cli_login_router, prefix="/auth/cli-login", tags=["auth"])
app.include_router(admin_token_router, prefix="/admin", tags=["admin"])
```

## Test Plan

### test_cli_login.py

- Happy path: create → approve → poll gets token → token authenticates
- Poll before approval returns `{status: "pending"}`
- Wrong secret on poll returns 404
- Expired challenge returns 410
- Reject (DELETE) then poll returns 404
- Second poll after redeem returns 404 (one-time retrieval)
- Multiple concurrent challenges don't interfere

### test_admin_token.py

- Happy path: superuser mints token for regular user, token works
- Non-superuser gets 403
- Target user not found returns 404
- Inactive target user returns 404
- Token `sub` claim matches target user (not admin)
- Token contains `impersonated_by` claim with admin's UUID

## Decisions

- **Router export pattern**: pre-built APIRouter (matches fastapi-users style)
- **No browser HTML**: zndraw-auth provides API only; approval UI in zndraw-fastapi
- **Direct pyjwt for admin tokens**: cleaner than wrapping JWTStrategy
- **FK on user_id**: referential integrity, no downside
- **Redeem-not-delete**: keep rows for audit, null sensitive fields
- **Admin risk accepted**: equivalent to existing PATCH /users/{id} capability,
  strictly less dangerous (no password change, has audit trail)
