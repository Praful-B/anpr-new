"""Admin endpoint tests — user management and audit-log access.

Covers RBAC on ``/api/v1/admin``, paginated user listing with role filters,
role changes, audit queries, and the audit rows written by the privileged
mutations elsewhere in the API.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.complaint import Complaint, ComplaintStatus
from app.models.user import Role, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin_test@example.com"
ADMIN_PASSWORD = "AdminPass123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user(db_session: Session) -> User:
    """Create and persist an ADMIN user.

    Args:
        db_session: Test database session.

    Returns:
        User: The created ADMIN user.
    """
    user = User(
        id=uuid.uuid4(),
        name="Test Admin",
        email=ADMIN_EMAIL,
        phone="+919000000001",
        password_hash=hash_password(ADMIN_PASSWORD),
        role=Role.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_headers(admin_user: User) -> dict[str, str]:
    """Provide auth headers for the ADMIN user.

    Args:
        admin_user: The ADMIN user fixture.

    Returns:
        dict: Authorization headers.
    """
    token = create_access_token(str(admin_user.id), admin_user.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_users_requires_admin(
    client: AsyncClient,
    cop_headers: dict[str, str],
) -> None:
    """A COP cannot read the user list.

    Args:
        client: Async HTTP test client.
        cop_headers: Auth headers for a COP user.

    Raises:
        AssertionError: If the COP request is not forbidden.
    """
    response = await client.get("/api/v1/admin/users", headers=cop_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_users_requires_token(client: AsyncClient) -> None:
    """An anonymous request is rejected with 401.

    Args:
        client: Async HTTP test client.

    Raises:
        AssertionError: If the request is not unauthorized.
    """
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# User listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_returns_paginated_payload(
    client: AsyncClient,
    admin_headers: dict[str, str],
    citizen_user: User,
) -> None:
    """The user list is paginated and reports a total.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for an ADMIN user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the payload shape or contents are wrong.
    """
    response = await client.get("/api/v1/admin/users", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    assert body["per_page"] > 0
    emails = [item["email"] for item in body["items"]]
    assert citizen_user.email in emails


@pytest.mark.asyncio
async def test_list_users_filters_by_role(
    client: AsyncClient,
    admin_headers: dict[str, str],
    cop_user: User,
) -> None:
    """The role query parameter restricts the listing.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for an ADMIN user.
        cop_user: The COP user fixture.

    Raises:
        AssertionError: If filtering returns a non-COP user.
    """
    response = await client.get(
        "/api/v1/admin/users",
        params={"role": Role.COP.value},
        headers=admin_headers,
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(item["role"] == Role.COP.value for item in items)


@pytest.mark.asyncio
async def test_list_users_rejects_unknown_role(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """An unknown role filter returns 400.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for an ADMIN user.

    Raises:
        AssertionError: If the response is not 400.
    """
    response = await client.get(
        "/api/v1/admin/users",
        params={"role": "WIZARD"},
        headers=admin_headers,
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Role changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_user_role_changes_role_and_audits(
    client: AsyncClient,
    db_session: Session,
    admin_headers: dict[str, str],
    citizen_user: User,
) -> None:
    """Changing a role updates the user and writes an audit entry.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        admin_headers: Auth headers for an ADMIN user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the role is unchanged or no audit row is written.
    """
    response = await client.patch(
        f"/api/v1/admin/users/{citizen_user.id}/role",
        json={"role": Role.VOLUNTEER.value},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == Role.VOLUNTEER.value
    assert response.json()["id"] == str(citizen_user.id)

    audits = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "user.role_change")
        .all()
    )
    assert len(audits) == 1
    assert audits[0].metadata_json == {
        "from": Role.CITIZEN.value,
        "to": Role.VOLUNTEER.value,
    }


@pytest.mark.asyncio
async def test_update_unknown_user_role_is_404(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Changing the role of a random UUID returns 404.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for an ADMIN user.

    Raises:
        AssertionError: If the response is not 404.
    """
    response = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/role",
        json={"role": Role.COP.value},
        headers=admin_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_listing_returns_written_entries(
    client: AsyncClient,
    admin_headers: dict[str, str],
    citizen_user: User,
) -> None:
    """Audit entries written by a role change are queryable.

    Args:
        client: Async HTTP test client.
        admin_headers: Auth headers for an ADMIN user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If the audit entry is missing from the listing.
    """
    await client.patch(
        f"/api/v1/admin/users/{citizen_user.id}/role",
        json={"role": Role.VOLUNTEER.value},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/admin/audit",
        params={"action": "user.role_change"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["target_type"] == "user"


@pytest.mark.asyncio
async def test_complaint_verification_writes_audit_row(
    client: AsyncClient,
    db_session: Session,
    cop_headers: dict[str, str],
    citizen_user: User,
) -> None:
    """Approving a complaint records a complaint.verify audit entry.

    Args:
        client: Async HTTP test client.
        db_session: Test database session.
        cop_headers: Auth headers for a COP user.
        citizen_user: The CITIZEN user fixture.

    Raises:
        AssertionError: If no audit row is written for the approval.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=citizen_user.id,
        plate="MH12AB1234",
        status=ComplaintStatus.PENDING_VERIFICATION,
    )
    db_session.add(complaint)
    db_session.commit()

    response = await client.post(
        f"/api/v1/complaints/{complaint.id}/verify",
        json={"decision": "approve"},
        headers=cop_headers,
    )
    assert response.status_code == 200

    audits = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "complaint.verify")
        .all()
    )
    assert len(audits) == 1
    assert audits[0].target_id == complaint.id
    assert audits[0].metadata_json is not None
    assert audits[0].metadata_json["decision"] == "approve"
