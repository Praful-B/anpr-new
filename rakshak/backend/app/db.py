"""SQLAlchemy engine, session factory, and declarative base.

Provides the ``get_db`` FastAPI dependency for request-scoped sessions,
the ``Base`` class that all ORM models inherit from, and the ``get_engine``
function used by Alembic's ``env.py`` to avoid duplicating connection logic.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base class for all RAKSHAK ORM models."""

    pass


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine instance.

    Used by Alembic's ``env.py`` so the connection string is not
    duplicated between ``db.py`` and the migration environment.

    Returns:
        Engine: The application's SQLAlchemy engine.
    """
    return engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Yields:
        Session: A SQLAlchemy session scoped to a single request.

    Ensures the session is closed after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
