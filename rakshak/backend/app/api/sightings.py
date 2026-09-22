"""Sighting endpoints — ingestion from devices and querying by COPs.

POST /api/v1/sightings accepts batched plate detection events from
authenticated devices via X-Device-Token. Each event is validated,
normalised, reverified against active hotlist entries, throttled,
deduplicated, stored, and broadcast to connected COPs via WebSocket.
Non-matching plates are never stored, never logged, and never echoed
back: the response reports a reason code, not the submitted plate.

GET /api/v1/sightings provides COP-only query access with optional
plate, from, and to filters.
"""

import base64
import uuid
from datetime import datetime, timezone
from typing import Annotated

import redis
import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.deps import get_current_device, get_db, get_redis, require_role
from app.models.device import Device
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.models.user import Role, User
from app.schemas.sighting import (
    SightingEvent,
    SightingIngestRequest,
    SightingIngestResponse,
    SightingResponse,
)
from app.services import notifier
from app.services.dedup import assign_cluster, check_throttle
from app.services.normalizer import normalise_plate
from app.services.storage import StorageBackend, get_storage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/sightings", tags=["sightings"])

logger = structlog.get_logger(__name__)

TIMESTAMP_TOLERANCE_SECONDS = 600
ACTIVE_STATUSES = (HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.ACTIVE_CONFIRMED)

# Drop reasons returned to the device. They intentionally never echo the
# submitted plate: the backend must not reflect non-matching plates back
# even to the device that sent them (§2 zero-retention invariant).
REASON_ACCEPTED = "accepted"
REASON_TIMESTAMP_INVALID = "timestamp_out_of_tolerance"
REASON_PLATE_NOT_HOTLISTED = "plate_not_hotlisted"
REASON_THROTTLED = "throttled"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sighting_to_response(sighting: Sighting) -> SightingResponse:
    """Convert a Sighting ORM instance to the response schema.

    Args:
        sighting: The sighting ORM instance.

    Returns:
        SightingResponse: Pydantic model safe for external responses.
    """
    return SightingResponse(
        id=sighting.id,
        hotlist_id=sighting.hotlist_id,
        device_id=sighting.device_id,
        lat=sighting.lat,
        lng=sighting.lng,
        captured_at=sighting.captured_at,
        photo_url=sighting.photo_url,
        confidence=sighting.confidence,
        cluster_id=sighting.cluster_id,
        created_at=sighting.created_at,
    )


def _find_active_hotlist(db: Session, plate: str) -> Hotlist | None:
    """Find an active hotlist entry matching the given plate.

    Searches for entries with status ACTIVE_UNCONFIRMED or ACTIVE_CONFIRMED.

    Args:
        db: Database session.
        plate: Normalised licence plate string.

    Returns:
        Hotlist | None: Matching hotlist entry, or None if not found.
    """
    return (
        db.query(Hotlist)
        .filter(
            Hotlist.plate == plate,
            Hotlist.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )


def _update_hotlist_last_seen(
    db: Session,
    hotlist_entry: Hotlist,
    lat: float,
    lng: float,
    captured_at: datetime,
) -> None:
    """Update the hotlist entry's last-seen location and timestamp.

    Args:
        db: Database session.
        hotlist_entry: The hotlist ORM instance to update.
        lat: Latitude of the sighting.
        lng: Longitude of the sighting.
        captured_at: UTC timestamp of the detection.
    """
    hotlist_entry.last_seen_at = captured_at
    hotlist_entry.last_seen_lat = lat
    hotlist_entry.last_seen_lng = lng
    hotlist_entry.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=SightingIngestResponse,
    status_code=status.HTTP_200_OK,
)
async def ingest_sightings(
    payload: SightingIngestRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    db: Annotated[Session, Depends(get_db)],
    r: Annotated[redis.Redis, Depends(get_redis)],
) -> SightingIngestResponse:
    """Ingest a batch of plate detection events from a device.

    For each event: validates schema, checks lat/lng bounds, verifies
    timestamp within ±10 min of now, normalises the plate server-side,
    re-verifies against active hotlist entries, checks throttle, assigns
    a cluster, stores the photo, inserts the sighting, and updates the
    hotlist entry's last-seen fields.

    Args:
        payload: Batch of detection events from the device.
        current_device: Authenticated device from X-Device-Token.
        db: Database session.
        r: Redis client for throttle checks.

    Returns:
        SightingIngestResponse: Count of accepted and dropped events.
    """
    storage = get_storage()
    accepted, dropped, reasons, notifications = _process_event_batch(
        payload=payload,
        current_device=current_device,
        db=db,
        r=r,
        storage=storage,
    )

    for notification in notifications:
        await notifier.push_new_sighting(notification)

    logger.info(
        "sighting_batch_processed",
        device_id=str(current_device.id),
        accepted=accepted,
        dropped=dropped,
    )

    return SightingIngestResponse(
        accepted=accepted,
        dropped=dropped,
        reasons=reasons,
    )


def _process_event_batch(
    payload: SightingIngestRequest,
    current_device: Device,
    db: Session,
    r: redis.Redis,
    storage: StorageBackend,
) -> tuple[int, int, list[str], list[dict]]:
    """Process every event in an ingestion batch.

    Args:
        payload: Batch of detection events from the device.
        current_device: Authenticated device.
        db: Database session.
        r: Redis client for throttle checks.
        storage: Storage backend instance.

    Returns:
        tuple[int, int, list[str], list[dict]]: Accepted count, dropped
        count, the reason code for each dropped event, and the dashboard
        notification payloads for the accepted ones.
    """
    accepted = 0
    dropped = 0
    reasons: list[str] = []
    notifications: list[dict] = []

    for event in payload.events:
        result, reason, notification = _process_single_event(
            event=event,
            current_device=current_device,
            db=db,
            r=r,
            storage=storage,
        )
        if result is None:
            dropped += 1
            reasons.append(reason)
            continue
        accepted += 1
        if notification is not None:
            notifications.append(notification)

    return accepted, dropped, reasons, notifications


def _resolve_captured_at(event: SightingEvent) -> datetime | None:
    """Normalise an event timestamp to UTC and enforce the tolerance window.

    Args:
        event: The sighting event being validated.

    Returns:
        datetime | None: The UTC timestamp, or None when the event is more
        than ``TIMESTAMP_TOLERANCE_SECONDS`` away from server time.
    """
    captured_at = event.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)

    time_diff = abs((datetime.now(timezone.utc) - captured_at).total_seconds())
    if time_diff > TIMESTAMP_TOLERANCE_SECONDS:
        logger.debug(
            "sighting_timestamp_invalid",
            captured_at=captured_at.isoformat(),
            diff=time_diff,
        )
        return None
    return captured_at


def _persist_sighting(
    db: Session,
    event: SightingEvent,
    current_device: Device,
    hotlist_entry: Hotlist,
    captured_at: datetime,
    storage: StorageBackend,
) -> Sighting:
    """Store the photo, insert the sighting row, and refresh last-seen fields.

    Args:
        db: Database session.
        event: The validated detection event.
        current_device: Authenticated device that reported the hit.
        hotlist_entry: The matched active hotlist entry.
        captured_at: Normalised UTC capture timestamp.
        storage: Storage backend used to persist the photo blob.

    Returns:
        Sighting: The committed sighting row.
    """
    cluster_id = assign_cluster(db, hotlist_entry.id, captured_at)
    photo_url = storage.put(base64.b64decode(event.photo_b64))

    sighting = Sighting(
        id=uuid.uuid4(),
        hotlist_id=hotlist_entry.id,
        device_id=current_device.id,
        lat=event.lat,
        lng=event.lng,
        captured_at=captured_at,
        photo_url=photo_url,
        confidence=event.confidence,
        cluster_id=cluster_id,
    )
    db.add(sighting)

    _update_hotlist_last_seen(db, hotlist_entry, event.lat, event.lng, captured_at)
    db.commit()
    db.refresh(sighting)
    return sighting


def _log_sighting_created(
    sighting: Sighting,
    hotlist_entry: Hotlist,
    current_device: Device,
    plate: str,
) -> None:
    """Log a stored sighting with its non-reversible correlation ids.

    Args:
        sighting: The committed sighting row.
        hotlist_entry: The matched hotlist entry.
        current_device: Device that reported the hit.
        plate: The matched (hotlisted) plate.
    """
    logger.info(
        "sighting_created",
        sighting_id=str(sighting.id),
        hotlist_id=str(hotlist_entry.id),
        device_id=str(current_device.id),
        plate=plate,
    )


def _process_single_event(
    event: SightingEvent,
    current_device: Device,
    db: Session,
    r: redis.Redis,
    storage: StorageBackend,
) -> tuple[Sighting | None, str, dict | None]:
    """Validate and process a single sighting event.

    Args:
        event: The sighting event to process.
        current_device: Authenticated device.
        db: Database session.
        r: Redis client.
        storage: Storage backend instance.

    Returns:
        tuple[Sighting | None, str, dict | None]: The created sighting (or
        None), a reason code, and the dashboard notification payload when the
        event was accepted.
    """
    captured_at = _resolve_captured_at(event)
    if captured_at is None:
        return None, REASON_TIMESTAMP_INVALID, None

    normalised_plate = normalise_plate(event.plate)
    hotlist_entry = _find_active_hotlist(db, normalised_plate)
    if hotlist_entry is None:
        return None, REASON_PLATE_NOT_HOTLISTED, None

    if not check_throttle(r, str(current_device.id), normalised_plate):
        return None, REASON_THROTTLED, None

    sighting = _persist_sighting(
        db=db,
        event=event,
        current_device=current_device,
        hotlist_entry=hotlist_entry,
        captured_at=captured_at,
        storage=storage,
    )
    _log_sighting_created(sighting, hotlist_entry, current_device, normalised_plate)
    return sighting, REASON_ACCEPTED, notifier.sighting_payload(sighting, normalised_plate)


@router.get(
    "/",
    response_model=list[SightingResponse],
)
def list_sightings(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    plate: str | None = Query(None, description="Filter by plate"),
    from_date: datetime | None = Query(None, description="Start date filter"),
    to_date: datetime | None = Query(None, description="End date filter"),
) -> list[SightingResponse]:
    """Query sightings with optional plate and date filters. COP only.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        plate: Optional plate filter (normalised, exact match).
        from_date: Optional start date for captured_at range.
        to_date: Optional end date for captured_at range.

    Returns:
        list[SightingResponse]: Matching sightings, newest first.
    """
    query = db.query(Sighting)

    if plate is not None:
        normalised = plate.upper().replace(" ", "").replace("-", "")
        query = query.join(Hotlist, Sighting.hotlist_id == Hotlist.id)
        query = query.filter(Hotlist.plate == normalised)

    if from_date is not None:
        query = query.filter(Sighting.captured_at >= from_date)

    if to_date is not None:
        query = query.filter(Sighting.captured_at <= to_date)

    sightings = (
        query.order_by(Sighting.captured_at.desc())
        .limit(200)
        .all()
    )

    return [_sighting_to_response(s) for s in sightings]
