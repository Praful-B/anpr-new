"""Pydantic schemas for authentication request and response payloads.

Defines the contracts for registration, login, token refresh, and
user-info responses used by the ``/api/v1/auth/*`` endpoints.
"""

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, BeforeValidator, Field

from app.models.user import Role

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PASSWORD_LENGTH = 8
MAX_NAME_LENGTH = 255
MAX_PHONE_LENGTH = 20

# Basic email regex: local@domain.tld (allows .local for dev environments).
_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _validate_email(value: str) -> str:
    """Validate an email address using a permissive regex pattern.

    Allows local-use domains such as ``*.local`` that stricter validators
    reject but are valid for development environments.

    Args:
        value: Raw email string to validate.

    Returns:
        str: Lowercased email address.

    Raises:
        ValueError: If the email format is invalid.
    """
    if not _EMAIL_REGEX.match(value):
        raise ValueError(f"Invalid email address: {value}")
    return value.lower()


# Pydantic Annotated type that validates email format with regex.
SafeEmail = Annotated[str, BeforeValidator(_validate_email)]


class RegisterRequest(BaseModel):
    """Schema for user registration payload.

    Attributes:
        name: Full name of the user.
        email: Unique email address.
        phone: Optional phone number.
        password: Plain-text password (minimum 8 characters).
        role: Desired role; defaults to CITIZEN.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=MAX_NAME_LENGTH, description="Full name")
    email: SafeEmail = Field(..., description="Unique email address")
    phone: str | None = Field(None, max_length=MAX_PHONE_LENGTH, description="Phone number")
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, description="Plain-text password")
    role: Role = Field(default=Role.CITIZEN, description="User role")


class LoginRequest(BaseModel):
    """Schema for login payload.

    Attributes:
        email: Registered email address.
        password: Plain-text password.
    """

    model_config = ConfigDict(extra="forbid")

    email: SafeEmail = Field(..., description="Registered email")
    password: str = Field(..., description="Plain-text password")


class TokenResponse(BaseModel):
    """Schema returned after successful login or token refresh.

    Attributes:
        access_token: Short-lived JWT (15 min).
        refresh_token: Long-lived JWT (7 days).
        token_type: Always ``bearer``.
    """

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class UserResponse(BaseModel):
    """Schema for user information returned in API responses.

    Attributes:
        id: UUID of the user.
        name: Full name.
        email: Email address.
        phone: Phone number (may be None).
        role: User role.
        created_at: Account creation timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="User UUID")
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    phone: str | None = Field(None, description="Phone number")
    role: Role = Field(..., description="User role")
    created_at: datetime = Field(..., description="Account creation timestamp")
