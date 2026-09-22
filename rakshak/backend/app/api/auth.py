"""Auth endpoints — registration, login, and token refresh.

All routes live under ``/api/v1/auth`` and handle user lifecycle:
registration with role selection, credential-based login, and
refresh-token rotation. Refresh tokens are delivered via HttpOnly cookies
for dashboard security; access tokens are returned in the JSON body.
"""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Body, Cookie, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_db
from app.exceptions import AppError
from app.models.user import Role, User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])

logger = structlog.get_logger(__name__)

REFRESH_COOKIE_NAME = "rakshak_refresh"
REFRESH_COOKIE_MAX_AGE_SECONDS = settings.JWT_REFRESH_TTL_DAYS * 86_400
REFRESH_COOKIE_PATH = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Response schemas (local to this module for spec compliance)
# ---------------------------------------------------------------------------


class RegisterResponse(BaseModel):
    """Response shape for successful registration.

    Attributes:
        user: The newly created user.
        tokens: Access and refresh JWTs for the new account.
    """

    user: UserResponse
    tokens: TokenResponse


class LoginResponse(BaseModel):
    """Response shape for successful login.

    Attributes:
        user: The authenticated user.
        access_token: Short-lived JWT access token.
        refresh_token: Long-lived JWT refresh token (also set as an
            HttpOnly cookie for browsers).
        token_type: Always ``bearer``.
    """

    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = Field(default="bearer", description="Token type")


class RefreshRequest(BaseModel):
    """Request body for token rotation.

    The token is accepted in the body (the shape both frontends and the
    mobile client post) or, for browser clients relying on the HttpOnly
    cookie, in the cookie itself; the body takes precedence.

    Attributes:
        refresh_token: The refresh JWT to rotate.
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., description="Refresh token to rotate")


class RefreshResponse(BaseModel):
    """Response shape for successful token refresh.

    Attributes:
        access_token: Fresh short-lived JWT access token.
        refresh_token: Fresh long-lived JWT refresh token.
    """

    access_token: str
    refresh_token: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token as an HttpOnly cookie on the response.

    Args:
        response: The FastAPI Response object to set the cookie on.
        refresh_token: The encoded refresh JWT.
    """
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _ensure_email_available(db: Session, email: str) -> None:
    """Reject registration when the email is already taken.

    Args:
        db: Database session.
        email: Email address being registered.

    Raises:
        AppError: 409 EMAIL_TAKEN when a user with this email already exists.
    """
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        logger.info("registration_duplicate_email", email=email)
        raise AppError(
            code="EMAIL_TAKEN",
            message="A user with this email already exists",
            status_code=409,
        )


def _user_to_response(user: User) -> UserResponse:
    """Convert a User ORM instance to the public response schema.

    Args:
        user: The user ORM instance.

    Returns:
        UserResponse: Pydantic model safe for external responses.
    """
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RegisterResponse:
    """Register a new user account.

    Args:
        payload: Registration data (name, email, password, optional role).
        response: FastAPI Response to set the refresh cookie on.
        db: Database session.

    Returns:
        RegisterResponse: User info and a ``tokens`` object with the
            access and refresh JWTs. The refresh token is also set as an
            HttpOnly cookie.

    Raises:
        AppError: 409 if the email is already registered.
    """
    _ensure_email_available(db, payload.email)

    user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(str(user.id), user.role.value)
    refresh_token = create_refresh_token(str(user.id))
    _set_refresh_cookie(response, refresh_token)

    logger.info("registration_success", user_id=str(user.id), role=user.role.value)

    return RegisterResponse(
        user=_user_to_response(user),
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
        ),
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    """Authenticate an existing user and return tokens.

    The refresh token is set as an HttpOnly cookie (``rakshak_refresh``)
    for secure browser-based storage. The access token is returned in the
    JSON body for in-memory storage on the client.

    Args:
        payload: Login credentials (email + password).
        response: FastAPI Response to set the cookie on.
        db: Database session.

    Returns:
        LoginResponse: User info and the access/refresh JWTs at the top
            level. The refresh token is also set as an HttpOnly cookie.

    Raises:
        AppError: 401 if credentials are invalid (same error for wrong
            password and unknown email to prevent enumeration).
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        logger.info("login_failed", email=payload.email)
        raise AppError(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password",
            status_code=401,
        )

    access_token = create_access_token(str(user.id), user.role.value)
    refresh_token = create_refresh_token(str(user.id))
    _set_refresh_cookie(response, refresh_token)

    logger.info("login_success", user_id=str(user.id))
    return LoginResponse(
        user=_user_to_response(user),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
)
def refresh(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[RefreshRequest | None, Body()] = None,
    rakshak_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> RefreshResponse:
    """Rotate a refresh token and return new access and refresh tokens.

    Accepts the refresh token from the JSON body (the shape posted by the
    dashboard, mobile client, and device simulator) or, as a fallback,
    from the HttpOnly cookie. A new refresh token is returned in the body
    and set as a fresh cookie on the response.

    Args:
        response: FastAPI Response to set the new cookie on.
        db: Database session.
        payload: Optional body carrying the refresh token.
        rakshak_refresh: Refresh token from the HttpOnly cookie.

    Returns:
        RefreshResponse: Fresh access and refresh tokens.

    Raises:
        AppError: 401 if the refresh token is invalid or expired.
    """
    token = (payload.refresh_token if payload else None) or rakshak_refresh
    if not token:
        raise AppError(code="INVALID_REFRESH", message="Missing refresh token", status_code=401)

    claims = decode_token(token, expected_type="refresh")
    if claims is None:
        raise AppError(code="INVALID_REFRESH", message="Invalid or expired refresh token", status_code=401)

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError):
        raise AppError(code="INVALID_REFRESH", message="Invalid token subject", status_code=401)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(code="INVALID_REFRESH", message="User not found", status_code=401)

    access_token = create_access_token(str(user.id), user.role.value)
    new_refresh_token = create_refresh_token(str(user.id))
    _set_refresh_cookie(response, new_refresh_token)

    logger.info("token_refresh", user_id=str(user.id))
    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )
