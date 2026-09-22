"""Pydantic schemas for sighting request and response payloads.

Defines the contracts for device sighting ingestion (POST) and
COP querying of sightings (GET), including the event payload schema
for batched plate detections.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PLATE_LENGTH = 20
MAX_PHOTO_B64_LENGTH = 10 * 1024 * 1024
MIN_LATITUDE = -90.0
MAX_LATITUDE = 90.0
MIN_LONGITUDE = -180.0
MAX_LONGITUDE = 180.0

# Indian plate format: 2 letters, 1-2 digits, 1-3 letters, 4 digits
_PLATE_REGEX = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$"


class SightingEvent(BaseModel):
    """Schema for a single plate detection event within a batch.

    Attributes:
        plate: Licence plate string (normalised server-side).
        lat: Latitude of detection (WGS-84).
        lng: Longitude of detection (WGS-84).
        captured_at: UTC timestamp when the plate was detected.
        confidence: OCR confidence score (0-100).
        photo_b64: Base64-encoded JPEG photo of the plate.
    """

    model_config = ConfigDict(extra="forbid")

    plate: str = Field(
        ...,
        max_length=MAX_PLATE_LENGTH,
        pattern=_PLATE_REGEX,
        description="Licence plate number",
    )
    lat: float = Field(
        ...,
        ge=MIN_LATITUDE,
        le=MAX_LATITUDE,
        description="Latitude (WGS-84)",
    )
    lng: float = Field(
        ...,
        ge=MIN_LONGITUDE,
        le=MAX_LONGITUDE,
        description="Longitude (WGS-84)",
    )
    captured_at: datetime = Field(
        ...,
        description="UTC timestamp of detection",
    )
    confidence: int = Field(
        ...,
        ge=0,
        le=100,
        description="OCR confidence (0-100)",
    )
    photo_b64: str = Field(
        ...,
        max_length=MAX_PHOTO_B64_LENGTH,
        description="Base64-encoded JPEG photo",
    )


class SightingIngestRequest(BaseModel):
    """Schema for the batch sighting ingestion payload.

    Attributes:
        events: List of plate detection events from a single device.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[SightingEvent] = Field(
        ...,
        min_length=1,
        description="Batch of detection events",
    )


class SightingIngestResponse(BaseModel):
    """Schema returned after processing a batch of sighting events.

    Attributes:
        accepted: Number of events accepted and stored.
        dropped: Number of events dropped (throttle, invalid, etc.).
        reasons: Machine-readable reason for each dropped event.
    """

    model_config = ConfigDict(from_attributes=True)

    accepted: int = Field(..., description="Number of accepted events")
    dropped: int = Field(..., description="Number of dropped events")
    reasons: list[dict] = Field(
        default_factory=list,
        description="Per-event reasons for drops: [{index, reason}]",
    )


class SightingResponse(BaseModel):
    """Schema for sighting data returned in COP query responses.

    Attributes:
        id: UUID of the sighting.
        hotlist_id: UUID of the matched hotlist entry.
        device_id: UUID of the reporting device.
        lat: Latitude of detection.
        lng: Longitude of detection.
        captured_at: UTC timestamp of detection.
        photo_url: URL to stored photo.
        confidence: OCR confidence score.
        cluster_id: UUID grouping nearby sightings (may be None).
        created_at: UTC timestamp of record creation.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hotlist_id: UUID
    device_id: UUID
    lat: float
    lng: float
    captured_at: datetime
    photo_url: str
    confidence: int
    cluster_id: UUID | None
    created_at: datetime
