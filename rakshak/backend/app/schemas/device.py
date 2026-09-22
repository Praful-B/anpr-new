"""Pydantic schemas for device request and response payloads.

Defines the contracts for device registration, hotlist sync response,
and device revocation used by the ``/api/v1/devices/*`` and
``/api/v1/hotlist/sync`` endpoints.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.device import DeviceType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEVICE_TOKEN_LENGTH_BYTES = 32


class DeviceRegisterRequest(BaseModel):
    """Schema for device registration payload.

    Attributes:
        type: Device classification (FLEET or VOLUNTEER).
    """

    model_config = ConfigDict(extra="forbid")

    type: DeviceType = Field(
        default=DeviceType.VOLUNTEER,
        description="Device classification (FLEET or VOLUNTEER)",
    )


class DeviceRegisterResponse(BaseModel):
    """Schema returned after successful device registration.

    The ``device_token`` is shown exactly once and must be stored
    securely by the client. It cannot be retrieved again.

    Attributes:
        device_id: UUID of the newly registered device.
        device_token: URL-safe base64 device token (shown once).
        encryption_key_b64: Base64-encoded per-device encryption key.
    """

    model_config = ConfigDict(from_attributes=True)

    device_id: UUID = Field(..., description="UUID of the registered device")
    device_token: str = Field(..., description="Device token (shown once)")
    encryption_key_b64: str = Field(
        ..., description="Base64-encoded per-device encryption key"
    )


class HotlistSyncResponse(BaseModel):
    """Schema returned by the hotlist sync endpoint.

    Attributes:
        version: Integer epoch timestamp (max updated_at of hotlist entries).
        iv: Base64-encoded AES-256-GCM IV.
        ciphertext: Base64-encoded AES-256-GCM ciphertext.
        key_id: UUID of the device (identifies which key was used).
    """

    model_config = ConfigDict(from_attributes=True)

    version: int = Field(..., description="Integer epoch version of the snapshot")
    iv: str = Field(..., description="Base64-encoded IV")
    ciphertext: str = Field(..., description="Base64-encoded ciphertext")
    key_id: UUID = Field(..., description="Device UUID used for key derivation")


class DeviceResponse(BaseModel):
    """Schema for device data returned in admin responses.

    Attributes:
        id: UUID of the device.
        user_id: UUID of the registering user.
        type: Device classification.
        revoked: Whether the device has been revoked.
        last_sync_at: UTC timestamp of last sync (may be None).
        created_at: UTC timestamp of registration.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Device UUID")
    user_id: UUID = Field(..., description="Registering user UUID")
    type: DeviceType = Field(..., description="Device classification")
    revoked: bool = Field(..., description="Whether the device is revoked")
    last_sync_at: datetime | None = Field(
        None, description="Last sync timestamp"
    )
    created_at: datetime = Field(..., description="Registration timestamp")
