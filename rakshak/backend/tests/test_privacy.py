"""Zero-retention privacy invariant tests.

The product's core promise is that the backend never stores, logs, or echoes
a plate that is not on the active hotlist. These tests enforce that promise
directly against the ingestion pipeline:

1. An unmatched plate creates no sighting row.
2. The ingestion response never contains the submitted plate string.
3. No logger call made while handling the batch contains that plate string.
4. The positive path still works, so the checks above are meaningful.
"""

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.api import sightings as sightings_api
from app.models.complaint import Complaint, ComplaintStatus
from app.models.device import Device, DeviceType
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.security import hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEVICE_TOKEN = "privacy-test-device-token"
HOTLISTED_PLATE = "MH12AB1234"
UNMATCHED_PLATE = "KA05ZZ4321"
UNMATCHED_PLATE_OCR = "KA05ZZ432L"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RecordingLogger:
    """Stand-in for the structlog logger that records every call.

    Records ``(event_name, args, kwargs)`` for each attribute access used as
    a logging method, so tests can assert that no call mentions a plate string.
    """

    def __init__(self) -> None:
        """Initialise an empty call list."""
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        """Return a recording function for any logger method.

        Args:
            name: The logger method being called (e.g. ``info``).

        Returns:
            A callable that appends to ``self.calls``.
        """

        def _record(*args: Any, **kwargs: Any) -> None:
            """Record a single logging call.

            Args:
                *args: Positional arguments passed to the logger.
                **kwargs: Keyword arguments passed to the logger.
            """
            self.calls.append((name, args, kwargs))

        return _record

    def mentions(self, needle: str) -> bool:
        """Report whether any recorded call contains ``needle``.

        Args:
            needle: The substring to search for.

        Returns:
            bool: True when any argument or keyword value contains ``needle``.
        """
        haystack = repr(self.calls)
        return needle in haystack


def _create_device(db_session: Session) -> str:
    """Create a device with a known token and return the raw token.

    Args:
        db_session: Test database session.

    Returns:
        str: The raw device token.
    """
    device = Device(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=DeviceType.VOLUNTEER,
        token_hash=hash_password(DEVICE_TOKEN),
        encryption_key_wrapped="{}",
        key_version=0,
        revoked=False,
    )
    db_session.add(device)
    db_session.commit()
    return DEVICE_TOKEN


def _create_hotlist_entry(db_session: Session) -> Hotlist:
    """Create a complaint and active hotlist entry for the matched plate.

    Args:
        db_session: Test database session.

    Returns:
        Hotlist: The created hotlist entry.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate=HOTLISTED_PLATE,
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    entry = Hotlist(
        id=uuid.uuid4(),
        plate=HOTLISTED_PLATE,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _event(plate: str) -> dict:
    """Build a single sighting event payload.

    Args:
        plate: The plate string to submit.

    Returns:
        dict: An ingestion event payload.
    """
    return {
        "plate": plate,
        "lat": 19.076,
        "lng": 72.8777,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "confidence": 82,
        "photo_b64": "",
    }


@pytest.fixture(autouse=True)
def _patch_storage():
    """Replace the storage backend with an in-memory stand-in.

    Yields:
        None — the patch is active for the duration of the test.
    """

    class FakeStorage:
        """Storage mock that never touches the filesystem."""

        def put(self, data: bytes, content_type: str = "image/jpeg") -> str:
            """Return a synthetic URL."""
            return f"/sightings/{uuid.uuid4().hex}.jpg"

        def get(self, url: str) -> bytes:
            """Return empty bytes."""
            return b""

        def delete(self, url: str) -> None:
            """Do nothing."""
            return None

    with patch("app.api.sightings.get_storage", return_value=FakeStorage()):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unmatched_plate_creates_no_sighting_row(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """A plate absent from the hotlist must not be persisted.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Raises:
        AssertionError: If a sighting row is created for the unmatched plate.
    """
    _create_device(db_session)
    _create_hotlist_entry(db_session)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(UNMATCHED_PLATE)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["dropped"] == 1

    total = db_session.query(Sighting).count()
    assert total == 0


@pytest.mark.asyncio
async def test_unmatched_plate_is_not_echoed_in_response(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """The ingestion response must not contain the submitted plate string.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Raises:
        AssertionError: If the response echoes the unmatched plate.
    """
    _create_device(db_session)
    _create_hotlist_entry(db_session)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(UNMATCHED_PLATE_OCR)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    assert response.status_code == 200
    assert UNMATCHED_PLATE_OCR not in response.text
    assert "KA05ZZ4321" not in response.text


@pytest.mark.asyncio
async def test_unmatched_plate_is_never_logged(
    client: AsyncClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No logger call while handling the batch may mention the plate.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        monkeypatch: Pytest fixture used to swap in the recording logger.

    Raises:
        AssertionError: If any log call contains the unmatched plate.
    """
    _create_device(db_session)
    _create_hotlist_entry(db_session)

    recorder = RecordingLogger()
    monkeypatch.setattr(sightings_api, "logger", recorder)

    await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(UNMATCHED_PLATE)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    assert recorder.mentions(UNMATCHED_PLATE) is False


@pytest.mark.asyncio
async def test_matched_plate_is_persisted_and_logged(
    client: AsyncClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive path stores the hit and logs the matched plate.

    This proves the privacy assertions above are not vacuous: a hotlisted
    plate does produce both a row and a log entry.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        monkeypatch: Pytest fixture used to swap in the recording logger.

    Raises:
        AssertionError: If the matched plate is not stored or not logged.
    """
    _create_device(db_session)
    _create_hotlist_entry(db_session)

    recorder = RecordingLogger()
    monkeypatch.setattr(sightings_api, "logger", recorder)

    response = await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(HOTLISTED_PLATE)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert db_session.query(Sighting).count() == 1
    assert recorder.mentions(HOTLISTED_PLATE) is True


@pytest.mark.asyncio
async def test_unmatched_plate_stays_absent_after_a_match(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """A matched hit does not cause the unmatched plate to be stored.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Raises:
        AssertionError: If only the matched plate is not the sole stored row.
    """
    _create_device(db_session)
    _create_hotlist_entry(db_session)

    await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(HOTLISTED_PLATE)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )
    await client.post(
        "/api/v1/sightings/",
        json={"events": [_event(UNMATCHED_PLATE)]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    rows = db_session.query(Sighting).all()
    assert len(rows) == 1
    stored_hotlist = db_session.query(Hotlist).filter(
        Hotlist.id == rows[0].hotlist_id
    ).first()
    assert stored_hotlist is not None
    assert stored_hotlist.plate == HOTLISTED_PLATE
