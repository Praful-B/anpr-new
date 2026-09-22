"""Sighting ingestion endpoint tests.

Covers the full flow: register device → create hotlist entry → post sighting
events → verify acceptance, throttle behaviour, and cluster assignment.
Uses FakeRedis for throttle checks and mocked storage.
"""

import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.models.user import Role, User
from app.security import hash_password, create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_TOKEN = "test-device-token-abc123"
FAKE_PHOTO_B64 = ""


def _make_photo_b64() -> str:
    """Create a minimal JPEG image and return it as a base64 string.

    Returns:
        str: Base64-encoded JPEG image data.
    """
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _create_hotlist_entry(db_session: Session, plate: str) -> Hotlist:
    """Create a complaint and hotlist entry for a given plate.

    Args:
        db_session: Test database session.
        plate: Normalised licence plate string.

    Returns:
        Hotlist: The created hotlist entry.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate=plate,
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    entry = Hotlist(
        id=uuid.uuid4(),
        plate=plate,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _create_device_with_token(db_session: Session) -> tuple[str, str]:
    """Create a device with a known raw token and return (device_id, raw_token).

    Uses the real bcrypt hash so that ``get_current_device`` can verify.

    Args:
        db_session: Test database session.

    Returns:
        tuple[str, str]: (device_id_str, raw_token_str).
    """
    from app.models.device import Device, DeviceType

    raw_token = FAKE_TOKEN
    token_hash = hash_password(raw_token)

    device = Device(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=DeviceType.VOLUNTEER,
        token_hash=token_hash,
        encryption_key_wrapped="{}",
        key_version=0,
        revoked=False,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return str(device.id), raw_token


def _build_event_payload(
    plate: str = "MH12AB1234",
    lat: float = 19.076,
    lng: float = 72.8777,
    captured_at: datetime | None = None,
    photo_b64: str = "",
) -> dict:
    """Build a single sighting event dict for the ingestion API.

    Args:
        plate: Licence plate string.
        lat: Latitude.
        lng: Longitude.
        captured_at: UTC timestamp (defaults to now).
        photo_b64: Base64-encoded photo.

    Returns:
        dict: Event payload dict.
    """
    if captured_at is None:
        captured_at = datetime.now(timezone.utc)
    return {
        "plate": plate,
        "lat": lat,
        "lng": lng,
        "captured_at": captured_at.isoformat(),
        "confidence": 85,
        "photo_b64": photo_b64,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _reset_throttle_state() -> None:
    """Clear stored throttle keys on the FakeRedis dependency override.

    Returns:
        None.
    """
    from app.deps import get_redis
    from app.main import app as _app

    redis_override = _app.dependency_overrides.get(get_redis)
    if redis_override is None:
        return
    fake_redis = redis_override()
    fake_redis._store.clear()
    fake_redis._ttls.clear()


async def _post_event_batch(
    client: AsyncClient,
    raw_token: str,
    event: dict,
) -> dict:
    """POST a single-event batch and return the decoded response body.

    Args:
        client: Async HTTP test client.
        raw_token: Device token for the X-Device-Token header.
        event: The sighting event payload to send.

    Returns:
        dict: Decoded JSON response body, asserted to be HTTP 200.
    """
    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
        headers={"X-Device-Token": raw_token},
    )
    assert response.status_code == 200
    return response.json()


def _latest_sighting(
    db_session: Session,
    hotlist_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
) -> Sighting | None:
    """Fetch the newest sighting recorded for a hotlist entry.

    Args:
        db_session: Test database session.
        hotlist_id: UUID of the hotlist entry.
        exclude_id: Optional sighting id to skip (the previous hit).

    Returns:
        Sighting | None: The newest matching sighting, if any.
    """
    query = db_session.query(Sighting).filter(Sighting.hotlist_id == hotlist_id)
    if exclude_id is not None:
        query = query.filter(Sighting.id != exclude_id)
    return query.order_by(Sighting.captured_at.desc()).first()


@pytest.fixture(autouse=True)
def _patch_storage() -> None:
    """Patch the storage backend to avoid filesystem writes during tests."""
    class FakeStorage:
        """In-memory storage mock that returns fake URLs."""
        def put(self, data: bytes, content_type: str = "image/jpeg") -> str:
            """Return a fake URL for the stored data."""
            return f"/sightings/{uuid.uuid4().hex}.jpg"
        def get(self, url: str) -> bytes:
            """Return fake data."""
            return b""
        def delete(self, url: str) -> None:
                """No-op delete."""
                pass
    with patch("app.api.sightings.get_storage", return_value=FakeStorage()):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_one_event_accepted(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """POST one valid sighting event returns accepted=1.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If accepted is not 1.
    """
    device_id, raw_token = _create_device_with_token(db_session)
    _create_hotlist_entry(db_session, "MH12AB1234")

    photo_b64 = _make_photo_b64()
    event = _build_event_payload(plate="MH12AB1234", photo_b64=photo_b64)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
        headers={"X-Device-Token": raw_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["dropped"] == 0


@pytest.mark.asyncio
async def test_post_twice_within_30s_second_throttled(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Posting the same plate from the same device within 30s drops the second.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the second event is not throttled.
    """
    device_id, raw_token = _create_device_with_token(db_session)
    _create_hotlist_entry(db_session, "MH12AB1234")

    photo_b64 = _make_photo_b64()
    now = datetime.now(timezone.utc)

    event1 = _build_event_payload(plate="MH12AB1234", captured_at=now, photo_b64=photo_b64)
    event2 = _build_event_payload(plate="MH12AB1234", captured_at=now, photo_b64=photo_b64)

    resp1 = await client.post(
        "/api/v1/sightings/",
        json={"events": [event1]},
        headers={"X-Device-Token": raw_token},
    )
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] == 1

    resp2 = await client.post(
        "/api/v1/sightings/",
        json={"events": [event2]},
        headers={"X-Device-Token": raw_token},
    )
    assert resp2.status_code == 200
    assert resp2.json()["dropped"] == 1


@pytest.mark.asyncio
async def test_two_events_60s_apart_same_cluster(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Two events 60s apart for the same plate share the same cluster_id.

    Clears the fake Redis throttle between calls to simulate 30s elapsed,
    while keeping captured_at timestamps 60s apart for cluster grouping.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the cluster_ids differ.
    """
    _device_id, raw_token = _create_device_with_token(db_session)
    hotlist_entry = _create_hotlist_entry(db_session, "MH12AB1234")

    photo_b64 = _make_photo_b64()
    now = datetime.now(timezone.utc)

    first_body = await _post_event_batch(
        client,
        raw_token,
        _build_event_payload(
            plate="MH12AB1234",
            captured_at=now,
            photo_b64=photo_b64,
        ),
    )
    assert first_body["accepted"] == 1

    sighting1 = _latest_sighting(db_session, hotlist_entry.id)
    assert sighting1 is not None

    _reset_throttle_state()

    second_body = await _post_event_batch(
        client,
        raw_token,
        _build_event_payload(
            plate="MH12AB1234",
            captured_at=now + timedelta(seconds=60),
            photo_b64=photo_b64,
        ),
    )
    assert second_body["accepted"] == 1

    sighting2 = _latest_sighting(db_session, hotlist_entry.id, exclude_id=sighting1.id)
    assert sighting2 is not None
    assert sighting2.cluster_id == sighting1.cluster_id


@pytest.mark.asyncio
async def test_sighting_without_device_token_returns_401(
    client: AsyncClient,
) -> None:
    """POST /api/v1/sightings/ without X-Device-Token returns 401.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If the request does not return 401.
    """
    photo_b64 = _make_photo_b64()
    event = _build_event_payload(plate="MH12AB1234", photo_b64=photo_b64)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sighting_invalid_timestamp_dropped(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Events with timestamps more than 10 minutes old are dropped.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the stale event is accepted.
    """
    device_id, raw_token = _create_device_with_token(db_session)
    _create_hotlist_entry(db_session, "MH12AB1234")

    photo_b64 = _make_photo_b64()
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    event = _build_event_payload(
        plate="MH12AB1234",
        captured_at=stale_time,
        photo_b64=photo_b64,
    )

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
        headers={"X-Device-Token": raw_token},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["dropped"] == 1


@pytest.mark.asyncio
async def test_sighting_no_hotlist_match_dropped(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Events for plates not on the active hotlist are dropped.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If the unmatched plate is accepted.
    """
    device_id, raw_token = _create_device_with_token(db_session)

    photo_b64 = _make_photo_b64()
    event = _build_event_payload(plate="ZZ99XX9999", photo_b64=photo_b64)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
        headers={"X-Device-Token": raw_token},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["dropped"] == 1


@pytest.mark.asyncio
async def test_sighting_updates_hotlist_last_seen(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Accepted sighting updates the hotlist entry's last-seen fields.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If last-seen fields are not updated.
    """
    device_id, raw_token = _create_device_with_token(db_session)
    hotlist_entry = _create_hotlist_entry(db_session, "MH12AB1234")

    assert hotlist_entry.last_seen_at is None

    photo_b64 = _make_photo_b64()
    event = _build_event_payload(
        plate="MH12AB1234",
        lat=28.6139,
        lng=77.209,
        photo_b64=photo_b64,
    )

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [event]},
        headers={"X-Device-Token": raw_token},
    )
    assert response.status_code == 200

    db_session.refresh(hotlist_entry)
    assert hotlist_entry.last_seen_at is not None
    assert hotlist_entry.last_seen_lat == 28.6139
    assert hotlist_entry.last_seen_lng == 77.209


@pytest.mark.asyncio
async def test_list_sightings_cop_only(
    client: AsyncClient,
    cop_headers: dict[str, str],
) -> None:
    """GET /api/v1/sightings/ requires COP role.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for a COP user.

    Returns:
        None.

    Raises:
        AssertionError: If the request is not 200 for COP.
    """
    response = await client.get(
        "/api/v1/sightings/",
        headers=cop_headers,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
