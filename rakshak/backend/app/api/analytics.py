"""Analytics endpoints — overview, heatmap, recovery metrics, and more.

All endpoints accept optional ``from`` and ``to`` query parameters
defaulting to the last 30 days. COP-only access.

Week, hour, and weekday bucketing plus duration averaging are computed in
Python from a small set of fetched timestamp columns, so identical SQL runs
on SQLite (tests) and PostgreSQL + PostGIS (production).

Endpoints:
- GET /analytics/overview
- GET /analytics/heatmap
- GET /analytics/recovery-metrics
- GET /analytics/false-positive-rate
- GET /analytics/device-coverage
- GET /analytics/time-patterns
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Sequence

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.device import Device
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.models.user import Role, User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/analytics", tags=["analytics"])

logger = structlog.get_logger(__name__)

LOOKBACK_24H_HOURS = 24
LOOKBACK_7D_DAYS = 7
LOOKBACK_30D_DAYS = 30
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
SECONDS_PER_HOUR = 3600.0
HEATMAP_GRID_DECIMALS = 3
ACTIVE_STATUSES = (HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.ACTIVE_CONFIRMED)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _default_from_date() -> datetime:
    """Compute the default start date as now minus 30 days.

    Returns:
        datetime: UTC timestamp 30 days in the past.
    """
    return datetime.now(timezone.utc) - timedelta(days=LOOKBACK_30D_DAYS)


def _to_utc(moment: datetime) -> datetime:
    """Normalise a stored timestamp to an aware UTC datetime.

    SQLAlchemy returns naive datetimes from SQLite and aware datetimes from
    PostgreSQL; both must behave identically for bucketing.

    Args:
        moment: A timestamp read from the database.

    Returns:
        datetime: The same instant, timezone-aware in UTC.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _percentage(numerator: int, denominator: int) -> float:
    """Compute an integer percentage, guarding against division by zero.

    Args:
        numerator: Value to divide.
        denominator: Divisor.

    Returns:
        float: Percentage rounded to two decimals, or 0.0 when empty.
    """
    return round(numerator / denominator * 100, 2) if denominator > 0 else 0.0


def _mean_hours(durations: Sequence[timedelta]) -> float | None:
    """Average a set of durations and convert them to hours.

    Args:
        durations: Observed durations; may be empty.

    Returns:
        float | None: Mean duration in hours rounded to two decimals, or None
        when there is nothing to average.
    """
    if not durations:
        return None
    total_seconds = sum(duration.total_seconds() for duration in durations)
    return round(total_seconds / len(durations) / SECONDS_PER_HOUR, 2)


def _timestamps(
    db: Session,
    column: Any,
    effective_from: datetime,
    now: datetime,
    extra_filters: tuple = (),
) -> list[datetime]:
    """Fetch one timestamp column for rows inside a time window.

    Args:
        db: Database session.
        column: The ``DateTime`` column to select.
        effective_from: Inclusive lower bound on the column.
        now: Inclusive upper bound on the column.
        extra_filters: Additional SQLAlchemy filter expressions.

    Returns:
        list[datetime]: Non-null timestamps matching the window.
    """
    rows = (
        db.query(column)
        .filter(column >= effective_from, column <= now, *extra_filters)
        .all()
    )
    return [row[0] for row in rows if row[0] is not None]


# ---------------------------------------------------------------------------
# Overview helpers
# ---------------------------------------------------------------------------


def _count_sightings_between(db: Session, since: datetime, until: datetime | None = None) -> int:
    """Count sightings captured within a time window.

    Args:
        db: Database session.
        since: Inclusive lower bound on ``captured_at``.
        until: Optional inclusive upper bound on ``captured_at``.

    Returns:
        int: Number of matching sightings.
    """
    query = db.query(func.count(Sighting.id)).filter(Sighting.captured_at >= since)
    if until is not None:
        query = query.filter(Sighting.captured_at <= until)
    return int(query.scalar() or 0)


def _count_active_hotlist(db: Session) -> int:
    """Count hotlist entries currently in an active state.

    Args:
        db: Database session.

    Returns:
        int: Number of ACTIVE_UNCONFIRMED or ACTIVE_CONFIRMED entries.
    """
    return int(
        db.query(func.count(Hotlist.id))
        .filter(Hotlist.status.in_(ACTIVE_STATUSES))
        .scalar()
        or 0
    )


def _count_recoveries_since(db: Session, since: datetime) -> int:
    """Count hotlist entries recovered at or after a timestamp.

    Args:
        db: Database session.
        since: Inclusive lower bound on ``recovered_at``.

    Returns:
        int: Number of CLOSED entries recovered in the window.
    """
    return int(
        db.query(func.count(Hotlist.id))
        .filter(
            Hotlist.status == HotlistStatus.CLOSED,
            Hotlist.recovered_at >= since,
        )
        .scalar()
        or 0
    )


def _first_sighting_delays(db: Session, effective_from: datetime) -> list[timedelta]:
    """Measure hotlist-added to first-sighting durations.

    Args:
        db: Database session.
        effective_from: Only hotlist entries added after this are counted.

    Returns:
        list[timedelta]: One duration per hotlist entry that has a sighting.
    """
    rows = (
        db.query(Hotlist.added_at, func.min(Sighting.captured_at))
        .outerjoin(Sighting, Sighting.hotlist_id == Hotlist.id)
        .filter(Hotlist.added_at >= effective_from)
        .group_by(Hotlist.id, Hotlist.added_at)
        .all()
    )
    return [
        _to_utc(captured_at) - _to_utc(added_at)
        for added_at, captured_at in rows
        if added_at is not None and captured_at is not None
    ]


def _recovery_delays(db: Session, effective_from: datetime) -> list[timedelta]:
    """Measure hotlist-added to recovery durations.

    Args:
        db: Database session.
        effective_from: Only hotlist entries added after this are counted.

    Returns:
        list[timedelta]: One duration per recovered hotlist entry.
    """
    rows = (
        db.query(Hotlist.added_at, Hotlist.recovered_at)
        .filter(
            Hotlist.recovered_at.isnot(None),
            Hotlist.added_at >= effective_from,
        )
        .all()
    )
    return [
        _to_utc(recovered_at) - _to_utc(added_at)
        for added_at, recovered_at in rows
        if added_at is not None and recovered_at is not None
    ]


# ---------------------------------------------------------------------------
# Heatmap helpers
# ---------------------------------------------------------------------------


def _coordinate_counts(db: Session, effective_from: datetime, now: datetime) -> Sequence[Row]:
    """Count sightings per exact coordinate pair inside the window.

    Args:
        db: Database session.
        effective_from: Inclusive lower bound on ``captured_at``.
        now: Inclusive upper bound on ``captured_at``.

    Returns:
        Sequence[Row]: Rows of (lat, lng, count).
    """
    return (
        db.query(
            Sighting.lat.label("lat"),
            Sighting.lng.label("lng"),
            func.count(Sighting.id).label("weight"),
        )
        .filter(Sighting.captured_at >= effective_from, Sighting.captured_at <= now)
        .group_by(Sighting.lat, Sighting.lng)
        .all()
    )


def _heatmap_buckets(rows: Sequence[Row]) -> list[dict]:
    """Snap coordinate counts onto a rounded grid.

    Args:
        rows: Rows produced by :func:`_coordinate_counts`.

    Returns:
        list[dict]: ``{lat, lng, weight}`` buckets, heaviest first.
    """
    buckets: dict[tuple[float, float], int] = {}
    for row in rows:
        key = (
            round(float(row[0]), HEATMAP_GRID_DECIMALS),
            round(float(row[1]), HEATMAP_GRID_DECIMALS),
        )
        buckets[key] = buckets.get(key, 0) + int(row[2])

    ordered = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    return [
        {"lat": lat, "lng": lng, "weight": weight} for (lat, lng), weight in ordered
    ]


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------


def _week_start(moment: datetime) -> str:
    """Return the ISO date of the Monday starting a timestamp's week.

    Args:
        moment: A timestamp to bucket.

    Returns:
        str: ``YYYY-MM-DD`` label identifying the containing week.
    """
    utc_moment = _to_utc(moment)
    monday = utc_moment - timedelta(days=utc_moment.weekday())
    return monday.date().isoformat()


def _week_counts(moments: Sequence[datetime]) -> dict[str, int]:
    """Group timestamps into week buckets.

    Args:
        moments: Timestamps to bucket.

    Returns:
        dict[str, int]: Mapping of week-start date to row count.
    """
    counts: dict[str, int] = {}
    for moment in moments:
        label = _week_start(moment)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _weekly_rows(
    added_map: dict[str, int],
    recovered_map: dict[str, int],
    expired_map: dict[str, int],
) -> list[dict]:
    """Assemble the per-week recovery-metrics series.

    Args:
        added_map: Weekly count of hotlist entries added.
        recovered_map: Weekly count of recovered entries.
        expired_map: Weekly count of expired entries.

    Returns:
        list[dict]: Weekly rows ordered by week start.
    """
    weeks = sorted(set(added_map) | set(recovered_map) | set(expired_map))
    return [
        {
            "week_start": week,
            "hotlist_added": added_map.get(week, 0),
            "recovered": recovered_map.get(week, 0),
            "expired": expired_map.get(week, 0),
            "recovery_rate": _percentage(
                recovered_map.get(week, 0), added_map.get(week, 0)
            ),
        }
        for week in weeks
    ]


def _hour_counts(moments: Sequence[datetime]) -> list[int]:
    """Count timestamps by UTC hour of day.

    Args:
        moments: Timestamps to bucket.

    Returns:
        list[int]: 24 counts, index 0 being 00:00 UTC.
    """
    counts = [0] * HOURS_PER_DAY
    for moment in moments:
        counts[_to_utc(moment).hour] += 1
    return counts


def _weekday_counts(moments: Sequence[datetime]) -> list[int]:
    """Count timestamps by weekday with Sunday first.

    Args:
        moments: Timestamps to bucket.

    Returns:
        list[int]: 7 counts, index 0 being Sunday and index 6 Saturday.
    """
    counts = [0] * DAYS_PER_WEEK
    for moment in moments:
        counts[(_to_utc(moment).weekday() + 1) % DAYS_PER_WEEK] += 1
    return counts


# ---------------------------------------------------------------------------
# Device helpers
# ---------------------------------------------------------------------------


def _false_positive_breakdown(
    db: Session, effective_from: datetime, now: datetime
) -> list[dict]:
    """Per-device false-positive counts.

    Args:
        db: Database session.
        effective_from: Inclusive lower bound on ``captured_at``.
        now: Inclusive upper bound on ``captured_at``.

    Returns:
        list[dict]: One entry per device with totals and dismissals.
    """
    rows = (
        db.query(
            Sighting.device_id,
            func.count(Sighting.id).label("total"),
            func.sum(case((Hotlist.dismissed.is_(True), 1), else_=0)).label("dismissed"),
        )
        .join(Hotlist, Sighting.hotlist_id == Hotlist.id)
        .filter(Sighting.captured_at >= effective_from, Sighting.captured_at <= now)
        .group_by(Sighting.device_id)
        .all()
    )
    per_device: list[dict] = []
    for row in rows:
        total = int(row[1])
        dismissed = int(row[2] or 0)
        per_device.append(
            {
                "device_id": str(row[0]),
                "total_hits": total,
                "hits_dismissed": dismissed,
                "fp_rate": _percentage(dismissed, total),
            }
        )
    return per_device


def _device_coverage_rows(db: Session) -> Sequence[Row]:
    """Fetch per-device coverage rows with sighting aggregates.

    Args:
        db: Database session.

    Returns:
        Sequence[Row]: Rows ordered by sighting count, descending.
    """
    return (
        db.query(
            Device.id,
            Device.type,
            Device.revoked,
            Device.last_sync_at,
            func.count(Sighting.id).label("total_sightings"),
            func.max(Sighting.captured_at).label("last_active"),
        )
        .outerjoin(Sighting, Sighting.device_id == Device.id)
        .group_by(Device.id, Device.type, Device.revoked, Device.last_sync_at)
        .order_by(func.count(Sighting.id).desc())
        .all()
    )


def _serialize_device_rows(rows: Sequence[Row]) -> list[dict]:
    """Convert coverage rows into JSON-ready dictionaries.

    Args:
        rows: Rows produced by :func:`_device_coverage_rows`.

    Returns:
        list[dict]: Serialized device coverage entries.
    """
    device_list: list[dict] = []
    for row in rows:
        device_list.append(
            {
                "device_id": str(row[0]),
                "type": row[1].value if hasattr(row[1], "value") else row[1],
                "revoked": row[2],
                "last_sync_at": row[3].isoformat() if row[3] else None,
                "total_sightings": int(row[4]),
                "last_active": row[5].isoformat() if row[5] else None,
            }
        )
    return device_list


def _count_revoked_devices(db: Session) -> int:
    """Count revoked devices.

    Args:
        db: Database session.

    Returns:
        int: Number of devices flagged as revoked.
    """
    return int(db.query(func.count(Device.id)).filter(Device.revoked.is_(True)).scalar() or 0)


def _count_active_devices_24h(db: Session, now: datetime) -> int:
    """Count devices that reported a sighting in the last 24 hours.

    Args:
        db: Database session.
        now: Current UTC timestamp.

    Returns:
        int: Number of distinct reporting devices.
    """
    since = now - timedelta(hours=LOOKBACK_24H_HOURS)
    return int(
        db.query(func.count(func.distinct(Sighting.device_id)))
        .filter(Sighting.captured_at >= since)
        .scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview")
def analytics_overview(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from", description="Start date"),
    to_date: datetime | None = Query(None, alias="to", description="End date"),
) -> dict:
    """Return high-level overview metrics for the COP dashboard.

    Metrics include total active hotlist entries, sightings in the last
    24h and 7d, recoveries in the last 30d, and average time from
    hotlist addition to first sighting and to recovery.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date (default: 30 days ago).
        to_date: Optional end date (default: now).

    Returns:
        dict: Overview metrics.
    """
    now = datetime.now(timezone.utc)
    effective_from = from_date or _default_from_date()

    logger.info("analytics_overview", actor_id=str(current_user.id))

    return {
        "total_active_hotlist": _count_active_hotlist(db),
        "total_sightings_last_24h": _count_sightings_between(
            db, now - timedelta(hours=LOOKBACK_24H_HOURS), now
        ),
        "total_sightings_last_7d": _count_sightings_between(
            db, now - timedelta(days=LOOKBACK_7D_DAYS), now
        ),
        "total_recoveries_last_30d": _count_recoveries_since(
            db, now - timedelta(days=LOOKBACK_30D_DAYS)
        ),
        "avg_time_to_first_sighting_hours": _mean_hours(
            _first_sighting_delays(db, effective_from)
        ),
        "avg_time_to_recovery_hours": _mean_hours(_recovery_delays(db, effective_from)),
    }


@router.get("/heatmap")
def analytics_heatmap(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
) -> list[dict]:
    """Return heatmap data with coordinates snapped to a ~100m grid.

    Sightings are grouped onto a grid rounded to three decimal places and the
    sighting count per cell is returned as the heat weight.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date.
        to_date: Optional end date.

    Returns:
        list[dict]: List of {lat, lng, weight} buckets.
    """
    effective_from = from_date or _default_from_date()
    now = datetime.now(timezone.utc)
    rows = _coordinate_counts(db, effective_from, now)
    buckets = _heatmap_buckets(rows)

    logger.info("analytics_heatmap", actor_id=str(current_user.id), buckets=len(buckets))

    return buckets


@router.get("/recovery-metrics")
def analytics_recovery_metrics(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
) -> list[dict]:
    """Return per-week recovery metrics.

    ``week_start`` is the Monday (ISO date) of each week that saw an entry
    added, recovered, or expired within the window.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date.
        to_date: Optional end date.

    Returns:
        list[dict]: Weekly time series with recovery metrics.
    """
    effective_from = from_date or _default_from_date()
    now = datetime.now(timezone.utc)

    added_map = _week_counts(
        _timestamps(db, Hotlist.added_at, effective_from, now)
    )
    recovered_map = _week_counts(
        _timestamps(
            db,
            Hotlist.recovered_at,
            effective_from,
            now,
            (Hotlist.recovered_at.isnot(None),),
        )
    )
    expired_map = _week_counts(
        _timestamps(
            db,
            Hotlist.updated_at,
            effective_from,
            now,
            (Hotlist.status == HotlistStatus.EXPIRED,),
        )
    )

    logger.info("analytics_recovery_metrics", actor_id=str(current_user.id))

    return _weekly_rows(added_map, recovered_map, expired_map)


@router.get("/false-positive-rate")
def analytics_false_positive_rate(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
) -> dict:
    """Return false-positive rate and per-device breakdown.

    A sighting is considered a false positive if its hotlist entry was
    dismissed by an officer.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date.
        to_date: Optional end date.

    Returns:
        dict: Aggregate FP rate and per-device breakdown.
    """
    effective_from = from_date or _default_from_date()
    now = datetime.now(timezone.utc)

    total_hits = _count_sightings_between(db, effective_from, now)
    dismissed_hits = (
        db.query(func.count(Sighting.id))
        .join(Hotlist, Sighting.hotlist_id == Hotlist.id)
        .filter(
            Hotlist.dismissed.is_(True),
            Sighting.captured_at >= effective_from,
            Sighting.captured_at <= now,
        )
        .scalar()
        or 0
    )

    logger.info("analytics_false_positive_rate", actor_id=str(current_user.id))

    return {
        "total_hits": total_hits,
        "hits_dismissed_by_officer": int(dismissed_hits),
        "fp_rate": _percentage(int(dismissed_hits), total_hits),
        "per_device": _false_positive_breakdown(db, effective_from, now),
    }


@router.get("/device-coverage")
def analytics_device_coverage(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
) -> dict:
    """Return device coverage statistics and aggregate counts.

    Includes per-device stats (total sightings, last active time),
    aggregate counts (total, active in last 24h, revoked), and the
    device list.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date.
        to_date: Optional end date.

    Returns:
        dict: Device coverage summary with per-device stats.
    """
    now = datetime.now(timezone.utc)

    logger.info("analytics_device_coverage", actor_id=str(current_user.id))

    return {
        "total": int(db.query(func.count(Device.id)).scalar() or 0),
        "active_last_24h": _count_active_devices_24h(db, now),
        "revoked": _count_revoked_devices(db),
        "devices": _serialize_device_rows(_device_coverage_rows(db)),
    }


@router.get("/time-patterns")
def analytics_time_patterns(
    current_user: Annotated[User, Depends(require_role(Role.COP))],
    db: Annotated[Session, Depends(get_db)],
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
) -> dict:
    """Return sighting time patterns by hour of day and day of week.

    Buckets are computed in UTC: ``by_hour`` runs 00:00–23:00 and ``by_day``
    starts at Sunday.

    Args:
        current_user: Authenticated COP user.
        db: Database session.
        from_date: Optional start date.
        to_date: Optional end date.

    Returns:
        dict: ``by_hour`` (24-element list) and ``by_day`` (7-element list).
    """
    effective_from = from_date or _default_from_date()
    now = datetime.now(timezone.utc)
    moments = _timestamps(db, Sighting.captured_at, effective_from, now)

    logger.info("analytics_time_patterns", actor_id=str(current_user.id))

    return {
        "by_hour": _hour_counts(moments),
        "by_day": _weekday_counts(moments),
    }
