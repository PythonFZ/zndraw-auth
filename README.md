# zndraw-auth

Shared authentication package for the ZnDraw ecosystem using [fastapi-users](https://fastapi-users.github.io/fastapi-users/).

## Installation

```bash
pip install zndraw-auth
# or with uv
uv add zndraw-auth
```

## Quick Start

```python
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from zndraw_auth import (
    User,
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    current_active_user,
    database_lifespan,
    ensure_default_admin,
    fastapi_users,
    get_auth_settings,
)
from zndraw_auth.db import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database_lifespan(app):
        # Create all tables
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Create default admin user
        session_maker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        async with session_maker() as session:
            await ensure_default_admin(session, get_auth_settings())

        yield


app = FastAPI(lifespan=lifespan)

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
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)


@app.get("/protected")
async def protected_route(user: User = Depends(current_active_user)):
    return {"message": f"Hello {user.email}!"}
```

## Available Routers

zndraw-auth provides access to three fastapi-users routers that you can include in your app:

### Authentication Router

```python
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
```

**Provides:**
- `POST /auth/jwt/login` - Login with email/password, returns JWT token
- `POST /auth/jwt/logout` - Logout (revokes token)

### Registration Router

```python
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
```

**Provides:**
- `POST /auth/register` - Create new user account

### Users Router (Profile & User Management)

```python
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
```

**Provides:**
- `GET /users/me` - Get current user profile (email, is_superuser, etc.)
- `PATCH /users/me` - Update own profile (email, password)
- `GET /users/{user_id}` - Get any user (superuser only)
- `PATCH /users/{user_id}` - Update any user (superuser only)
- `DELETE /users/{user_id}` - Delete user (superuser only)

**When to include:**
- ✅ Include if clients need to view/edit user profiles
- ✅ Include if superusers need to manage users via API
- ⚠️ Skip if you implement custom user management endpoints

**Example client usage:**

```bash
# Get current user profile (requires authentication)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/users/me

# Response:
# {
#   "id": "4fd3477b-eccf-4ee3-8f7d-68ad72261476",
#   "email": "user@example.com",
#   "is_active": true,
#   "is_superuser": false,
#   "is_verified": false
# }
```

## Extending with Custom Models (e.g., zndraw-joblib)

Other packages can import `Base` and `SessionDep` to define models that share the same database and have foreign key relationships to `User`.

### Example: Adding a Job model in zndraw-joblib

```python
# zndraw_joblib/models.py
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zndraw_auth import Base

if TYPE_CHECKING:
    from zndraw_auth import User


class Job(Base):
    """A compute job owned by a user."""

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Foreign key to User from zndraw-auth (cascade delete when user is deleted)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="cascade"))

    # Relationship (optional, for ORM navigation)
    user: Mapped["User"] = relationship("User", lazy="selectin")
```

### Example: Using the shared session in endpoints

```python
# zndraw_joblib/routes.py
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from zndraw_auth import SessionDep, User, current_active_user

from .models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/")
async def create_job(
    name: str,
    user: Annotated[User, Depends(current_active_user)],
    session: SessionDep,
):
    """Create a new job for the current user."""
    job = Job(name=name, user_id=user.id)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return {"id": str(job.id), "name": job.name, "status": job.status}


@router.get("/")
async def list_jobs(
    user: Annotated[User, Depends(current_active_user)],
    session: SessionDep,
):
    """List all jobs for the current user."""
    result = await session.execute(
        select(Job).where(Job.user_id == user.id)
    )
    jobs = result.scalars().all()
    return [{"id": str(j.id), "name": j.name, "status": j.status} for j in jobs]


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    user: Annotated[User, Depends(current_active_user)],
    session: SessionDep,
):
    """Get a specific job (must belong to current user)."""
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"id": str(job.id), "name": job.name, "status": job.status}
```

### Example: App setup with multiple routers

```python
# main.py (in zndraw-fastapi or combined app)
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from zndraw_auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    database_lifespan,
    ensure_default_admin,
    fastapi_users,
    get_auth_settings,
)
from zndraw_auth.db import Base
from zndraw_joblib.routes import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database_lifespan(app):
        # Create all tables (User from zndraw-auth AND Job from zndraw-joblib)
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Create default admin user
        session_maker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        async with session_maker() as session:
            await ensure_default_admin(session, get_auth_settings())

        yield


app = FastAPI(lifespan=lifespan)

# Auth routes from zndraw-auth
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
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

# Job routes from zndraw-joblib
app.include_router(jobs_router)
```

## Configuration

Settings are loaded from environment variables with the `ZNDRAW_AUTH_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `ZNDRAW_AUTH_SECRET_KEY` | `CHANGE-ME-IN-PRODUCTION` | JWT signing secret |
| `ZNDRAW_AUTH_TOKEN_LIFETIME_SECONDS` | `3600` | JWT token lifetime |
| `ZNDRAW_AUTH_DATABASE_URL` | `sqlite+aiosqlite://` | Database connection URL (in-memory by default) |
| `ZNDRAW_AUTH_RESET_PASSWORD_TOKEN_SECRET` | `CHANGE-ME-RESET` | Password reset token secret |
| `ZNDRAW_AUTH_VERIFICATION_TOKEN_SECRET` | `CHANGE-ME-VERIFY` | Email verification token secret |
| `ZNDRAW_AUTH_DEFAULT_ADMIN_EMAIL` | `None` | Email for the default admin user |
| `ZNDRAW_AUTH_DEFAULT_ADMIN_PASSWORD` | `None` | Password for the default admin user |

### Database Persistence

By default, the database is in-memory (data lost on restart). For production or persistent storage:

```bash
# File-based SQLite
export ZNDRAW_AUTH_DATABASE_URL="sqlite+aiosqlite:///./zndraw_auth.db"

# PostgreSQL
export ZNDRAW_AUTH_DATABASE_URL="postgresql+asyncpg://user:pass@localhost/dbname"
```

### Dev Mode vs Production Mode

The system has two operating modes based on admin configuration:

**Dev Mode** (default - no admin configured):
- All newly registered users are automatically granted superuser privileges
- Useful for development and testing

**Production Mode** (admin configured):
- Set `ZNDRAW_AUTH_DEFAULT_ADMIN_EMAIL` and `ZNDRAW_AUTH_DEFAULT_ADMIN_PASSWORD`
- The configured admin user is created/promoted on startup
- New users are created as regular users (not superusers)

```bash
# Production mode example
export ZNDRAW_AUTH_DEFAULT_ADMIN_EMAIL=admin@example.com
export ZNDRAW_AUTH_DEFAULT_ADMIN_PASSWORD=secure-password
```

## Exports

```python
from zndraw_auth import (
    # SQLAlchemy Base (for extending with your own models)
    Base,

    # User model
    User,

    # Database lifecycle
    database_lifespan,    # Context manager for engine lifecycle

    # Database dependencies
    get_engine,           # Retrieves engine from app.state
    get_session_maker,    # Creates async_sessionmaker (primary override point)
    get_session,          # Yields request-scoped session
    SessionDep,           # Type alias for Annotated[AsyncSession, Depends(get_session)]
    get_user_db,          # FastAPI-Users database adapter

    # Database utilities
    create_engine_for_url,     # Factory for creating engines with appropriate pooling
    ensure_default_admin,      # Create/promote default admin user

    # Pydantic schemas
    UserCreate,    # For registration (get_register_router)
    UserRead,      # For responses (all routers)
    UserUpdate,    # For profile updates (get_users_router)
    TokenResponse, # JWT token response schema

    # Settings
    AuthSettings,
    get_auth_settings,

    # User manager (for custom lifecycle hooks)
    UserManager,
    get_user_manager,

    # FastAPIUsers instance (for including routers)
    fastapi_users,
    auth_backend,

    # Dependencies for Depends()
    current_active_user,    # Requires authenticated active user
    current_superuser,      # Requires superuser
    current_optional_user,  # User | None (optional auth)
)
```

## License

MIT
