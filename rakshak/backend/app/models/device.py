"""Device model — registered fleet and volunteer devices.

Defines the ``Device`` ORM class and the ``DeviceType`` enum used for
tracking government fleet and volunteer citizen devices that participate
in on-device ANPR matching.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOKEN_HASH_LENGTH = 255
MAX_ENCRYPTION_KEY_LENGTH = 512


class DeviceType(str, enum.Enum):
    """Type classification for registered devices.

    ``str`` inheritance allows direct serialisation in JWT claims and
    JSON responses without conversion.
    """

    FLEET = "FLEET"
    VOLUNTEER = "VOLUNTEER"


class Device(TimestampMixin, Base):
    """SQLAlchemy model representing a registered ANPR device.

    Attributes:
        id: UUID primary key, auto-generated.
        user_id: Foreign key to the registering user account.
        type: Device classification (FLEET or VOLUNTEER).
        token_hash: Bcrypt-hashed device token (raw token shown once).
        encryption_key_wrapped: Wrapped encryption key for this device.
        key_version: The hotlist version used when deriving the device key.
        revoked: Whether the device has been revoked by an admin.
        last_sync_at: UTC timestamp of the most recent hotlist sync.
        created_at: UTC timestamp of device registration (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    type: Mapped[DeviceType] = mapped_column(
        Enum(DeviceType, name="device_type", create_constraint=True),
        nullable=False,
        default=DeviceType.VOLUNTEER,
    )
    token_hash: Mapped[str] = mapped_column(
        String(MAX_TOKEN_HASH_LENGTH),
        nullable=False,
        unique=True,
    )
    encryption_key_wrapped: Mapped[str] = mapped_column(
        String(MAX_ENCRYPTION_KEY_LENGTH),
        nullable=False,
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
