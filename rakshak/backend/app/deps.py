"""FastAPI dependency providers — DB sessions, auth, RBAC guards, Redis, and device auth.

Provides ``get_db`` (re-exported from ``app.db``), ``get_current_user``
(extracts and validates the Bearer JWT), ``require_role`` (dependency
factory that enforces role-based access control), ``get_redis``
(Redis client for rate limiting), and ``get_current_device``
(extracts and validates the X-Device-Token header).
"""

import uuid
from collections.abc import Callable
from typing import Annotated

import redis
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db as _get_db
from app.models.device import Device
from app.models.user import Role, User
from app.security import decode_token, verify_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_TYPE = "bearer"

# ---------------------------------------------------------------------------
# Re-export get_db for convenience so all deps can import from this module.
# ---------------------------------------------------------------------------

get_db = _get_db

# Redis client singleton — lazily initialised.
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Provide a Redis client for rate limiting and caching.

    Returns:
        redis.Redis: A Redis connection instance.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_client

# Bearer token extraction from Authorization header.
_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    """Build a 401 response carrying the Bearer challenge header.

    Args:
        detail: Human-readable reason for the rejection.

    Returns:
        HTTPException: A ready-to-raise 401 error.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": TOKEN_TYPE},
    )


def _parse_subject(payload: dict) -> uuid.UUID:
    """Extract and parse the ``sub`` claim from a decoded token.

    Args:
        payload: Decoded JWT claims.

    Returns:
        uuid.UUID: The user identifier from the token subject.

    Raises:
        HTTPException: 401 when the claim is missing or not a UUID.
    """
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise _unauthorized("Token missing subject claim")
    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        raise _unauthorized("Invalid subject in token")


def _load_user(db: Session, user_id: uuid.UUID) -> User:
    """Load a user by id or fail with 401.

    Args:
        db: Database session for user lookup.
        user_id: Identifier from the access token.

    Returns:
        User: The authenticated ORM user.

    Raises:
        HTTPException: 401 when no such user exists.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _unauthorized("User not found")
    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Extract and validate the current user from the Bearer JWT.

    Args:
        credentials: The raw Bearer token extracted by FastAPI.
        db: Database session for user lookup.

    Returns:
        User: The authenticated ORM user.

    Raises:
        HTTPException: 401 if the token is missing, malformed, expired,
            or the user no longer exists.
    """
    if credentials is None or credentials.credentials == "":
        raise _unauthorized("Not authenticated")

    payload = decode_token(credentials.credentials, expected_type="access")
    if payload is None:
        raise _unauthorized("Invalid or expired token")

    return _load_user(db, _parse_subject(payload))


def require_role(
    *allowed_roles: Role,
) -> Callable[[User], User]:
    """Dependency factory that restricts access to specific roles.

    Args:
        *allowed_roles: One or more ``Role`` values permitted to access
            the endpoint.

    Returns:
        Callable: A FastAPI dependency that returns the current user if
            their role is among ``allowed_roles``.

    Raises:
        HTTPException: 403 with code ``ROLE_NOT_ALLOWED`` if the user's
            role is not permitted.
    """

    def _check_role(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        """Verify the current user's role is allowed.

        Args:
            current_user: The authenticated user from ``get_current_user``.

        Returns:
            User: The same user, if role check passes.

        Raises:
            HTTPException: 403 if the role is not permitted.
        """
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "ROLE_NOT_ALLOWED",
                        "message": f"Role '{current_user.role.value}' is not permitted. Required: {[r.value for r in allowed_roles]}",
                        "field": None,
                    }
                },
            )
        return current_user

    return _check_role


def _match_device_token(db: Session, raw_token: str) -> Device | None:
    """Find the device whose stored hash matches a raw token.

    Args:
        db: Database session for device lookup.
        raw_token: Plaintext token from the X-Device-Token header.

    Returns:
        Device | None: The matching device, or None when none matches.
    """
    for device in db.query(Device).all():
        if verify_password(raw_token, device.token_hash):
            return device
    return None


def get_current_device(
    x_device_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> Device:
    """Extract and validate the current device from the X-Device-Token header.

    Verifies the token against stored bcrypt hashes and rejects revoked
    devices.

    Args:
        x_device_token: The raw device token from the X-Device-Token header.
        db: Database session for device lookup.

    Returns:
        Device: The authenticated ORM device.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or the
            device is revoked.
    """
    if not x_device_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Device-Token header",
        )

    matched_device = _match_device_token(db, x_device_token)
    if matched_device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
        )

    if matched_device.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device has been revoked",
        )

    return matched_device
