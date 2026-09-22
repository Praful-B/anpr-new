"""Complaint model — citizen-filed stolen vehicle complaints.

Defines the ``Complaint`` ORM class and the ``ComplaintStatus`` enum
used for the complaint lifecycle (PENDING_VERIFICATION -> VERIFIED/REJECTED).
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PLATE_LENGTH = 20
MAX_PROOF_REF_LENGTH = 500
MAX_REJECTION_REASON_LENGTH = 1000


class ComplaintStatus(str, enum.Enum):
    """Lifecycle states for a citizen-filed complaint.

    ``str`` inheritance allows direct serialisation in JWT claims and
    JSON responses without conversion.
    """

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Complaint(TimestampMixin, Base):
    """SQLAlchemy model representing a citizen-filed stolen-vehicle complaint.

    Attributes:
        id: UUID primary key, auto-generated.
        user_id: Foreign key to the filing user.
        plate: Normalised licence plate (uppercase, no spaces).
        proof_ref: Optional reference to uploaded proof document.
        status: Current lifecycle state of the complaint.
        rejection_reason: Reason when status is REJECTED (nullable).
        created_at: UTC timestamp of complaint creation (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "complaints"

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
    plate: Mapped[str] = mapped_column(
        String(MAX_PLATE_LENGTH),
        nullable=False,
        index=True,
    )
    proof_ref: Mapped[str | None] = mapped_column(
        String(MAX_PROOF_REF_LENGTH),
        nullable=True,
    )
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus, name="complaint_status", create_constraint=True),
        nullable=False,
        default=ComplaintStatus.PENDING_VERIFICATION,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
