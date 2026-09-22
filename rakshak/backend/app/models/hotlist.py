"""Hotlist model — plates active for on-device matching.

Defines the ``Hotlist`` ORM class and the ``HotlistStatus`` enum
covering the full lifecycle from PENDING_VERIFICATION through
ACTIVE_UNCONFIRMED/CONFIRMED, EXPIRED, and CLOSED.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PLATE_LENGTH = 20
MAX_FIR_REF_LENGTH = 100


class HotlistStatus(str, enum.Enum):
    """Lifecycle states for a hotlist entry.

    ``str`` inheritance allows direct serialisation in JWT claims and
    JSON responses without conversion.
    """

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE_UNCONFIRMED = "ACTIVE_UNCONFIRMED"
    ACTIVE_CONFIRMED = "ACTIVE_CONFIRMED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


# Legal status transitions from the Flow A state machine.
#   PENDING_VERIFICATION -> ACTIVE_UNCONFIRMED (approve) | REJECTED (reject)
#   ACTIVE_UNCONFIRMED   -> ACTIVE_CONFIRMED (FIR verified) | CLOSED | EXPIRED
#   ACTIVE_CONFIRMED     -> CLOSED (recovered)
#   EXPIRED, CLOSED, REJECTED are terminal.
LEGAL_TRANSITIONS: dict[HotlistStatus, frozenset[HotlistStatus]] = {
    HotlistStatus.PENDING_VERIFICATION: frozenset(
        {HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.REJECTED}
    ),
    HotlistStatus.ACTIVE_UNCONFIRMED: frozenset(
        {
            HotlistStatus.ACTIVE_CONFIRMED,
            HotlistStatus.CLOSED,
            HotlistStatus.EXPIRED,
        }
    ),
    HotlistStatus.ACTIVE_CONFIRMED: frozenset({HotlistStatus.CLOSED}),
    HotlistStatus.EXPIRED: frozenset(),
    HotlistStatus.CLOSED: frozenset(),
    HotlistStatus.REJECTED: frozenset(),
}


def is_legal_transition(current: HotlistStatus, new: HotlistStatus) -> bool:
    """Return whether a status change is permitted by the state machine.

    A no-op transition (``current`` equal to ``new``) is treated as legal so
    partial updates that echo the present status stay idempotent.

    Args:
        current: The entry's present status.
        new: The status being requested.

    Returns:
        bool: True when the transition is permitted, False otherwise.
    """
    if current == new:
        return True
    return new in LEGAL_TRANSITIONS.get(current, frozenset())


class Hotlist(TimestampMixin, Base):
    """SQLAlchemy model representing a hotlisted plate for on-device matching.

    Attributes:
        id: UUID primary key, auto-generated.
        plate: Normalised licence plate (uppercase, no spaces).
        complaint_id: Foreign key to the originating complaint.
        status: Current lifecycle state of the hotlist entry.
        added_at: UTC timestamp when the entry was added.
        fir_deadline: Deadline for FIR confirmation (48h after approval).
        fir_ref: FIR reference number submitted by the citizen.
        fir_verified_at: UTC timestamp when COP verified the FIR.
        cooldown_until: Expiry cooldown period end (7 days after expiry).
        recovered_at: UTC timestamp when vehicle was recovered.
        last_seen_at: UTC timestamp of the most recent sighting.
        last_seen_lat: Latitude of the most recent sighting.
        last_seen_lng: Longitude of the most recent sighting.
        dismissed: Whether the entry has been dismissed by an officer.
        notes: Free-text notes from officers.
        created_at: UTC timestamp of entry creation (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "hotlist"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plate: Mapped[str] = mapped_column(
        String(MAX_PLATE_LENGTH),
        nullable=False,
        index=True,
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id"),
        nullable=False,
    )
    status: Mapped[HotlistStatus] = mapped_column(
        Enum(HotlistStatus, name="hotlist_status", create_constraint=True),
        nullable=False,
        default=HotlistStatus.PENDING_VERIFICATION,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )
    fir_deadline: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    fir_ref: Mapped[str | None] = mapped_column(
        String(MAX_FIR_REF_LENGTH),
        nullable=True,
    )
    fir_verified_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    recovered_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    last_seen_lat: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    last_seen_lng: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    dismissed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
