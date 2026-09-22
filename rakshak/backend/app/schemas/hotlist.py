"""Pydantic schemas for hotlist request and response payloads.

Defines the contracts for listing, retrieving, updating, and
soft-deleting hotlist entries used by the ``/api/v1/hotlist/*`` endpoints.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.hotlist import HotlistStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FIR_REF_LENGTH = 100
MAX_NOTES_LENGTH = 5000


class HotlistResponse(BaseModel):
    """Schema for hotlist data returned in list and detail responses.

    Attributes:
        id: UUID of the hotlist entry.
        plate: Normalised licence plate.
        complaint_id: UUID of the originating complaint.
        status: Current lifecycle state.
        added_at: UTC timestamp when added.
        fir_deadline: Deadline for FIR confirmation (may be None).
        fir_ref: FIR reference number (may be None).
        fir_verified_at: UTC timestamp of FIR verification (may be None).
        cooldown_until: Cooldown period end (may be None).
        recovered_at: UTC timestamp of recovery (may be None).
        last_seen_at: UTC timestamp of most recent sighting (may be None).
        last_seen_lat: Latitude of most recent sighting (may be None).
        last_seen_lng: Longitude of most recent sighting (may be None).
        dismissed: Whether dismissed by officer.
        notes: Officer notes (may be None).
        created_at: UTC timestamp of creation.
        updated_at: UTC timestamp of last update.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plate: str
    complaint_id: UUID
    status: HotlistStatus
    added_at: datetime
    fir_deadline: datetime | None
    fir_ref: str | None
    fir_verified_at: datetime | None
    cooldown_until: datetime | None
    recovered_at: datetime | None
    last_seen_at: datetime | None
    last_seen_lat: float | None
    last_seen_lng: float | None
    dismissed: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class HotlistUpdate(BaseModel):
    """Schema for updating a hotlist entry (COP only).

    All fields are optional; only provided fields are updated.
    Setting status to CLOSED with recovered_at sets the recovery time.

    Attributes:
        status: New lifecycle state.
        fir_ref: FIR reference number.
        notes: Free-text officer notes.
        dismissed: Whether to dismiss the entry.
        recovered_at: UTC timestamp of vehicle recovery.
        fir_verified_at: UTC timestamp of FIR verification.
    """

    model_config = ConfigDict(extra="forbid")

    status: HotlistStatus | None = Field(
        None,
        description="New lifecycle status for the hotlist entry",
    )
    fir_ref: str | None = Field(
        None,
        max_length=MAX_FIR_REF_LENGTH,
        description="FIR reference number",
    )
    notes: str | None = Field(
        None,
        max_length=MAX_NOTES_LENGTH,
        description="Free-text officer notes",
    )
    dismissed: bool | None = Field(
        None,
        description="Whether to dismiss the entry",
    )
    recovered_at: datetime | None = Field(
        None,
        description="UTC timestamp of vehicle recovery",
    )
    fir_verified_at: datetime | None = Field(
        None,
        description="UTC timestamp of FIR verification",
    )


class HotlistDetailResponse(HotlistResponse):
    """Extended hotlist response for detail view including complaint and sightings.

    Attributes:
        complaint: The originating complaint data.
        sightings: List of the last 50 sightings (empty list if none).
    """

    model_config = ConfigDict(from_attributes=True)

    complaint: dict | None = None
    sightings: list[dict] = Field(default_factory=list)
