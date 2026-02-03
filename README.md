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

from zndraw_auth import (
    User,
    UserCreate,
    UserRead,
    auth_backend,
    create_db_and_tables,
    current_active_user,
    fastapi_users,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
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


@app.get("/protected")
async def protected_route(user: User = Depends(current_active_user)):
    return {"message": f"Hello {user.email}!"}
```

## Extending with Custom Models (e.g., zndraw-joblib)

Other packages can import `Base` and `get_async_session` to define models that share the same database and have foreign key relationships to `User`.

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
from sqlalchemy.ext.asyncio import AsyncSession

from zndraw_auth import User, current_active_user, get_async_session

from .models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/")
async def create_job(
    name: str,
    user: Annotated[User, Depends(current_active_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
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
    session: Annotated[AsyncSession, Depends(get_async_session)],
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
    session: Annotated[AsyncSession, Depends(get_async_session)],
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

from zndraw_auth import (
    UserCreate,
    UserRead,
    auth_backend,
    create_db_and_tables,
    fastapi_users,
)
from zndraw_joblib.routes import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates tables for User AND Job (all models using Base)
    await create_db_and_tables()
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

# Job routes from zndraw-joblib
app.include_router(jobs_router)
```

## Configuration

Settings are loaded from environment variables with the `ZNDRAW_AUTH_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `ZNDRAW_AUTH_SECRET_KEY` | `CHANGE-ME-IN-PRODUCTION` | JWT signing secret |
| `ZNDRAW_AUTH_TOKEN_LIFETIME_SECONDS` | `3600` | JWT token lifetime |
| `ZNDRAW_AUTH_DATABASE_URL` | `sqlite+aiosqlite:///./zndraw_auth.db` | Database connection URL |
| `ZNDRAW_AUTH_RESET_PASSWORD_TOKEN_SECRET` | `CHANGE-ME-RESET` | Password reset token secret |
| `ZNDRAW_AUTH_VERIFICATION_TOKEN_SECRET` | `CHANGE-ME-VERIFY` | Email verification token secret |

## Exports

```python
from zndraw_auth import (
    # SQLAlchemy Base (for extending with your own models)
    Base,

    # User model
    User,

    # Database utilities
    create_db_and_tables,
    get_async_session,
    get_user_db,

    # Pydantic schemas
    UserCreate,
    UserRead,
    UserUpdate,

    # Settings
    AuthSettings,
    get_auth_settings,

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
