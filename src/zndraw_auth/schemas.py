"""Pydantic schemas for user operations."""

import uuid

from fastapi_users import schemas
from pydantic import BaseModel


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schema for reading user data (responses)."""

    pass


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user."""

    pass


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating an existing user."""

    pass


# --- OAuth2 Schemas ---


class TokenResponse(BaseModel):
    """OAuth2 bearer token response.

    This is the standard OAuth2 token response format returned by
    the /auth/jwt/login endpoint. Useful for type-safe testing and
    client implementations.

    Note: FastAPI and fastapi-users don't export a standard schema for this,
    so we provide it here for convenience.
    """

    access_token: str
    token_type: str
