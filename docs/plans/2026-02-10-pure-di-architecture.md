# zndraw-auth: Pure Dependency Injection Architecture

**Date**: 2026-02-10
**Status**: Design
**Scope**: Foundation database layer for ZnDraw ecosystem

---

## Goal

Pure FastAPI dependency injection with lifespan-managed resources. Maximum DRY.

**Remove:**
- `@lru_cache` decorators
- Module-level singletons
- Database initialization (moved to host app)

**Provide:**
- Engine lifecycle management (lifespan)
- Session dependencies (via DI)
- Utility functions for host app

---

## Architectural Role

**zndraw-auth is the database foundation:**
- Provides engine/session dependencies
- Provides authentication
- **Does NOT** initialize tables (host app does)
- **Single source of truth** for session management

**Why not init tables?**
- All packages share `SQLModel.metadata` (via `Base.metadata = SQLModel.metadata`)
- One `metadata.create_all()` creates ALL tables (User, Job, Room, etc.)
- Only host app knows all dependencies
- Avoids DRY violation

---

## Unified Naming Schema

**Principle:** Drop "async" prefix (everything is async, types make it clear)

```python
get_engine(request: Request) -> AsyncEngine
get_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]
get_session(session_maker: async_sessionmaker) -> AsyncIterator[AsyncSession]
```

**Downstream packages use these directly** - no wrappers, maximum DRY.

---

## Dependency Chain

```
Environment Variables
        ↓
    AuthSettings
        ↓
database_lifespan(app)
        ↓
  app.state.engine ← created once in lifespan
        ↓
  get_engine(request) ← retrieves from app.state
        ↓
  get_session_maker(engine) ← creates async_sessionmaker
        ↓
  get_session(session_maker) ← yields request-scoped session
        ↓
  current_active_user(session) ← auth dependencies
```

**Override point:** `get_session_maker` (primary for tests)

---

## Implementation

### 1. Engine Factory

```python
# zndraw_auth/db.py
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool, NullPool

def create_engine_for_url(database_url: str) -> AsyncEngine:
    """Create engine with appropriate connection pooling.

    Strategy:
    - In-memory SQLite: StaticPool (single shared connection)
    - File SQLite: NullPool (connection per checkout, avoids locks)
    - PostgreSQL: QueuePool (default connection pool)
    """
    if database_url == "sqlite+aiosqlite://":
        return create_async_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif database_url.startswith("sqlite"):
        return create_async_engine(database_url, poolclass=NullPool)
    else:
        return create_async_engine(database_url)
```

---

### 2. Lifespan Context Manager

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

@asynccontextmanager
async def database_lifespan(
    app: FastAPI,
    settings: AuthSettings | None = None,
) -> AsyncIterator[None]:
    """Manage database engine lifecycle.

    Creates engine, stores in app.state, cleans up on shutdown.
    Does NOT create tables - host app handles initialization.
    """
    if settings is None:
        settings = get_auth_settings()

    engine = create_engine_for_url(settings.database_url)
    app.state.engine = engine

    yield

    await engine.dispose()
```

**Key:** No table creation here - that's host app responsibility.

---

### 3. Dependencies

```python
from typing import Annotated, AsyncIterator
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

def get_engine(request: Request) -> AsyncEngine:
    """Retrieve engine from app.state.

    Override point #1 (advanced use cases).
    """
    return request.app.state.engine


def get_session_maker(
    engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> async_sessionmaker[AsyncSession]:
    """Create session maker from engine.

    Override point #2 (PRIMARY - most tests override here).

    Returns factory, not session, because:
    - Long-polling needs multiple sessions per request
    - Socket.IO needs session per event
    - TaskIQ needs session per task
    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session(
    session_maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_maker)]
) -> AsyncIterator[AsyncSession]:
    """Yield request-scoped session.

    Override point #3 (rare - specific session mocking).

    Session lifecycle:
    - Created at request time
    - Auto-committed on success
    - Rolled back on exception
    - Closed after request
    """
    async with session_maker() as session:
        yield session


# Type alias for convenience
SessionDep = Annotated[AsyncSession, Depends(get_session)]
```

---

### 4. Admin User Management

```python
async def ensure_default_admin(settings: AuthSettings) -> None:
    """Create or promote default admin user.

    Called by host app during initialization.
    Idempotent - safe to call multiple times.

    If default_admin_email is None, runs in dev mode (all users are superusers).
    """
    if settings.default_admin_email is None:
        return

    # Create session_maker directly (outside request context)
    from zndraw_auth.db import create_engine_for_url

    engine = create_engine_for_url(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        # Check if user exists
        result = await session.execute(
            select(User).where(User.email == settings.default_admin_email)
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            # Create admin user
            password_helper = PasswordHelper()
            hashed = password_helper.hash(settings.default_admin_password.get_secret_value())
            admin = User(
                email=settings.default_admin_email,
                hashed_password=hashed,
                is_active=True,
                is_superuser=True,
                is_verified=True,
            )
            session.add(admin)
            await session.commit()
        elif not existing.is_superuser:
            # Promote to superuser
            existing.is_superuser = True
            await session.commit()

    await engine.dispose()
```

---

## What This Package Provides

### Public API

```python
# Database lifecycle
from zndraw_auth import database_lifespan

# Dependencies (used by all downstream packages)
from zndraw_auth.db import get_engine, get_session_maker, get_session, SessionDep

# Utilities (used by host app for init)
from zndraw_auth.db import create_engine_for_url, ensure_default_admin

# Models
from zndraw_auth import User, Base

# Auth dependencies
from zndraw_auth import current_active_user, current_superuser, current_optional_user

# Settings
from zndraw_auth import AuthSettings, get_auth_settings
```

---

## Usage Examples

### Host Application

```python
from zndraw_auth import database_lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database_lifespan(app):
        # Host app initializes tables here
        yield

app = FastAPI(lifespan=lifespan)
```

### Downstream Library (zndraw-joblib)

```python
from zndraw_auth.db import get_session, SessionDep

@router.post("/jobs")
async def create_job(session: SessionDep):
    # Uses auth's session dependency directly
    job = Job(...)
    session.add(job)
    await session.commit()
```

### Tests

```python
from zndraw_auth.db import get_session_maker

@pytest.fixture
def app():
    app = FastAPI()

    test_engine = create_async_engine("sqlite://", poolclass=StaticPool)
    test_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    # Override at session_maker level (primary override point)
    app.dependency_overrides[get_session_maker] = lambda: test_maker

    yield app

    app.dependency_overrides.clear()
```

---

## Changes Required

### Remove
- `@lru_cache` on `get_engine()` and `get_session_maker()`
- `create_db_and_tables()` (host app responsibility)
- Table creation from lifespan

### Add
- `create_engine_for_url()` factory function
- Engine lifecycle in `database_lifespan()`
- `SessionDep` type alias

### Modify
- `get_engine()` → takes Request, returns from app.state
- `get_session_maker()` → takes engine via Depends, returns factory
- `get_session()` → takes session_maker via Depends, yields session (rename from `get_async_session`)
- `ensure_default_admin()` → standalone function (not in lifespan)

### Keep Unchanged
- `User` model
- `Base` class (with `metadata = SQLModel.metadata`)
- All auth dependencies
- `AuthSettings` model
- Default: `database_url = "sqlite+aiosqlite://"` (in-memory)

---

## Package Coordination

### With zndraw-joblib
- Joblib imports `SessionDep` from zndraw-auth directly
- No session wrappers in joblib (maximum DRY)
- Joblib models inherit from `Base` (shared metadata)
- See: `/Users/fzills/tools/zndraw-joblib/docs/plans/2026-02-10-dependency-injection-alignment.md`

### With zndraw-fastapi
- Fastapi uses `database_lifespan()` from zndraw-auth
- Fastapi owns database initialization (imports all models, calls `create_all()`)
- Fastapi adds SQLite locking in lifespan if needed (not via DI)
- See: `/Users/fzills/tools/zndraw-fastapi/docs/plans/2026-02-10-database-initialization.md`

---

## Testing Strategy

**Primary override:** `get_session_maker`

```python
app.dependency_overrides[get_session_maker] = lambda: test_session_maker
```

**Why this level?**
- Flexible (control engine, pool, session config)
- Simple (one override for entire DB)
- Standard (matches FastAPI patterns)

---

## Success Criteria

- [ ] No `@lru_cache` in codebase
- [ ] Engine in app.state (not module-level)
- [ ] No table creation in lifespan
- [ ] Unified naming (`get_session` not `get_async_session`)
- [ ] `ensure_default_admin()` is standalone
- [ ] Downstream packages use dependencies directly (no wrappers)
- [ ] Tests override `get_session_maker` cleanly
- [ ] Engine disposed on shutdown
- [ ] All tests pass
