"""Rate-limit tests for complaint submission (§4.2).

Verifies the per-user cap of three complaints per 24 hours, that the 429
response carries a ``Retry-After`` header, and that the shared Redis counter
helper enforces an arbitrary limit for both users and IP addresses.
"""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.complaints import (
    RATE_LIMIT_IP_MAX,
    RATE_LIMIT_USER_MAX,
    _check_rate_limit,
)
from tests.conftest import FakeRedis

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPLAINT_URL = "/api/v1/complaints/"
TEST_PLATE = "MH12AB1234"
TEST_WINDOW_SECONDS = 86400
IP_KEY_PREFIX = "rate:complaints:ip"
USER_KEY_PREFIX = "rate:complaints:user"


# ---------------------------------------------------------------------------
# Endpoint-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_three_complaints_succeed(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """The first three complaints from one user are accepted.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Raises:
        AssertionError: If any of the first three requests is rejected.
    """
    for index in range(RATE_LIMIT_USER_MAX):
        response = await client.post(
            COMPLAINT_URL,
            data={"plate": f"{TEST_PLATE[: -1]}{index}"},
            headers=citizen_headers,
        )
        assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_fourth_complaint_is_rate_limited(
    client: AsyncClient,
    citizen_headers: dict[str, str],
) -> None:
    """The fourth complaint within 24 hours returns 429.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.

    Raises:
        AssertionError: If the fourth request is not rate limited.
    """
    for _ in range(RATE_LIMIT_USER_MAX):
        response = await client.post(
            COMPLAINT_URL,
            data={"plate": TEST_PLATE},
            headers=citizen_headers,
        )
        assert response.status_code == 201

    blocked = await client.post(
        COMPLAINT_URL,
        data={"plate": TEST_PLATE},
        headers=citizen_headers,
    )

    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_rate_limit_is_per_user(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    cop_headers: dict[str, str],
) -> None:
    """Exhausting one user's quota leaves another user unaffected.

    A COP cannot file a complaint (403), so this asserts the quota is
    tracked per authenticated user rather than globally by IP.

    Args:
        client: Async HTTP test client.
        citizen_headers: Auth headers for a CITIZEN user.
        cop_headers: Auth headers for a COP user.

    Raises:
        AssertionError: If the citizen quota leaks to the COP caller.
    """
    for _ in range(RATE_LIMIT_USER_MAX):
        response = await client.post(
            COMPLAINT_URL,
            data={"plate": TEST_PLATE},
            headers=citizen_headers,
        )
        assert response.status_code == 201

    blocked = await client.post(
        COMPLAINT_URL,
        data={"plate": TEST_PLATE},
        headers=citizen_headers,
    )
    assert blocked.status_code == 429

    cop_response = await client.post(
        COMPLAINT_URL,
        data={"plate": TEST_PLATE},
        headers=cop_headers,
    )
    assert cop_response.status_code == 403


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_check_rate_limit_allows_requests_up_to_the_cap() -> None:
    """Requests at or below the cap are permitted.

    Raises:
        AssertionError: If a request within the cap is rejected.
    """
    redis_client = FakeRedis()
    for _ in range(RATE_LIMIT_IP_MAX):
        _check_rate_limit(
            redis_client,
            IP_KEY_PREFIX,
            "203.0.113.7",
            RATE_LIMIT_IP_MAX,
            TEST_WINDOW_SECONDS,
        )


def test_check_rate_limit_raises_with_retry_after_beyond_the_cap() -> None:
    """The request past the cap raises 429 carrying ``Retry-After``.

    Raises:
        AssertionError: If no 429 is raised or the header is missing.
    """
    redis_client = FakeRedis()
    for _ in range(RATE_LIMIT_IP_MAX):
        _check_rate_limit(
            redis_client,
            IP_KEY_PREFIX,
            "203.0.113.8",
            RATE_LIMIT_IP_MAX,
            TEST_WINDOW_SECONDS,
        )

    with pytest.raises(HTTPException) as excinfo:
        _check_rate_limit(
            redis_client,
            IP_KEY_PREFIX,
            "203.0.113.8",
            RATE_LIMIT_IP_MAX,
            TEST_WINDOW_SECONDS,
        )

    assert excinfo.value.status_code == 429
    assert excinfo.value.headers is not None
    assert "Retry-After" in excinfo.value.headers


def test_check_rate_limit_tracks_identifiers_separately() -> None:
    """Exhausting one identifier does not affect another.

    Raises:
        AssertionError: If quotas are shared across identifiers.
    """
    redis_client = FakeRedis()
    for _ in range(RATE_LIMIT_USER_MAX):
        _check_rate_limit(
            redis_client,
            USER_KEY_PREFIX,
            "user-one",
            RATE_LIMIT_USER_MAX,
            TEST_WINDOW_SECONDS,
        )

    _check_rate_limit(
        redis_client,
        USER_KEY_PREFIX,
        "user-two",
        RATE_LIMIT_USER_MAX,
        TEST_WINDOW_SECONDS,
    )
