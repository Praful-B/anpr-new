"""User model — stores citizen, volunteer, COP, and admin accounts.

Defines the ``User`` ORM class and the ``Role`` enum used for
role-based access control across the RAKSHAK backend.
"""

import enum
import uuid

from sqlalchemy import Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_NAME_LENGTH = 255
MAX_EMAIL_LENGTH = 255
MAX_PHONE_LENGTH = 20
MAX_PASSWORD_HASH_LENGTH = 255


class Role(str, enum.Enum):
    """Role enumeration for RBAC.

    ``str`` inheritance allows direct serialisation in JWT claims and
    JSON responses without conversion.
    """

    CITIZEN = "CITIZEN"
    VOLUNTEER = "VOLUNTEER"
    COP = "COP"
    ADMIN = "ADMIN"


class User(TimestampMixin, Base):
    """SQLAlchemy model representing a registered user account.

    Attributes:
        id: UUID primary key, auto-generated.
        name: Full name of the user.
        email: Unique, indexed email address used for login.
        phone: Optional phone number.
        password_hash: Bcrypt-hashed password (cost 12).
        role: RBAC role (CITIZEN, VOLUNTEER, COP, ADMIN).
        created_at: UTC timestamp of account creation (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    email: Mapped[str] = mapped_column(
        String(MAX_EMAIL_LENGTH),
        unique=True,
        nullable=False,
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(
        String(MAX_PHONE_LENGTH),
        nullable=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(MAX_PASSWORD_HASH_LENGTH),
        nullable=False,
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", create_constraint=True),
        nullable=False,
        default=Role.CITIZEN,
    )
