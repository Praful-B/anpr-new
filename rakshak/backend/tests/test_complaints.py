"""Complaint endpoint tests.

Covers complaint creation, listing, FIR submission, and verification.
Tests rate limiting, plate normalisation, RBAC enforcement, and the
full complaint → hotlist lifecycle.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.user import User
from tests.conftest import _auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RATE_LIMIT_USER_MAX = 3


async def _create_complaint_via_api(
    client: AsyncClient,
    headers: dict[str, str],
    plate: str = "MH12AB1234",
) -> dict:
    """Create a complaint through the API and return the response body.

    Args:
        client: Async HTTP test client.
        headers: Authorization headers.
        plate: Licence plate string.

    Returns:
        dict: Response JSON body.
    """
    resp = await client.post(
        "/api/v1/complaints/",
        data={"plate": plate},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /complaints — creation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_complaint_happy_path(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """A CITIZEN can create a complaint with a normalised plate.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: On unexpected status or body.
    """
    body = await _create_complaint_via_api(client, citizen_headers, "mh12 ab 1234")
    assert body["plate"] == "MH12AB1234"
    assert body["status"] == "PENDING_VERIFICATION"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_complaint_plate_normalisation(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """Plates are normalised: uppercased, spaces and hyphens stripped.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: If plate normalisation is incorrect.
    """
    body = await _create_complaint_via_api(client, citizen_headers, "  mh-12-ab-1234  ")
    assert body["plate"] == "MH12AB1234"


@pytest.mark.asyncio
async def test_create_complaint_volunteer_allowed(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """A VOLUNTEER can also file complaints.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If volunteer is denied.
    """
    from app.models.user import Role, User
    from app.security import hash_password

    volunteer = User(
        id=uuid.uuid4(),
        name="Test Volunteer",
        email="volunteer_test@example.com",
        password_hash=hash_password("TestPass123"),
        role=Role.VOLUNTEER,
    )
    db_session.add(volunteer)
    db_session.commit()

    headers = _auth_headers(volunteer)
    body = await _create_complaint_via_api(client, headers, "DL01AB1234")
    assert body["status"] == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_create_complaint_cop_forbidden(
    client: AsyncClient,
    cop_headers: dict[str, str],
) -> None:
    """A COP cannot file complaints (RBAC: CITIZEN/VOLUNTEER only).

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for a COP user.

    Returns:
        None.

    Raises:
        AssertionError: If COP is not rejected with 403.
    """
    resp = await client.post(
        "/api/v1/complaints/",
        data={"plate": "MH12AB1234"},
        headers=cop_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_complaint_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    """Creating a complaint without auth returns 401.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If request does not return 401.
    """
    resp = await client.post(
        "/api/v1/complaints/",
        data={"plate": "MH12AB1234"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /complaints — rate limiting tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_hits_429_on_4th_call(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """After 3 successful complaint creations, the 4th returns 429.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: If the 4th call does not return 429.
    """
    for i in range(RATE_LIMIT_USER_MAX):
        resp = await client.post(
            "/api/v1/complaints/",
            data={"plate": f"MH12AB100{i}"},
            headers=citizen_headers,
        )
        assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/complaints/",
        data={"plate": "MH12AB9999"},
        headers=citizen_headers,
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ---------------------------------------------------------------------------
# GET /complaints/mine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_my_complaints(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    citizen_user: User,
) -> None:
    """GET /complaints/mine returns the current user's complaints.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If complaints are not returned correctly.
    """
    await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    await _create_complaint_via_api(client, citizen_headers, "MH12AB5678")

    resp = await client.get("/api/v1/complaints/mine", headers=citizen_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert all(c["user_id"] == str(citizen_user.id) for c in body)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/fir
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_fir_on_verified_complaint(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
    citizen_user: User,
    db_session: Session,
) -> None:
    """Submitting FIR on a verified complaint updates the hotlist entry.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If FIR submission fails.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    verify_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert verify_resp.status_code == 200

    fir_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/fir",
        json={"fir_ref": "FIR/2026/12345"},
        headers=citizen_headers,
    )
    assert fir_resp.status_code == 200
    fir_body = fir_resp.json()
    assert fir_body["fir_ref"] == "FIR/2026/12345"

    hotlist_entry = db_session.query(Hotlist).filter(
        Hotlist.complaint_id == uuid.UUID(complaint_id)
    ).first()
    assert hotlist_entry is not None
    assert hotlist_entry.fir_ref == "FIR/2026/12345"


@pytest.mark.asyncio
async def test_submit_fir_on_unverified_complaint_returns_409(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """Submitting FIR on a non-verified complaint returns 409.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: If request does not return 409.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/fir",
        json={"fir_ref": "FIR/2026/12345"},
        headers=citizen_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_submit_fir_other_users_complaint_returns_403(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Submitting FIR on another user's complaint returns 403.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If request does not return 403.
    """
    from app.models.user import Role, User
    from app.security import hash_password

    user_a = User(
        id=uuid.uuid4(),
        name="User A",
        email="user_a_test@example.com",
        password_hash=hash_password("TestPass123"),
        role=Role.CITIZEN,
    )
    user_b = User(
        id=uuid.uuid4(),
        name="User B",
        email="user_b_test@example.com",
        password_hash=hash_password("TestPass123"),
        role=Role.CITIZEN,
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()

    headers_a = _auth_headers(user_a)
    headers_b = _auth_headers(user_b)

    complaint_body = await _create_complaint_via_api(client, headers_a, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/fir",
        json={"fir_ref": "FIR/2026/12345"},
        headers=headers_b,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /complaints/{id}/verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_complaint_creates_hotlist_entry(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Approving a complaint creates a hotlist entry with correct status and deadline.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If hotlist entry is not created correctly.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "VERIFIED"

    hotlist_entry = db_session.query(Hotlist).filter(
        Hotlist.complaint_id == uuid.UUID(complaint_id)
    ).first()
    assert hotlist_entry is not None
    assert hotlist_entry.status == HotlistStatus.ACTIVE_UNCONFIRMED
    assert hotlist_entry.fir_deadline is not None
    assert hotlist_entry.plate == "MH12AB1234"


@pytest.mark.asyncio
async def test_reject_complaint_sets_rejection_reason(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Rejecting a complaint sets status to REJECTED with reason, no hotlist entry.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If rejection is not handled correctly.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "reject", "reason": "Insufficient evidence"},
        headers=cop_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "REJECTED"
    assert body["rejection_reason"] == "Insufficient evidence"

    hotlist_entry = db_session.query(Hotlist).filter(
        Hotlist.complaint_id == uuid.UUID(complaint_id)
    ).first()
    assert hotlist_entry is None


@pytest.mark.asyncio
async def test_reject_complaint_without_reason_returns_400(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
) -> None:
    """Rejecting a complaint without a reason returns 400.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.

    Returns:
        None.

    Raises:
        AssertionError: If request does not return 400.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "reject"},
        headers=cop_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reverify_verified_complaint_returns_409(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
) -> None:
    """Verifying a complaint that was already verified returns 409.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.

    Returns:
        None.

    Raises:
        AssertionError: If re-verification does not return 409.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    first = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_verify_complaint_citizen_forbidden(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """A CITIZEN cannot verify complaints (RBAC: COP/ADMIN only).

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Returns:
        None.

    Raises:
        AssertionError: If citizen is not rejected with 403.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "MH12AB1234")
    complaint_id = complaint_body["id"]

    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=citizen_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_full_lifecycle_pending_to_approve_to_hotlist(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Full lifecycle: create → pending → approve → hotlist entry with deadline.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If any step of the lifecycle fails.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "KA01MN5678")
    complaint_id = complaint_body["id"]
    assert complaint_body["status"] == "PENDING_VERIFICATION"

    complaint = db_session.query(Complaint).filter(
        Complaint.id == uuid.UUID(complaint_id)
    ).first()
    assert complaint is not None
    assert complaint.status == ComplaintStatus.PENDING_VERIFICATION

    verify_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "VERIFIED"

    hotlist_entry = db_session.query(Hotlist).filter(
        Hotlist.complaint_id == uuid.UUID(complaint_id)
    ).first()
    assert hotlist_entry is not None
    assert hotlist_entry.status == HotlistStatus.ACTIVE_UNCONFIRMED
    assert hotlist_entry.plate == "KA01MN5678"
    assert hotlist_entry.fir_deadline is not None

    now = datetime.now(timezone.utc)
    deadline = hotlist_entry.fir_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    expected_deadline = now + timedelta(hours=48)
    diff = abs((deadline - expected_deadline).total_seconds())
    assert diff < 5, f"FIR deadline should be ~48h from now, diff was {diff}s"


@pytest.mark.asyncio
async def test_full_lifecycle_pending_to_reject(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Full lifecycle: create → pending → reject → no hotlist entry.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.
        db_session: Test database session.

    Returns:
        None.

    Raises:
        AssertionError: If any step of the lifecycle fails.
    """
    complaint_body = await _create_complaint_via_api(client, citizen_headers, "GJ01CD9999")
    complaint_id = complaint_body["id"]

    verify_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/verify",
        json={"decision": "reject", "reason": "Fake report"},
        headers=cop_headers,
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "REJECTED"
    assert verify_resp.json()["rejection_reason"] == "Fake report"

    hotlist_entry = db_session.query(Hotlist).filter(
        Hotlist.complaint_id == uuid.UUID(complaint_id)
    ).first()
    assert hotlist_entry is None
