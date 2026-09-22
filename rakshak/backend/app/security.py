"""Security helpers — password hashing and JWT token management.

Provides bcrypt-based password hashing (cost from settings) and JWT
encode/decode utilities used throughout the auth subsystem.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PASSWORD_CONTEXT = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.BCRYPT_COST,
)


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt.

    Args:
        plain_password: The raw password string.

    Returns:
        str: Bcrypt-hashed password.
    """
    return PASSWORD_CONTEXT.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash.

    Args:
        plain_password: The raw password to verify.
        hashed_password: The stored bcrypt hash.

    Returns:
        bool: True if the password matches, False otherwise.
    """
    return PASSWORD_CONTEXT.verify(plain_password, hashed_password)


def create_access_token(subject: str, role: str) -> str:
    """Create a short-lived JWT access token.

    Args:
        subject: The user's UUID string (``sub`` claim).
        role: The user's role string (``role`` claim).

    Returns:
        str: Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TTL_MIN)
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a long-lived JWT refresh token.

    Refresh tokens contain only the subject, expiry, issued-at, and type.
    They do not carry a role claim.

    Args:
        subject: The user's UUID string (``sub`` claim).

    Returns:
        str: Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
    payload = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict | None:
    """Decode and validate a JWT token, checking the ``type`` claim.

    Args:
        token: The encoded JWT string.
        expected_type: The required token type (``access`` or ``refresh``).

    Returns:
        dict | None: The decoded payload dict, or ``None`` if decoding fails
            or the type claim does not match.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None
