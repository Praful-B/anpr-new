"""Analytics endpoint tests.

Covers seeding sightings and hotlist entries, then asserting that
/analytics/overview, /analytics/heatmap, and /analytics/time-patterns
return correctly structured and populated responses.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.models.user import Role, User
from app.security import hash_password, create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_headers(user: User) -> dict[str, str]:
    """Generate Bearer auth headers for the given user.

    Args:
        user: The user to generate a token for.

    Returns:
        dict: Headers dict with Authorization Bearer token.
    """
    token = create_access_token(str(user.id), user.role.value)
    return {"Authorization": f"Bearer {token}"}


def _create_complaint(db_session: Session, plate: str) -> Complaint:
    """Create and flush a verified complaint for a plate.

    Args:
        db_session: Test database session.
        plate: Normalised licence plate.

    Returns:
        Complaint: The flushed complaint row.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate=plate,
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()
    return complaint


def _create_hotlist_entry(
    db_session: Session,
    plate: str,
    dismissed: bool = False,
) -> Hotlist:
    """Create and flush a hotlist entry linked to a fresh complaint.

    Args:
        db_session: Test database session.
        plate: Normalised licence plate.
        dismissed: Whether the hotlist entry is dismissed.

    Returns:
        Hotlist: The flushed hotlist entry.
    """
    complaint = _create_complaint(db_session, plate)
    hotlist_entry = Hotlist(
        id=uuid.uuid4(),
        plate=plate,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        dismissed=dismissed,
    )
    db_session.add(hotlist_entry)
    db_session.flush()
    return hotlist_entry


def _create_sighting(
    db_session: Session,
    hotlist_entry: Hotlist,
    lat: float,
    lng: float,
    captured_at: datetime,
) -> Sighting:
    """Create, commit, and refresh a sighting for a hotlist entry.

    Args:
        db_session: Test database session.
        hotlist_entry: The matched hotlist entry.
        lat: Latitude of sighting.
        lng: Longitude of sighting.
        captured_at: UTC timestamp of detection.

    Returns:
        Sighting: The committed sighting row.
    """
    sighting = Sighting(
        id=uuid.uuid4(),
        hotlist_id=hotlist_entry.id,
        device_id=uuid.uuid4(),
        lat=lat,
        lng=lng,
        captured_at=captured_at,
        photo_url="/sightings/test.jpg",
        confidence=85,
        cluster_id=uuid.uuid4(),
    )
    db_session.add(sighting)
    db_session.commit()
    db_session.refresh(hotlist_entry)
    db_session.refresh(sighting)
    return sighting


def _create_hotlist_with_sighting(
    db_session: Session,
    plate: str,
    lat: float = 19.076,
    lng: float = 72.8777,
    captured_at: datetime | None = None,
    dismissed: bool = False,
) -> tuple[Hotlist, Sighting]:
    """Create a hotlist entry and a sighting for analytics seeding.

    Args:
        db_session: Test database session.
        plate: Normalised licence plate.
        lat: Latitude of sighting.
        lng: Longitude of sighting.
        captured_at: UTC timestamp of detection (defaults to now).
        dismissed: Whether the hotlist entry is dismissed.

    Returns:
        tuple[Hotlist, Sighting]: Created hotlist and sighting.
    """
    hotlist_entry = _create_hotlist_entry(db_session, plate, dismissed)
    sighting = _create_sighting(
        db_session,
        hotlist_entry,
        lat,
        lng,
        captured_at or datetime.now(timezone.utc),
    )
    return hotlist_entry, sighting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_data(db_session: Session) -> dict:
    """Seed the database with hotlist entries and sightings for analytics.

    Creates 3 hotlist entries with sightings at different locations
    and times, and one dismissed entry for false-positive rate testing.

    Args:
        db_session: Test database session.

    Returns:
        dict: Summary of seeded data for test assertions.
    """
    now = datetime.now(timezone.utc)

    h1, s1 = _create_hotlist_with_sighting(
        db_session, "MH12AB1234", lat=19.076, lng=72.877, captured_at=now,
    )
    h2, s2 = _create_hotlist_with_sighting(
        db_session, "DL01CD5678", lat=28.613, lng=77.209, captured_at=now,
    )
    h3, s3 = _create_hotlist_with_sighting(
        db_session, "KA01EF9012", lat=12.971, lng=77.594, captured_at=now,
    )
    h4, s4 = _create_hotlist_with_sighting(
        db_session, "GJ01XX0001", lat=19.076, lng=72.877,
        captured_at=now, dismissed=True,
    )

    return {
        "hotlist_ids": [h1.id, h2.id, h3.id, h4.id],
        "sighting_ids": [s1.id, s2.id, s3.id, s4.id],
        "now": now,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_overview_returns_correct_counts(
    client: AsyncClient,
    cop_headers: dict[str, str],
    seeded_data: dict,
    db_session: Session,
) -> None:
    """GET /analytics/overview returns correct total_active_hotlist and sightings.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        seeded_data: Seeded database fixture.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If counts are incorrect.
    """
    response = await client.get(
        "/api/v1/analytics/overview",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_active_hotlist"] == 4
    assert body["total_sightings_last_24h"] == 4
    assert body["total_sightings_last_7d"] == 4
    assert "avg_time_to_first_sighting_hours" in body
    assert "avg_time_to_recovery_hours" in body


@pytest.mark.asyncio
async def test_analytics_heatmap_returns_buckets(
    client: AsyncClient,
    cop_headers: dict[str, str],
    seeded_data: dict,
) -> None:
    """GET /analytics/heatmap returns lat/lng/weight buckets.

    Two sightings at (19.076, 72.877) should produce a bucket with weight 2.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        seeded_data: Seeded database fixture.

    Returns:
        None.

    Raises:
        AssertionError: If heatmap buckets are incorrect.
    """
    response = await client.get(
        "/api/v1/analytics/heatmap",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) > 0

    for bucket in body:
        assert "lat" in bucket
        assert "lng" in bucket
        assert "weight" in bucket
        assert isinstance(bucket["lat"], float)
        assert isinstance(bucket["lng"], float)
        assert isinstance(bucket["weight"], int)

    weights = {f"{b['lat']},{b['lng']}": b["weight"] for b in body}
    assert weights.get("19.076,72.877") == 2


@pytest.mark.asyncio
async def test_analytics_time_patterns_arrays_length(
    client: AsyncClient,
    cop_headers: dict[str, str],
    seeded_data: dict,
) -> None:
    """GET /analytics/time-patterns returns by_hour (len 24) and by_day (len 7).

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        seeded_data: Seeded database fixture.

    Returns:
        None.

    Raises:
        AssertionError: If array lengths are incorrect.
    """
    response = await client.get(
        "/api/v1/analytics/time-patterns",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert "by_hour" in body
    assert "by_day" in body
    assert len(body["by_hour"]) == 24
    assert len(body["by_day"]) == 7
    assert all(isinstance(v, int) for v in body["by_hour"])
    assert all(isinstance(v, int) for v in body["by_day"])


@pytest.mark.asyncio
async def test_analytics_false_positive_rate(
    client: AsyncClient,
    cop_headers: dict[str, str],
    seeded_data: dict,
) -> None:
    """GET /analytics/false-positive-rate returns correct fp_rate.

    1 of 4 sightings has a dismissed hotlist entry → fp_rate = 25.0.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        seeded_data: Seeded database fixture.

    Returns:
        None.

    Raises:
        AssertionError: If fp_rate is incorrect.
    """
    response = await client.get(
        "/api/v1/analytics/false-positive-rate",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_hits"] == 4
    assert body["hits_dismissed_by_officer"] == 1
    assert body["fp_rate"] == 25.0
    assert "per_device" in body


@pytest.mark.asyncio
async def test_analytics_device_coverage(
    client: AsyncClient,
    cop_headers: dict[str, str],
    seeded_data: dict,
) -> None:
    """GET /analytics/device-coverage returns aggregate and per-device stats.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        seeded_data: Seeded database fixture.

    Returns:
        None.

    Raises:
        AssertionError: If coverage data is incorrect.
    """
    response = await client.get(
        "/api/v1/analytics/device-coverage",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert "total" in body
    assert "active_last_24h" in body
    assert "revoked" in body
    assert "devices" in body
    assert isinstance(body["devices"], list)


@pytest.mark.asyncio
async def test_analytics_requires_cop_role(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """Analytics endpoints require COP role; citizens get 403.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: If citizen is not rejected with 403.
    """
    response = await client.get(
        "/api/v1/analytics/overview",
        headers=citizen_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_analytics_recovery_metrics_weekly_series(
    client: AsyncClient,
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """GET /analytics/recovery-metrics reports recovered and expired counts.

    A CLOSED entry with ``recovered_at`` and an EXPIRED entry both land in
    the current ISO week with ``hotlist_added`` >= 2 and ``recovery_rate``.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the weekly series is missing or miscounted.
    """
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).date().isoformat()

    recovered_complaint = _create_complaint(db_session, "MH12AB1234")
    recovered = Hotlist(
        id=uuid.uuid4(),
        plate="MH12AB1234",
        complaint_id=recovered_complaint.id,
        status=HotlistStatus.CLOSED,
        recovered_at=now,
    )
    expired_complaint = _create_complaint(db_session, "DL01CD5678")
    expired = Hotlist(
        id=uuid.uuid4(),
        plate="DL01CD5678",
        complaint_id=expired_complaint.id,
        status=HotlistStatus.EXPIRED,
        updated_at=now,
    )
    db_session.add_all([recovered, expired])
    db_session.commit()

    response = await client.get(
        "/api/v1/analytics/recovery-metrics",
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body

    current_week = next(row for row in body if row["week_start"] == monday)
    assert current_week["hotlist_added"] >= 2
    assert current_week["recovered"] >= 1
    assert current_week["expired"] >= 1
    assert current_week["recovery_rate"] >= 0.0


@pytest.mark.asyncio
async def test_analytics_heatmap_respects_from_bound(
    client: AsyncClient,
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """The ``from`` alias bounds the heatmap window.

    An old sighting (45d ago) is excluded at the default 30-day lookback and
    reappears when ``from`` is widened to 60 days.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the window bounds are not respected.
    """
    now = datetime.now(timezone.utc)

    _create_hotlist_with_sighting(db_session, "KA01EF9012", 10.0, 11.0, now)
    _create_hotlist_with_sighting(
        db_session, "GJ01XX0001", 20.0, 21.0, now - timedelta(days=45)
    )

    narrow = await client.get(
        "/api/v1/analytics/heatmap",
        params={"from": (now - timedelta(days=30)).isoformat()},
        headers=cop_headers,
    )
    assert narrow.status_code == 200
    narrow_keys = {
        f"{b['lat']},{b['lng']}" for b in narrow.json()
    }
    assert "10.0,11.0" in narrow_keys
    assert "20.0,21.0" not in narrow_keys

    wide = await client.get(
        "/api/v1/analytics/heatmap",
        params={"from": (now - timedelta(days=60)).isoformat()},
        headers=cop_headers,
    )
    assert wide.status_code == 200
    wide_keys = {f"{b['lat']},{b['lng']}" for b in wide.json()}
    assert "10.0,11.0" in wide_keys
    assert "20.0,21.0" in wide_keys
