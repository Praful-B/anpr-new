"""Device endpoints — registration and revocation.

Routes under ``/api/v1/devices`` handle device lifecycle: registration
with token generation and admin-controlled device revocation.
"""

import base64
import binascii
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_current_user, get_db, require_role
from app.models.device import Device, DeviceType
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.user import Role, User
from app.schemas.device import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceResponse,
)
from app.security import hash_password
from app.services.audit import (
    ACTION_DEVICE_REVOKE,
    TARGET_DEVICE,
    write_audit_log,
)
from app.services.crypto import derive_device_key, wrap_key_for_device

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/devices", tags=["devices"])

logger = structlog.get_logger(__name__)

DEVICE_TOKEN_BYTES = 32
MASTER_KEY_BYTES = 32
MASTER_KEY_MISSING = "MASTER_KEY_B64 is not configured"
ACTIVE_STATUSES = (HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.ACTIVE_CONFIRMED)


def _decode_master_key() -> bytes:
    """Decode the base64-encoded master key from application settings.

    Returns:
        bytes: The 32-byte master key.

    Raises:
        HTTPException: 500 if MASTER_KEY_B64 is empty or invalid.
    """
    if not settings.MASTER_KEY_B64:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=MASTER_KEY_MISSING,
        )
    try:
        master_key = base64.b64decode(settings.MASTER_KEY_B64, validate=True)
    except binascii.Error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid MASTER_KEY_B64 encoding",
        )
    if len(master_key) != MASTER_KEY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MASTER_KEY_B64 must decode to 32 bytes",
        )
    return master_key


def _compute_version(db: Session) -> int:
    """Compute the hotlist sync version as an integer epoch.

    The version is the maximum ``updated_at`` timestamp across all
    active hotlist entries, converted to an integer epoch.

    Args:
        db: Database session.

    Returns:
        int: Integer epoch version, or 0 if no active entries exist.
    """
    latest = (
        db.query(Hotlist.updated_at)
        .filter(Hotlist.status.in_(ACTIVE_STATUSES))
        .order_by(Hotlist.updated_at.desc())
        .first()
    )

    if latest is None or latest[0] is None:
        return 0
    return int(latest[0].timestamp())


def _device_to_response(device: Device) -> DeviceResponse:
    """Convert a Device ORM instance into the public response schema.

    Args:
        device: The device ORM instance.

    Returns:
        DeviceResponse: Pydantic model safe for external responses.
    """
    return DeviceResponse(
        id=device.id,
        user_id=device.user_id,
        type=device.type.value,
        revoked=device.revoked,
        last_sync_at=device.last_sync_at,
        created_at=device.created_at,
    )


def _persist_device(
    db: Session,
    current_user: User,
    device_type: DeviceType,
) -> tuple[Device, str, bytes]:
    """Create a device row and derive its unique encryption key.

    Generates a 32-byte URL-safe token (returned once), stores only its
    bcrypt hash, derives the per-device AES key with HKDF, and wraps that
    key with the master key before persisting.

    Args:
        db: Database session.
        current_user: Owner of the new device.
        device_type: Fleet or volunteer device type.

    Returns:
        tuple[Device, str, bytes]: The device, its raw token, and its key.
    """
    master_key = _decode_master_key()
    raw_token = secrets.token_urlsafe(DEVICE_TOKEN_BYTES)

    device = Device(
        id=uuid.uuid4(),
        user_id=current_user.id,
        type=device_type,
        token_hash=hash_password(raw_token),
        encryption_key_wrapped="",
        revoked=False,
    )
    db.add(device)
    db.flush()

    version = _compute_version(db)
    device_key = derive_device_key(master_key, str(device.id), version)
    device.encryption_key_wrapped = wrap_key_for_device(device_key, master_key)
    device.key_version = version

    db.commit()
    db.refresh(device)
    return device, raw_token, device_key


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_device(
    payload: DeviceRegisterRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DeviceRegisterResponse:
    """Register a new device for the authenticated user.

    Generates a 32-byte URL-safe device token (shown once), bcrypt-hashes
    it for storage, derives a per-device encryption key using HKDF, and
    returns the device ID, raw token, and base64-encoded encryption key.

    Args:
        payload: Registration data (device type).
        current_user: Authenticated user registering the device.
        db: Database session.

    Returns:
        DeviceRegisterResponse: Device ID, token (shown once), and
            base64-encoded encryption key.
    """
    device, raw_token, device_key = _persist_device(db, current_user, payload.type)

    logger.info(
        "device_registered",
        device_id=str(device.id),
        user_id=str(current_user.id),
        device_type=payload.type.value,
    )

    return DeviceRegisterResponse(
        device_id=str(device.id),
        device_token=raw_token,
        encryption_key_b64=base64.b64encode(device_key).decode("ascii"),
    )


@router.post(
    "/{device_id}/revoke",
    response_model=DeviceResponse,
)
def revoke_device(
    device_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(Role.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> DeviceResponse:
    """Revoke a device. ADMIN only.

    Sets ``revoked=True`` on the device. The next sync attempt by the
    device will receive a 401 response.

    Args:
        device_id: UUID of the device to revoke.
        current_user: Authenticated ADMIN user.
        db: Database session.

    Returns:
        DeviceResponse: The updated device data.

    Raises:
        HTTPException: 404 if the device is not found.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    device.revoked = True
    device.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)

    write_audit_log(
        db=db,
        actor_id=current_user.id,
        action=ACTION_DEVICE_REVOKE,
        target_type=TARGET_DEVICE,
        target_id=device.id,
        metadata={"user_id": str(device.user_id)},
    )

    logger.info(
        "device_revoked",
        device_id=str(device.id),
        actor_id=str(current_user.id),
    )

    return _device_to_response(device)
