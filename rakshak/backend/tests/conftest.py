"""Shared test fixtures for the RAKSHAK backend test suite.

Provides in-memory SQLite database setup, dependency overrides for
``get_db`` and ``get_redis``, and helper fixtures for creating
authenticated test clients with specific roles.
"""

import uuid
from typing import Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.deps import get_redis
from app.main import app
from app.models.user import Role, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQLALCHEMY_TEST_URL = "sqlite:///./test_rakshak.db"

# ---------------------------------------------------------------------------
# Test database engine and session
# ---------------------------------------------------------------------------

test_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# ---------------------------------------------------------------------------
# Fake Redis for rate-limit testing
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory Redis mock for testing rate limits.

    Supports the minimal Redis API used by the rate limiter:
    ``get``, ``incr``, ``expire``, ``ttl``, and ``pipeline``.
    """

    def __init__(self) -> None:
        """Initialise the in-memory store."""
        self._store: dict[str, int] = {}
        self._ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        """Return the value for *key*, or ``None`` if missing.

        Args:
            key: Redis key.

        Returns:
            str | None: Stored string or None.
        """
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        """Set a key to the given string value.

        Args:
            key: Redis key.
            value: String value to store.
        """
        self._store[key] = value

    def incr(self, key: str) -> int:
        """Increment the integer at *key* by one, initialising to 0.

        Args:
            key: Redis key.

        Returns:
            int: New value after increment.
        """
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    def expire(self, key: str, seconds: int) -> None:
        """Set a TTL on *key* (tracked but not enforced in tests).

        Args:
            key: Redis key.
            seconds: Time-to-live in seconds.
        """
        self._ttls[key] = seconds

    def ttl(self, key: str) -> int:
        """Return the remaining TTL for *key*.

        Args:
            key: Redis key.

        Returns:
            int: Remaining seconds, or -1 if no TTL set.
        """
        return self._ttls.get(key, -1)

    def pipeline(self) -> "FakePipeline":
        """Return a pipeline object for batched commands.

        Returns:
            FakePipeline: A pipeline that buffers commands.
        """
        return FakePipeline(self)


class FakePipeline:
    """Buffered command pipeline for FakeRedis.

    Collects ``incr`` and ``expite`` calls, then executes them
    all at once via ``execute``.
    """

    def __init__(self, redis: FakeRedis) -> None:
        """Initialise the pipeline.

        Args:
            redis: Parent FakeRedis instance.
        """
        self._redis = redis
        self._commands: list[tuple[str, tuple, dict]] = []

    def incr(self, key: str) -> "FakePipeline":
        """Buffer an INCR command.

        Args:
            key: Redis key.

        Returns:
            FakePipeline: Self for chaining.
        """
        self._commands.append(("incr", (key,), {}))
        return self

    def set(self, key: str, value: str) -> "FakePipeline":
        """Buffer a SET command.

        Args:
            key: Redis key.
            value: String value to store.

        Returns:
            FakePipeline: Self for chaining.
        """
        self._commands.append(("set", (key, value), {}))
        return self

    def expire(self, key: str, seconds: int) -> "FakePipeline":
        """Buffer an EXPIRE command.

        Args:
            key: Redis key.
            seconds: TTL in seconds.

        Returns:
            FakePipeline: Self for chaining.
        """
        self._commands.append(("expire", (key, seconds), {}))
        return self

    def execute(self) -> list:
        """Execute all buffered commands.

        Returns:
            list: Results of each command in order.
        """
        results = []
        for method_name, args, kwargs in self._commands:
            method = getattr(self._redis, method_name)
            result = method(*args, **kwargs)
            results.append(result)
        self._commands.clear()
        return results


# ---------------------------------------------------------------------------
# Dependency overrides
# ---------------------------------------------------------------------------

_fake_redis_instance: FakeRedis | None = None


def _override_get_db() -> Generator:
    """Provide a test-scoped database session.

    Yields:
        Session: A SQLAlchemy session bound to the test database.
    """
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _override_get_redis() -> FakeRedis:
    """Provide a shared FakeRedis instance for testing.

    Returns a singleton FakeRedis that persists across requests within
    a single test, so that rate-limit counters accumulate correctly.

    Returns:
        FakeRedis: In-memory Redis mock.
    """
    global _fake_redis_instance
    if _fake_redis_instance is None:
        _fake_redis_instance = FakeRedis()
    return _fake_redis_instance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator:
    """Create and tear down test tables for each test function.

    Also resets the shared FakeRedis instance so rate-limit counters
    do not leak between tests.

    Yields:
        None — control returns to the test after setup.
    """
    global _fake_redis_instance
    _fake_redis_instance = None
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session() -> Generator:
    """Provide a direct database session for unit-level tests.

    Yields:
        Session: A SQLAlchemy session bound to the test database.
    """
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Generator:
    """Provide an async HTTP client wired to the test app.

    Sets up dependency overrides for the database and Redis, creates
    an httpx AsyncClient with ASGI transport, and tears down overrides
    after the test.

    Yields:
        AsyncClient: httpx client using ASGI transport.
    """
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis

    transport = ASGITransport(app=app)
    async_client = AsyncClient(transport=transport, base_url="http://test")
    yield async_client

    app.dependency_overrides.clear()


@pytest.fixture()
def citizen_user(db_session) -> User:
    """Create and persist a CITIZEN user for testing.

    Args:
        db_session: Test database session.

    Returns:
        User: The created CITIZEN user.
    """
    user = User(
        id=uuid.uuid4(),
        name="Test Citizen",
        email="citizen_test@example.com",
        phone="+911234567890",
        password_hash=hash_password("TestPass123"),
        role=Role.CITIZEN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def cop_user(db_session) -> User:
    """Create and persist a COP user for testing.

    Args:
        db_session: Test database session.

    Returns:
        User: The created COP user.
    """
    user = User(
        id=uuid.uuid4(),
        name="Test Officer",
        email="cop_test@example.com",
        phone="+919876543210",
        password_hash=hash_password("TestPass123"),
        role=Role.COP,
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
    token = create_access_token(str(user.id), user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def citizen_headers(citizen_user) -> dict[str, str]:
    """Provide auth headers for a CITIZEN user.

    Args:
        citizen_user: The CITIZEN user fixture.

    Returns:
        dict: Authorization headers.
    """
    return _auth_headers(citizen_user)


@pytest.fixture()
def cop_headers(cop_user) -> dict[str, str]:
    """Provide auth headers for a COP user.

    Args:
        cop_user: The COP user fixture.

    Returns:
        dict: Authorization headers.
    """
    return _auth_headers(cop_user)
