"""Hotlist endpoint tests — RBAC, listing, detail, and state-machine rules.

Covers the COP-only listing/detail endpoints and verifies that
``PUT /api/v1/hotlist/{id}`` enforces the Flow A state machine (§2.7):
legal transitions succeed, illegal transitions return 409, unknown status
strings return 400, and repeated no-op updates stay idempotent.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus, is_legal_transition
from app.models.sighting import Sighting

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_PLATE = "MH12AB1234"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_hotlist_entry(
    db_session: Session,
    user_id: uuid.UUID,
    status: HotlistStatus = HotlistStatus.ACTIVE_UNCONFIRMED,
) -> Hotlist:
    """Create a verified complaint and its hotlist entry.

    Args:
        db_session: Test database session.
        user_id: UUID of the user who filed the complaint.
        status: Initial hotlist status.

    Returns:
        Hotlist: The created hotlist entry.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=user_id,
        plate=TEST_PLATE,
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    entry = Hotlist(
        id=uuid.uuid4(),
        plate=TEST_PLATE,
        complaint_id=complaint.id,
        status=status,
        added_at=datetime.now(timezone.utc),
        fir_deadline=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# State-machine unit tests (pure function)
# ---------------------------------------------------------------------------


def test_legal_transitions_allowed() -> None:
    """Every transition drawn in the §2.7 diagram is permitted.

    Raises:
        AssertionError: If a documented transition is rejected.
    """
    assert is_legal_transition(
        HotlistStatus.PENDING_VERIFICATION, HotlistStatus.ACTIVE_UNCONFIRMED
    )
    assert is_legal_transition(
        HotlistStatus.PENDING_VERIFICATION, HotlistStatus.REJECTED
    )
    assert is_legal_transition(
        HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.ACTIVE_CONFIRMED
    )
    assert is_legal_transition(
        HotlistStatus.ACTIVE_UNCONFIRMED, HotlistStatus.EXPIRED
    )
    assert is_legal_transition(HotlistStatus.ACTIVE_CONFIRMED, HotlistStatus.CLOSED)


def test_illegal_transitions_rejected() -> None:
    """Backwards and out-of-terminal transitions are rejected.

    Raises:
        AssertionError: If an illegal transition is accepted.
    """
    assert not is_legal_transition(
        HotlistStatus.ACTIVE_CONFIRMED, HotlistStatus.PENDING_VERIFICATION
    )
    assert not is_legal_transition(HotlistStatus.CLOSED, HotlistStatus.ACTIVE_CONFIRMED)
    assert not is_legal_transition(
        HotlistStatus.EXPIRED, HotlistStatus.ACTIVE_UNCONFIRMED
    )
    assert not is_legal_transition(
        HotlistStatus.REJECTED, HotlistStatus.ACTIVE_UNCONFIRMED
    )


def test_noop_transition_is_legal() -> None:
    """A status equal to the current one is a permitted no-op.

    Raises:
        AssertionError: If an idempotent update is rejected.
    """
    for status in HotlistStatus:
        assert is_legal_transition(status, status)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_hotlist_requires_cop(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """A citizen cannot read the hotlist.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Raises:
        AssertionError: If the citizen request is not forbidden.
    """
    response = await client.get("/api/v1/hotlist/", headers=citizen_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_hotlist_without_token_is_401(client: AsyncClient) -> None:
    """An anonymous request is rejected with 401.

    Args:
        client: Async HTTP test client.

    Raises:
        AssertionError: If the request is not unauthorized.
    """
    response = await client.get("/api/v1/hotlist/")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Listing and detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_hotlist_returns_entries(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """A COP sees the seeded hotlist entry.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the entry is missing from the response.
    """
    _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.get("/api/v1/hotlist/", headers=cop_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["plate"] == TEST_PLATE
    assert body[0]["status"] == HotlistStatus.ACTIVE_UNCONFIRMED.value


@pytest.mark.asyncio
async def test_list_hotlist_filters_by_status(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """The status query parameter filters the listing.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If filtering returns the wrong entries.
    """
    _create_hotlist_entry(db_session, citizen_user.id)

    matched = await client.get(
        "/api/v1/hotlist/",
        params={"status": HotlistStatus.ACTIVE_UNCONFIRMED.value},
        headers=cop_headers,
    )
    assert matched.status_code == 200
    assert len(matched.json()) == 1

    empty = await client.get(
        "/api/v1/hotlist/",
        params={"status": HotlistStatus.CLOSED.value},
        headers=cop_headers,
    )
    assert empty.status_code == 200
    assert empty.json() == []


@pytest.mark.asyncio
async def test_list_hotlist_invalid_status_is_400(
    client: AsyncClient,
    cop_headers: dict[str, str],
) -> None:
    """An unknown status filter returns 400.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for a COP user.

    Raises:
        AssertionError: If the response is not 400.
    """
    response = await client.get(
        "/api/v1/hotlist/",
        params={"status": "NOT_A_STATUS"},
        headers=cop_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_detail_includes_complaint_and_sightings(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """The detail endpoint embeds the complaint and a sightings list.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the detail payload is incomplete.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.get(f"/api/v1/hotlist/{entry.id}", headers=cop_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["complaint"] is not None
    assert body["complaint"]["plate"] == TEST_PLATE
    assert body["sightings"] == []


@pytest.mark.asyncio
async def test_detail_sightings_include_photo_url(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """The detail sightings expose ``photo_url`` for dashboard thumbnails.

    Phase 7 hardening: closes the stored-but-never-rendered photo gap by
    adding ``photo_url`` to the detail payload's sighting items.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the field is missing from the detail payload.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)
    sighting = Sighting(
        id=uuid.uuid4(),
        hotlist_id=entry.id,
        device_id=uuid.uuid4(),
        lat=19.076,
        lng=72.877,
        captured_at=datetime.now(timezone.utc),
        photo_url="/sightings/def456.jpg",
        confidence=90,
    )
    db_session.add(sighting)
    db_session.commit()

    response = await client.get(f"/api/v1/hotlist/{entry.id}", headers=cop_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["sightings"]) == 1
    assert body["sightings"][0]["photo_url"] == "/sightings/def456.jpg"


@pytest.mark.asyncio
async def test_detail_unknown_id_is_404(
    client: AsyncClient,
    cop_headers: dict[str, str],
) -> None:
    """A random UUID returns 404.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for a COP user.

    Raises:
        AssertionError: If the response is not 404.
    """
    response = await client.get(f"/api/v1/hotlist/{uuid.uuid4()}", headers=cop_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# State machine through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_verify_fir_transition_succeeds(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """ACTIVE_UNCONFIRMED -> ACTIVE_CONFIRMED is accepted and stores the FIR.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the transition or stored fields are wrong.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "ACTIVE_CONFIRMED", "fir_ref": "FIR-2026-001"},
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == HotlistStatus.ACTIVE_CONFIRMED.value
    assert body["fir_ref"] == "FIR-2026-001"


@pytest.mark.asyncio
async def test_put_illegal_backwards_transition_is_409(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """ACTIVE_UNCONFIRMED -> PENDING_VERIFICATION is refused with 409.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the illegal transition is accepted.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "PENDING_VERIFICATION"},
        headers=cop_headers,
    )

    assert response.status_code == 409
    db_session.refresh(entry)
    assert entry.status == HotlistStatus.ACTIVE_UNCONFIRMED


@pytest.mark.asyncio
async def test_put_illegal_from_terminal_state_is_409(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """A CLOSED entry cannot be reopened.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If a closed entry is reopened.
    """
    entry = _create_hotlist_entry(
        db_session, citizen_user.id, status=HotlistStatus.CLOSED
    )

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "ACTIVE_CONFIRMED"},
        headers=cop_headers,
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_put_recovery_transition_succeeds(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """ACTIVE_CONFIRMED -> CLOSED (recovered) stores recovered_at.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the recovery transition fails.
    """
    entry = _create_hotlist_entry(
        db_session, citizen_user.id, status=HotlistStatus.ACTIVE_CONFIRMED
    )
    recovered_at = datetime.now(timezone.utc).isoformat()

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "CLOSED", "recovered_at": recovered_at},
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == HotlistStatus.CLOSED.value
    assert body["recovered_at"] is not None


@pytest.mark.asyncio
async def test_put_noop_status_is_idempotent(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """Re-sending the current status is accepted.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the no-op update is rejected.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "ACTIVE_UNCONFIRMED"},
        headers=cop_headers,
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_put_field_only_update_skips_state_machine(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """Updating only ``dismissed`` leaves the status untouched.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the status changes or dismissal is lost.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"dismissed": True},
        headers=cop_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dismissed"] is True
    assert body["status"] == HotlistStatus.ACTIVE_UNCONFIRMED.value


@pytest.mark.asyncio
async def test_delete_soft_closes_entry(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user,
) -> None:
    """DELETE marks the entry CLOSED without removing the row.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the entry is not soft-closed.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.delete(f"/api/v1/hotlist/{entry.id}", headers=cop_headers)
    assert response.status_code == 200

    db_session.refresh(entry)
    assert entry.status == HotlistStatus.CLOSED


@pytest.mark.asyncio
async def test_put_requires_cop(
    client: AsyncClient,
    db_session: Session,
    citizen_headers: dict[str, str],
    citizen_user,
) -> None:
    """A citizen cannot mutate the hotlist.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        citizen_headers: Auth headers for a CITIZEN user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the citizen mutation is not forbidden.
    """
    entry = _create_hotlist_entry(db_session, citizen_user.id)

    response = await client.put(
        f"/api/v1/hotlist/{entry.id}",
        json={"status": "CLOSED"},
        headers=citizen_headers,
    )
    assert response.status_code == 403


@pytest.fixture(autouse=True)
def _ensure_test_tables() -> Generator[None, None, None]:
    """Keep the standard table fixture active for every test in this module.

    Yields:
        None.
    """
    yield
