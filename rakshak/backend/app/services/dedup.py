"""Sighting deduplication and throttling services.

Provides Redis-based throttling (max 1 accepted hit per device+plate per 30s)
and cluster assignment (same plate on the same hotlist entry within 90s shares
a cluster_id).
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.models.sighting import Sighting

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

THROTTLE_TTL_SECONDS = 30
CLUSTER_WINDOW_SECONDS = 90
THROTTLE_KEY_PREFIX = "throttle"


def check_throttle(redis_client: "redis.Redis", device_id: str, plate: str) -> bool:
    """Check whether a (device_id, plate) pair is within the throttle window.

    Uses a Redis key ``throttle:{device_id}:{plate}`` with a 30-second TTL.
    Returns True if the hit should be **accepted** (key did not exist or has
    expired), False if it should be **dropped** (key still present).

    Args:
        redis_client: Redis client instance.
        device_id: UUID string of the reporting device.
        plate: Normalised licence plate string.

    Returns:
        bool: True if the hit is accepted, False if throttled.
    """
    key = f"{THROTTLE_KEY_PREFIX}:{device_id}:{plate}"
    existing = redis_client.get(key)

    if existing is not None:
        logger.debug("sighting_throttled", device_id=device_id, plate=plate)
        return False

    pipe = redis_client.pipeline()
    pipe.set(key, "1")
    pipe.expire(key, THROTTLE_TTL_SECONDS)
    pipe.execute()

    logger.debug("sighting_throttle_set", device_id=device_id, plate=plate)
    return True


def _find_existing_cluster(
    db: Session,
    hotlist_id: uuid.UUID,
    captured_at: datetime,
) -> uuid.UUID | None:
    """Look up the most recent cluster id inside the dedup window.

    Args:
        db: Database session.
        hotlist_id: UUID of the matched hotlist entry.
        captured_at: UTC timestamp of the current detection.

    Returns:
        uuid.UUID | None: A reusable cluster id, or None when none exists.
    """
    window_start = captured_at - timedelta(seconds=CLUSTER_WINDOW_SECONDS)
    window_end = captured_at + timedelta(seconds=CLUSTER_WINDOW_SECONDS)
    existing = (
        db.query(Sighting.cluster_id)
        .filter(
            Sighting.hotlist_id == hotlist_id,
            Sighting.captured_at >= window_start,
            Sighting.captured_at <= window_end,
            Sighting.cluster_id.isnot(None),
        )
        .order_by(Sighting.captured_at.desc())
        .first()
    )
    if existing is None:
        return None
    return existing[0]


def assign_cluster(
    db: Session,
    hotlist_id: uuid.UUID,
    captured_at: datetime,
) -> uuid.UUID:
    """Find or create a sighting cluster for the given hotlist entry.

    If an existing sighting for the same ``hotlist_id`` was captured within
    ``CLUSTER_WINDOW_SECONDS`` of ``captured_at``, its ``cluster_id`` is
    reused. Otherwise a new UUID is generated.

    Args:
        db: Database session.
        hotlist_id: UUID of the matched hotlist entry.
        captured_at: UTC timestamp of the current detection.

    Returns:
        uuid.UUID: The cluster_id (existing or newly generated).
    """
    existing_cluster_id = _find_existing_cluster(db, hotlist_id, captured_at)
    if existing_cluster_id is not None:
        logger.debug(
            "cluster_reused",
            hotlist_id=str(hotlist_id),
            cluster_id=str(existing_cluster_id),
        )
        return existing_cluster_id

    new_cluster_id = uuid.uuid4()
    logger.debug(
        "cluster_created",
        hotlist_id=str(hotlist_id),
        cluster_id=str(new_cluster_id),
    )
    return new_cluster_id
