"""Pydantic schemas for complaint request and response payloads.

Defines the contracts for creating, listing, submitting FIR references,
and verifying complaints used by the ``/api/v1/complaints/*`` endpoints.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PLATE_INPUT_LENGTH = 20
MAX_PROOF_REF_LENGTH = 500
MAX_FIR_REF_LENGTH = 100
MAX_REJECTION_REASON_LENGTH = 1000

# Indian plate format: 2 letters, 1-2 digits, 1-3 letters, 4 digits
_PLATE_REGEX = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$"


class ComplaintCreate(BaseModel):
    """Schema for creating a new complaint.

    Attributes:
        plate: Licence plate string (will be normalised server-side).
        proof_ref: Optional reference to uploaded proof document.
    """

    model_config = ConfigDict(extra="forbid")

    plate: str = Field(
        ...,
        max_length=MAX_PLATE_INPUT_LENGTH,
        pattern=_PLATE_REGEX,
        description="Licence plate number",
    )
    proof_ref: str | None = Field(
        None,
        max_length=MAX_PROOF_REF_LENGTH,
        description="Reference to proof document",
    )


class ComplaintResponse(BaseModel):
    """Schema for complaint data returned in API responses.

    Attributes:
        id: UUID of the complaint.
        user_id: UUID of the filing user.
        plate: Normalised licence plate.
        proof_ref: Reference to proof document (may be None).
        status: Current lifecycle state.
        rejection_reason: Reason for rejection (may be None).
        created_at: UTC timestamp of creation.
        updated_at: UTC timestamp of last update.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    plate: str
    proof_ref: str | None
    status: str
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class FIRSubmit(BaseModel):
    """Schema for submitting an FIR reference on a complaint.

    Attributes:
        fir_ref: The FIR reference number provided by the citizen.
    """

    model_config = ConfigDict(extra="forbid")

    fir_ref: str = Field(
        ...,
        max_length=MAX_FIR_REF_LENGTH,
        description="FIR reference number",
    )


class VerifyRequest(BaseModel):
    """Schema for COP/ADMIN verification of a complaint.

    Attributes:
        decision: ``approve`` to verify the complaint and create a hotlist
            entry, ``reject`` to deny it.
        reason: Optional rejection reason (required when rejecting).
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str | None = Field(
        None,
        max_length=MAX_REJECTION_REASON_LENGTH,
        description="Rejection reason (required when rejecting)",
    )
