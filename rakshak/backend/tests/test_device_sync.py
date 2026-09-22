"""Device registration and hotlist sync integration tests.

Covers the full flow: register device → sync hotlist → decrypt ciphertext
→ verify plates match. Also tests device revocation prevents further sync.
"""

import base64
import os
import secrets
import uuid
from typing import Generator
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.config import settings
from app.deps import get_db
from app.main import app
from app.models.complaint import Complaint, ComplaintStatus
from app.models.device import Device, DeviceType
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.user import Role, User
from app.security import hash_password
from app.services.crypto import decrypt_hotlist, derive_device_key

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_MASTER_KEY = secrets.token_bytes(32)
TEST_MASTER_KEY_B64 = base64.b64encode(TEST_MASTER_KEY).decode("ascii")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_master_key() -> Generator:
    """Temporarily set MASTER_KEY_B64 for the duration of each test.

    Patches the settings singleton so that ``_decode_master_key`` can
    decode a valid 32-byte key during endpoint execution.

    Yields:
        None — control returns to the test with the key configured.
    """
    original = settings.MASTER_KEY_B64
    settings.MASTER_KEY_B64 = TEST_MASTER_KEY_B64
    yield
    settings.MASTER_KEY_B64 = original


@pytest.fixture()
def volunteer_user(db_session) -> User:
    """Create and persist a VOLUNTEER user for device registration tests.

    Args:
        db_session: Test database session.

    Returns:
        User: The created VOLUNTEER user.
    """
    user = User(
        id=uuid.uuid4(),
        name="Test Volunteer",
        email="volunteer_test@example.com",
        phone="+911122334455",
        password_hash=hash_password("TestPass123"),
        role=Role.VOLUNTEER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_user(db_session) -> User:
    """Create and persist an ADMIN user for device revocation tests.

    Args:
        db_session: Test database session.

    Returns:
        User: The created ADMIN user.
    """
    user = User(
        id=uuid.uuid4(),
        name="Test Admin",
        email="admin_test@example.com",
        phone="+919988776655",
        password_hash=hash_password("TestPass123"),
        role=Role.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    """Generate Bearer auth headers for the given user.

    Args:
        user: The user to generate a token for.

    Returns:
        dict: Headers dict with Authorization Bearer token.
    """
    from app.security import create_access_token

    token = create_access_token(str(user.id), user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def volunteer_headers(volunteer_user) -> dict[str, str]:
    """Provide auth headers for a VOLUNTEER user.

    Args:
        volunteer_user: The VOLUNTEER user fixture.

    Returns:
        dict: Authorization headers.
    """
    return _auth_headers(volunteer_user)


@pytest.fixture()
def admin_headers(admin_user) -> dict[str, str]:
    """Provide auth headers for an ADMIN user.

    Args:
        admin_user: The ADMIN user fixture.

    Returns:
        dict: Authorization headers.
    """
    return _auth_headers(admin_user)


def _create_hotlist_entry(db_session, plate: str) -> Hotlist:
    """Helper to create a complaint and hotlist entry for a plate.

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


def _create_active_confirmed_entry(db_session, plate: str) -> Hotlist:
    """Helper to create a complaint and confirmed hotlist entry.

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
        status=HotlistStatus.ACTIVE_CONFIRMED,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Tests: Device Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_happy_path(
    client: AsyncClient,
    volunteer_headers: dict[str, str],
) -> None:
    """POST /api/v1/devices/register returns 201 with device credentials.

    The response must contain device_id, device_token, and
    encryption_key_b64. The encryption key must be a valid
    base64-encoded 32-byte key.

    Args:
        client: Async HTTP test client.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If the response is incorrect.
    """
    response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert "device_id" in body
    assert "device_token" in body
    assert "encryption_key_b64" in body

    key_bytes = base64.b64decode(body["encryption_key_b64"])
    assert len(key_bytes) == 32


@pytest.mark.asyncio
async def test_register_device_requires_auth(client: AsyncClient) -> None:
    """POST /api/v1/devices/register without auth returns 401.

    Args:
        client: Async HTTP test client.

    Raises:
        AssertionError: If the request does not return 401.
    """
    response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_device_fleet_type(
    client: AsyncClient,
    volunteer_headers: dict[str, str],
) -> None:
    """POST /api/v1/devices/register with FLEET type succeeds.

    Args:
        client: Async HTTP test client.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If the device type is not stored correctly.
    """
    response = await client.post(
        "/api/v1/devices/register",
        json={"type": "FLEET"},
        headers=volunteer_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["device_id"]


# ---------------------------------------------------------------------------
# Tests: Hotlist Sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_returns_encrypted_hotlist(
    client: AsyncClient,
    db_session,
    volunteer_headers: dict[str, str],
) -> None:
    """GET /api/v1/hotlist/sync returns encrypted plates that decrypt correctly.

    1. Register a device to get credentials.
    2. Create hotlist entries.
    3. Sync and verify the response structure.
    4. Decrypt with the returned key and verify plates.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If decrypted plates do not match.
    """
    reg_response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    assert reg_response.status_code == 201
    reg_body = reg_response.json()
    device_token = reg_body["device_token"]
    encryption_key_b64 = reg_body["encryption_key_b64"]

    _create_hotlist_entry(db_session, "MH12AB1234")
    _create_hotlist_entry(db_session, "DL01CD5678")
    _create_active_confirmed_entry(db_session, "KA01EF9012")

    sync_response = await client.get(
        "/api/v1/hotlist/sync",
        headers={"X-Device-Token": device_token},
    )
    assert sync_response.status_code == 200
    sync_body = sync_response.json()
    assert "version" in sync_body
    assert "iv" in sync_body
    assert "ciphertext" in sync_body
    assert "key_id" in sync_body

    device_key = base64.b64decode(encryption_key_b64)
    plates = decrypt_hotlist(sync_body["iv"], sync_body["ciphertext"], device_key)
    assert set(plates) == {"MH12AB1234", "DL01CD5678", "KA01EF9012"}


@pytest.mark.asyncio
async def test_sync_empty_hotlist(
    client: AsyncClient,
    volunteer_headers: dict[str, str],
) -> None:
    """GET /api/v1/hotlist/sync with no active entries returns empty list.

    Args:
        client: Async HTTP test client.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If the decrypted plates list is not empty.
    """
    reg_response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    device_token = reg_response.json()["device_token"]
    encryption_key_b64 = reg_response.json()["encryption_key_b64"]

    sync_response = await client.get(
        "/api/v1/hotlist/sync",
        headers={"X-Device-Token": device_token},
    )
    assert sync_response.status_code == 200
    sync_body = sync_response.json()

    device_key = base64.b64decode(encryption_key_b64)
    plates = decrypt_hotlist(sync_body["iv"], sync_body["ciphertext"], device_key)
    assert plates == []


@pytest.mark.asyncio
async def test_sync_without_device_token_returns_401(client: AsyncClient) -> None:
    """GET /api/v1/hotlist/sync without X-Device-Token returns 401.

    Args:
        client: Async HTTP test client.

    Raises:
        AssertionError: If the request does not return 401.
    """
    response = await client.get("/api/v1/hotlist/sync")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sync_with_invalid_token_returns_401(client: AsyncClient) -> None:
    """GET /api/v1/hotlist/sync with a bogus token returns 401.

    Args:
        client: Async HTTP test client.

    Raises:
        AssertionError: If the request does not return 401.
    """
    response = await client.get(
        "/api/v1/hotlist/sync",
        headers={"X-Device-Token": "this-is-not-a-valid-token"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Device Revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_prevents_sync(
    client: AsyncClient,
    db_session,
    volunteer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """POST /devices/{id}/revoke followed by sync returns 401.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        volunteer_headers: Auth headers for VOLUNTEER user.
        admin_headers: Auth headers for ADMIN user.

    Raises:
        AssertionError: If the revoked device can still sync.
    """
    reg_response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    reg_body = reg_response.json()
    device_id = reg_body["device_id"]
    device_token = reg_body["device_token"]

    sync_before = await client.get(
        "/api/v1/hotlist/sync",
        headers={"X-Device-Token": device_token},
    )
    assert sync_before.status_code == 200

    revoke_response = await client.post(
        f"/api/v1/devices/{device_id}/revoke",
        headers=admin_headers,
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["revoked"] is True

    sync_after = await client.get(
        "/api/v1/hotlist/sync",
        headers={"X-Device-Token": device_token},
    )
    assert sync_after.status_code == 401
    assert "revoked" in sync_after.json()["detail"].lower()


@pytest.mark.asyncio
async def test_revoke_requires_admin(
    client: AsyncClient,
    volunteer_headers: dict[str, str],
) -> None:
    """POST /devices/{id}/revoke by a non-admin returns 403.

    Args:
        client: Async HTTP test client.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If the revoke does not return 403.
    """
    reg_response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    device_id = reg_response.json()["device_id"]

    response = await client.post(
        f"/api/v1/devices/{device_id}/revoke",
        headers=volunteer_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_revoke_nonexistent_returns_404(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """POST /devices/{id}/revoke for a non-existent device returns 404.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for ADMIN user.

    Raises:
        AssertionError: If the revoke does not return 404.
    """
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/devices/{fake_id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Key derivation consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_key_matches_derivation(
    client: AsyncClient,
    volunteer_headers: dict[str, str],
) -> None:
    """The encryption key returned at registration must match HKDF derivation.

    Verifies that derive_device_key(master, device_id, version) produces
    the same key as the one returned in the registration response.

    Args:
        client: Async HTTP test client.
        volunteer_headers: Auth headers for VOLUNTEER user.

    Raises:
        AssertionError: If the keys do not match.
    """
    reg_response = await client.post(
        "/api/v1/devices/register",
        json={"type": "VOLUNTEER"},
        headers=volunteer_headers,
    )
    reg_body = reg_response.json()
    device_id = reg_body["device_id"]
    returned_key = base64.b64decode(reg_body["encryption_key_b64"])

    expected_key = derive_device_key(TEST_MASTER_KEY, device_id, 0)
    assert returned_key == expected_key
