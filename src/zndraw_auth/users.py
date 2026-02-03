"""FastAPI-Users configuration and exported dependencies.

This module exports the key dependencies that other packages should import:
- current_active_user: Depends() for authenticated active user
- current_superuser: Depends() for authenticated superuser
- fastapi_users: The FastAPIUsers instance for including routers
- auth_backend: The JWT authentication backend

Example usage in other packages:
    from zndraw_auth import current_active_user, User

    @router.get("/protected")
    async def protected_route(user: User = Depends(current_active_user)):
        return {"user_id": str(user.id)}
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase

from zndraw_auth.db import User, get_user_db
from zndraw_auth.schemas import UserUpdate
from zndraw_auth.settings import AuthSettings, get_auth_settings

# --- User Manager ---


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Custom user manager with lifecycle hooks.

    Token secrets are set via dependency injection in get_user_manager.
    """

    reset_password_token_secret: str
    verification_token_secret: str
    is_dev_mode: bool = False

    async def on_after_register(
        self, user: User, request: Request | None = None
    ) -> None:
        """Called after successful registration."""
        if self.is_dev_mode and not user.is_superuser:
            await self.update(UserUpdate(is_superuser=True), user, safe=False)
            print(f"User {user.id} has registered (granted superuser - dev mode).")
        else:
            print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Called after password reset requested."""
        print(f"User {user.id} forgot password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Called after verification requested."""
        print(f"Verification requested for {user.id}. Token: {token}")


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AsyncGenerator[UserManager, None]:
    """FastAPI dependency that yields the user manager."""
    manager = UserManager(user_db)
    manager.reset_password_token_secret = (
        settings.reset_password_token_secret.get_secret_value()
    )
    manager.verification_token_secret = (
        settings.verification_token_secret.get_secret_value()
    )
    manager.is_dev_mode = settings.is_dev_mode
    yield manager


# --- Authentication Backend ---


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> JWTStrategy[User, uuid.UUID]:
    """Get JWT strategy with settings."""
    return JWTStrategy(
        secret=settings.secret_key.get_secret_value(),
        lifetime_seconds=settings.token_lifetime_seconds,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


# --- FastAPI Users Instance ---


fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)


# --- Exported Dependencies ---
# These are the main exports that other packages should use

current_active_user = fastapi_users.current_user(active=True)
"""Dependency for routes requiring an authenticated active user.

Usage:
    @router.get("/protected")
    async def route(user: User = Depends(current_active_user)):
        ...
"""

current_superuser = fastapi_users.current_user(active=True, superuser=True)
"""Dependency for routes requiring superuser privileges.

Usage:
    @router.get("/admin")
    async def route(user: User = Depends(current_superuser)):
        ...
"""

current_optional_user = fastapi_users.current_user(active=True, optional=True)
"""Dependency for routes with optional authentication.

Usage:
    @router.get("/public")
    async def route(user: User | None = Depends(current_optional_user)):
        ...
"""
