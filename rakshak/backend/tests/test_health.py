"""Health-check endpoint tests.

Verifies that GET /healthz returns a 200 with the expected payload.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_healthz_returns_ok() -> None:
    """Assert /healthz returns status ok and the current version.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the response status or body is incorrect.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
