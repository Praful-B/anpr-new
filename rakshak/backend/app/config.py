"""Application configuration loaded from environment variables via pydantic-settings.

All secrets and runtime knobs live in .env; this module provides the
single ``Settings`` object consumed throughout the backend.
"""

import base64

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised configuration for the RAKSHAK backend.

    Attributes:
        DATABASE_URL: PostgreSQL connection string with PostGIS.
        REDIS_URL: Redis connection string.
        MASTER_KEY_B64: Base64-encoded 32-byte master key for device encryption.
        JWT_SECRET: Secret used to sign JSON Web Tokens.
        JWT_ALGORITHM: HMAC algorithm identifier for JWT signing.
        JWT_ACCESS_TTL_MIN: Lifetime of access tokens in minutes.
        JWT_REFRESH_TTL_DAYS: Lifetime of refresh tokens in days.
        BCRYPT_COST: Bcrypt hashing cost factor.
        CORS_ORIGIN: Allowed CORS origin (dashboard URL).
        STORAGE_BACKEND: Photo storage backend type (``local`` or ``s3``).
        UPLOAD_DIR: Filesystem path for local photo uploads.
        FIR_DEADLINE_HOURS: Hours after complaint approval before FIR expires.
        COOLDOWN_DAYS: Days after expiry before a plate can be re-listed.
        POSTGRES_USER: PostgreSQL username.
        POSTGRES_PASSWORD: PostgreSQL password.
        POSTGRES_DB: PostgreSQL database name.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/rakshak"
    REDIS_URL: str = "redis://localhost:6379/0"
    MASTER_KEY_B64: str = ""
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MIN: int = 15
    JWT_REFRESH_TTL_DAYS: int = 7
    BCRYPT_COST: int = 12
    CORS_ORIGIN: str = "http://localhost:5173"
    STORAGE_BACKEND: str = "local"
    UPLOAD_DIR: str = "./data/uploads"
    FIR_DEADLINE_HOURS: int = 48
    COOLDOWN_DAYS: int = 7

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "rakshak"

    @model_validator(mode="after")
    def _validate_master_key(self) -> "Settings":
        """Ensure MASTER_KEY_B64 decodes to exactly 32 bytes at startup.

        Returns:
            Settings: The validated settings instance.

        Raises:
            ValueError: If the key is empty or does not decode to 32 bytes.
        """
        if not self.MASTER_KEY_B64:
            raise ValueError("MASTER_KEY_B64 must not be empty")
        try:
            key_bytes = base64.b64decode(self.MASTER_KEY_B64, validate=True)
        except Exception as exc:
            raise ValueError(
                f"MASTER_KEY_B64 is not valid base64: {exc}"
            ) from exc
        if len(key_bytes) != 32:
            raise ValueError(
                f"MASTER_KEY_B64 must decode to exactly 32 bytes, got {len(key_bytes)}"
            )
        return self


settings = Settings()
