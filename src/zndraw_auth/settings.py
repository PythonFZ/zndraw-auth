"""Configuration settings for zndraw-auth."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication settings loaded from environment variables.

    All settings can be overridden with ZNDRAW_AUTH_ prefix.
    Example: ZNDRAW_AUTH_SECRET_KEY=your-secret-key
    """

    model_config = SettingsConfigDict(
        env_prefix="ZNDRAW_AUTH_",
        env_file=".env",
        extra="ignore",
    )

    # JWT settings
    secret_key: SecretStr = SecretStr("CHANGE-ME-IN-PRODUCTION")
    token_lifetime_seconds: int = 3600  # 1 hour

    # Database
    database_url: str = "sqlite+aiosqlite:///./zndraw_auth.db"

    # Password reset / verification tokens
    reset_password_token_secret: SecretStr = SecretStr("CHANGE-ME-RESET")
    verification_token_secret: SecretStr = SecretStr("CHANGE-ME-VERIFY")

    # User defaults
    default_superuser: bool = False
    """When True, new users are automatically granted superuser privileges."""


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
