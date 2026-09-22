"""Sighting model — device-reported plate detections.

Stores every confirmed hit event received from ANPR devices. Each sighting
links to a hotlist entry and the reporting device, and carries location,
timestamp, photo URL, and OCR confidence. Sightings within 90 seconds for
the same hotlist entry are clustered via ``cluster_id``.
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PHOTO_URL_LENGTH = 1024


class Sighting(TimestampMixin, Base):
    """SQLAlchemy model representing a confirmed plate detection event.

    Attributes:
        id: UUID primary key, auto-generated.
        hotlist_id: Foreign key to the hotlist entry that was matched.
        device_id: Foreign key to the device that reported the sighting.
        lat: Latitude of the detection (WGS-84).
        lng: Longitude of the detection (WGS-84).
        captured_at: UTC timestamp when the plate was detected on-device.
        photo_url: URL to the stored photo in the object store.
        confidence: OCR model confidence score (0-100).
        cluster_id: UUID grouping sightings of the same plate within 90s
            (nullable; assigned server-side during ingestion).
        created_at: UTC timestamp of sighting record creation (from TimestampMixin).
        updated_at: UTC timestamp of last modification (from TimestampMixin).
    """

    __tablename__ = "sightings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    hotlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotlist.id"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id"),
        nullable=False,
        index=True,
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        nullable=False,
    )
    photo_url: Mapped[str] = mapped_column(
        String(MAX_PHOTO_URL_LENGTH),
        nullable=False,
    )
    confidence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_sightings_hotlist_id_captured_at", "hotlist_id", "captured_at"),
        Index("ix_sightings_device_id_captured_at", "device_id", "captured_at"),
    )
