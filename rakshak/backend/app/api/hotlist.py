"""Hotlist endpoints — listing, detail, update, soft-delete, and device sync.

Routes under ``/api/v1/hotlist`` provide COP-only access to the
hotlist of active plates for on-device matching, and a device-authenticated
sync endpoint that returns the encrypted hotlist.
"""

import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_current_device, get_db, require_role
from app.exceptions import InvalidStateTransition
from app.models.complaint import Complaint
from app.models.device import Device
from app.models.hotlist import Hotlist, HotlistStatus, is_legal_transition
from app.models.sighting import Sighting
from app.models.user import Role, User
from app.schemas.device import HotlistSyncResponse
from app.schemas.hotlist import HotlistDetailResponse, HotlistResponse, HotlistUpdate
from app.services import notifier
from app.services.audit import (
    ACTION_HOTLIST_DELETE,
    ACTION_HOTLIST_UPDATE,
    TARGET_HOTLIST,
    write_audit_log,
)
from app.services.crypto import derive_device_key, encrypt_hotlist

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/hotlist", tags=["hotlist"])

logger = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
SIGHTINGS_LIMIT = 50
MASTER_KEY_BYTES = 32
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
            detail="MASTER_KEY_B64 is not configured",
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


def _hotlist_to_response(entry: Hotlist) -> HotlistResponse:
    """Convert a Hotlist ORM instance to the response schema.

    Args:
        entry: The hotlist ORM instance.

    Returns:
        HotlistResponse: Pydantic model safe for external responses.
    """
    return HotlistResponse(
        id=entry.id,
        plate=entry.plate,
        complaint_id=entry.complaint_id,
        status=entry.status.value,
        added_at=entry.added_at,
        fir_deadline=entry.fir_deadline,
        fir_ref=entry.fir_ref,
        fir_verified_at=entry.fir_verified_at,
        cooldown_until=entry.cooldown_until,
        recovered_at=entry.recovered_at,
        last_seen_at=entry.last_seen_at,
        last_seen_lat=entry.last_seen_lat,
        last_seen_lng=entry.last_seen_lng,
        dismissed=entry.dismissed,
        notes=entry.notes,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _parse_status_filter(raw_status: str) -> HotlistStatus:
    """Convert a raw status string into a ``HotlistStatus`` value.

    Args:
        raw_status: Status string supplied by the client.

    Returns:
        HotlistStatus: The parsed enum value.

    Raises:
        HTTPException: 400 when the value is not a known status.
    """
    try:
        return HotlistStatus(raw_status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {raw_status}. "
            f"Valid values: {[s.value for s in HotlistStatus]}",
        )


def _load_hotlist_entry(db: Session, entry_id: uuid.UUID) -> Hotlist:
    """Load a hotlist entry or fail with 404.

    Args:
        db: Database session.
        entry_id: UUID of the hotlist entry.

    Returns:
        Hotlist: The matching ORM entry.

    Raises:
        HTTPException: 404 when the entry does not exist.
    """
    entry = db.query(Hotlist).filter(Hotlist.id == entry_id).first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotlist entry not found",
        )
    return entry


def _collect_active_plates(db: Session) -> tuple[list[str], int]:
    """Collect active plates for device sync along with the sync version.

    Args:
        db: Database session.

    Returns:
        tuple[list[str], int]: Plates to sync and the derived version epoch.
    """
    active_entries = (
        db.query(Hotlist).filter(Hotlist.status.in_(ACTIVE_STATUSES)).all()
    )
    return [entry.plate for entry in active_entries], _compute_version(db)


def _complaint_summary(db: Session, entry: Hotlist) -> dict | None:
    """Build the complaint payload embedded in a hotlist detail response.

    Args:
        db: Database session.
        entry: The hotlist entry whose complaint should be summarised.

    Returns:
        dict | None: Complaint summary, or None when no complaint is linked.
    """
    complaint = db.query(Complaint).filter(Complaint.id == entry.complaint_id).first()
    if complaint is None:
        return None
    return {
        "id": str(complaint.id),
        "user_id": str(complaint.user_id),
        "plate": complaint.plate,
        "proof_ref": complaint.proof_ref,
        "status": complaint.status.value,
        "rejection_reason": complaint.rejection_reason,
        "created_at": complaint.created_at.isoformat(),
        "updated_at": complaint.updated_at.isoformat(),
    }


def _recent_sightings(db: Session, entry_id: uuid.UUID) -> list[dict]:
    """Fetch the most recent sightings for a hotlist entry.

    Args:
        db: Database session.
        entry_id: UUID of the hotlist entry.

    Returns:
        list[dict]: Up to ``SIGHTINGS_LIMIT`` sightings, newest first.
    """
    sightings = (
        db.query(Sighting)
        .filter(Sighting.hotlist_id == entry_id)
        .order_by(Sighting.captured_at.desc())
        .limit(SIGHTINGS_LIMIT)
        .all()
    )
    return [
        {
            "id": str(sighting.id),
            "lat": sighting.lat,
            "lng": sighting.lng,
            "captured_at": (
                sighting.captured_at.isoformat() if sighting.captured_at else None
            ),
            "confidence": sighting.confidence,
            "photo_url": sighting.photo_url,
        }
        for sighting in sightings
    ]


def _apply_status_update(entry: Hotlist, raw_status: str) -> None:
    """Validate and apply a status change against the §2.7 state machine.

    Args:
        entry: The hotlist ORM entry to mutate.
        raw_status: The requested status string from the update payload.

    Raises:
        HTTPException: 400 when the status is unknown.
        InvalidStateTransition: When the transition is not permitted from
            the entry's current status.
    """
    new_status = _parse_status_filter(raw_status)
    if not is_legal_transition(entry.status, new_status):
        logger.info(
            "hotlist_illegal_transition",
            hotlist_entry_id=str(entry.id),
            current_status=entry.status.value,
            requested_status=new_status.value,
        )
        raise InvalidStateTransition(entry.status.value, new_status.value)
    entry.status = new_status


def _apply_hotlist_updates(entry: Hotlist, payload: HotlistUpdate) -> None:
    """Copy every provided field from the update payload onto the entry.

    Status changes are validated against the §2.7 state machine; every other
    field is assigned directly.

    Args:
        entry: The hotlist ORM entry to mutate.
        payload: Partial update payload; ``None`` fields are ignored.
    """
    if payload.status is not None:
        _apply_status_update(entry, payload.status)
    if payload.fir_ref is not None:
        entry.fir_ref = payload.fir_ref.strip()
    if payload.notes is not None:
        entry.notes = payload.notes.strip()
    if payload.dismissed is not None:
        entry.dismissed = payload.dismissed
    if payload.recovered_at is not None:
        entry.recovered_at = payload.recovered_at
    if payload.fir_verified_at is not None:
        entry.fir_verified_at = payload.fir_verified_at


# ---------------------------------------------------------------------------
# Endpoints — /sync MUST be registered before /{entry_id} to avoid
# Starlette matching "sync" as a UUID path parameter.
# ---------------------------------------------------------------------------


@router.get(
    "/sync",
    response_model=HotlistSyncResponse,
)
def sync_hotlist(
    current_device: Annotated[Device, Depends(get_current_device)],
    db: Annotated[Session, Depends(get_db)],
) -> HotlistSyncResponse:
    """Synchronise the encrypted hotlist to an authenticated device.

    Returns the current hotlist encrypted with the device's HKDF-derived
    key. Plates include all ACTIVE_UNCONFIRMED and ACTIVE_CONFIRMED entries.

    Args:
        current_device: Authenticated device from X-Device-Token.
        db: Database session.

    Returns:
        HotlistSyncResponse: Version, IV, ciphertext, and key ID.
    """
    master_key = _decode_master_key()
    plates, version = _collect_active_plates(db)

    device_key = derive_device_key(
        master_key, str(current_device.id), current_device.key_version
    )
    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, device_key)

    current_device.last_sync_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "hotlist_synced",
        device_id=str(current_device.id),
        version=version,
        plate_count=len(plates),
    )

    return HotlistSyncResponse(
        version=version,
        iv=iv_b64,
        ciphertext=ciphertext_b64,
        key_id=str(current_device.id),
    )


@router.get(
    "/",
    response_model=list[HotlistResponse],
)
def list_hotlist(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    plate: str | None = Query(None, description="Filter by plate (partial match)"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    from_date: datetime | None = Query(None, description="Filter entries added after this date"),
    to_date: datetime | None = Query(None, description="Filter entries added before this date"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
) -> list[HotlistResponse]:
    """List hotlist entries with filtering and pagination. COP only.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        plate: Optional plate filter (case-insensitive partial match).
        status_filter: Optional status filter.
        from_date: Optional start date for added_at range.
        to_date: Optional end date for added_at range.
        page: Page number (1-indexed).
        per_page: Items per page (max 100).

    Returns:
        list[HotlistResponse]: Matching hotlist entries.
    """
    query = db.query(Hotlist)

    if plate is not None:
        normalised = plate.upper().replace(" ", "").replace("-", "")
        query = query.filter(Hotlist.plate.ilike(f"%{normalised}%"))

    if status_filter is not None:
        query = query.filter(Hotlist.status == _parse_status_filter(status_filter))

    if from_date is not None:
        query = query.filter(Hotlist.added_at >= from_date)

    if to_date is not None:
        query = query.filter(Hotlist.added_at <= to_date)

    entries = (
        query.order_by(Hotlist.added_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return [_hotlist_to_response(entry) for entry in entries]


@router.get(
    "/{entry_id}",
    response_model=HotlistDetailResponse,
)
def get_hotlist_entry(
    entry_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
) -> HotlistDetailResponse:
    """Get a single hotlist entry with complaint and last 50 sightings.

    Args:
        entry_id: UUID of the hotlist entry.
        current_user: Authenticated COP user.
        db: Database session.

    Returns:
        HotlistDetailResponse: Full entry with complaint and sightings.

    Raises:
        HTTPException: 404 if the entry is not found.
    """
    entry = _load_hotlist_entry(db, entry_id)
    response = _hotlist_to_response(entry)

    return HotlistDetailResponse(
        **response.model_dump(),
        complaint=_complaint_summary(db, entry),
        sightings=_recent_sightings(db, entry_id),
    )


@router.put(
    "/{entry_id}",
    response_model=HotlistResponse,
)
def update_hotlist_entry(
    entry_id: uuid.UUID,
    payload: HotlistUpdate,
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
) -> HotlistResponse:
    """Update a hotlist entry. COP only.

    Supports updating status, fir_ref, notes, dismissed, recovered_at,
    and fir_verified_at. When status is set to CLOSED with recovered_at
    provided, the recovery timestamp is stored.

    Args:
        entry_id: UUID of the hotlist entry.
        payload: Fields to update.
        current_user: Authenticated COP user.
        db: Database session.

    Returns:
        HotlistResponse: The updated entry.

    Raises:
        HTTPException: 404 if not found, 400 on invalid status.
    """
    entry = _load_hotlist_entry(db, entry_id)
    previous_status = entry.status.value
    _apply_hotlist_updates(entry, payload)

    entry.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    notifier.schedule(
        notifier.push_hotlist_change(notifier.hotlist_payload(entry))
    )
    write_audit_log(
        db=db,
        actor_id=current_user.id,
        action=ACTION_HOTLIST_UPDATE,
        target_type=TARGET_HOTLIST,
        target_id=entry.id,
        metadata={
            "from_status": previous_status,
            "to_status": entry.status.value,
            "fields": payload.model_dump(mode="json", exclude_none=True),
        },
    )

    logger.info(
        "hotlist_entry_updated",
        hotlist_entry_id=str(entry.id),
        actor_id=str(current_user.id),
        new_status=entry.status.value,
    )

    return _hotlist_to_response(entry)


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_200_OK,
)
def delete_hotlist_entry(
    entry_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Soft-delete a hotlist entry by setting status to CLOSED. COP only.

    Args:
        entry_id: UUID of the hotlist entry.
        current_user: Authenticated COP user.
        db: Database session.

    Returns:
        dict: Confirmation with the entry ID.

    Raises:
        HTTPException: 404 if not found.
    """
    entry = _load_hotlist_entry(db, entry_id)
    previous_status = entry.status.value

    entry.status = HotlistStatus.CLOSED
    entry.updated_at = datetime.now(timezone.utc)
    db.commit()
    notifier.schedule(
        notifier.push_hotlist_change(notifier.hotlist_payload(entry))
    )
    write_audit_log(
        db=db,
        actor_id=current_user.id,
        action=ACTION_HOTLIST_DELETE,
        target_type=TARGET_HOTLIST,
        target_id=entry.id,
        metadata={"from_status": previous_status, "to_status": entry.status.value},
    )

    logger.info(
        "hotlist_entry_soft_deleted",
        hotlist_entry_id=str(entry.id),
        actor_id=str(current_user.id),
    )

    return {"id": str(entry.id), "status": HotlistStatus.CLOSED.value}
