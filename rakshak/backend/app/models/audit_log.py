"""Audit log model — immutable record of COP and admin actions.

Every privileged mutation (complaint verification, hotlist update,
device revocation) writes an audit log row with actor, action,
target, and optional metadata. System actions (e.g. scheduler expiry)
use a NULL actor_id.
"""

import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ACTION_LENGTH = 100
MAX_TARGET_TYPE_LENGTH = 50


class AuditLog(TimestampMixin, Base):
    """SQLAlchemy model representing an immutable audit log entry.

    Attributes:
        id: UUID primary key, auto-generated.
        actor_id: Foreign key to the user who performed the action (nullable
            for system actions such as scheduler-triggered expiry).
        action: Human-readable action label (e.g. ``complaint.verify``).
        target_type: Type of the affected entity (e.g. ``complaint``).
        target_id: UUID of the affected entity.
        metadata_json: Arbitrary JSON payload for additional context.
        created_at: UTC timestamp when the log entry was created (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(MAX_ACTION_LENGTH),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(MAX_TARGET_TYPE_LENGTH),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
