"""Auth endpoint tests.

Covers registration, login, token refresh, and RBAC enforcement.
Uses the shared conftest fixtures for test database and client setup.
"""

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.user import Role, User
from app.security import create_access_token


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_happy_path(client: AsyncClient) -> None:
    """POST /api/v1/auth/register returns 201 with user and tokens.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If status code or response body is incorrect.
    """
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "TestPass123",
            "role": "CITIZEN",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "user" in body
    assert "tokens" in body
    assert body["user"]["email"] == "test@example.com"
    assert body["user"]["role"] == "CITIZEN"
    assert "access_token" in body["tokens"]
    assert "refresh_token" in body["tokens"]


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    """POST /api/v1/auth/register with existing email returns 409.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If the second registration does not return 409.
    """
    payload = {
        "name": "Dup User",
        "email": "dup@example.com",
        "password": "TestPass123",
    }
    resp1 = await client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    """POST /api/v1/auth/login with wrong password returns 401.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If the login does not return 401.
    """
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Login User",
            "email": "login@example.com",
            "password": "CorrectPass123",
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "WrongPass999",
        },
    )
    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_protected_route_without_token_returns_401(client: AsyncClient) -> None:
    """Accessing a route protected by get_current_user without a token returns 401.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If the request does not return 401.
    """
    from app.deps import get_current_user

    test_app = FastAPI()

    @test_app.get("/protected", dependencies=[Depends(get_current_user)])
    async def protected_endpoint() -> dict:
        """Dummy protected endpoint."""
        return {"ok": True}

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/protected")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_protected_route_with_wrong_role_returns_403(client: AsyncClient) -> None:
    """A CITIZEN token accessing a COP-only route returns 403.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If the response is not 403.
    """
    from app.deps import get_current_user, require_role

    test_app = FastAPI()

    cop_dependency = require_role(Role.COP)

    @test_app.get("/cop-only", dependencies=[Depends(cop_dependency)])
    async def cop_endpoint() -> dict:
        """COP-only endpoint."""
        return {"ok": True}

    def _mock_citizen() -> User:
        """Return an unsaved CITIZEN user for the dependency override.

        Returns:
            User: A transient CITIZEN ORM instance.
        """
        return User(
            id=uuid.uuid4(),
            name="Citizen",
            email="citizen_test@example.com",
            password_hash="x",
            role=Role.CITIZEN,
        )

    test_app.dependency_overrides[get_current_user] = _mock_citizen

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/cop-only")
    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_success_returns_tokens(client: AsyncClient) -> None:
    """POST /api/v1/auth/login with valid credentials returns 200 + tokens.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If status or tokens are missing.
    """
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Login OK",
            "email": "login_ok@example.com",
            "password": "LoginPass123",
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "login_ok@example.com",
            "password": "LoginPass123",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_refresh_returns_new_tokens(client: AsyncClient) -> None:
    """POST /api/v1/auth/refresh with a valid refresh token returns new tokens.

    Args:
        client: Async HTTP test client.

    Returns:
        None.

    Raises:
        AssertionError: If status or token structure is incorrect.
    """
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Refresh User",
            "email": "refresh@example.com",
            "password": "RefreshPass123",
        },
    )
    refresh_token = reg.json()["tokens"]["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
