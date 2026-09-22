"""Idempotency tests for the database seeding script.

The demo seeding script must be safe to run repeatedly: users are keyed by
email and the sample hotlist entry by plate, so a second invocation must
neither create duplicate rows nor raise.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# Ensure the repo root (parent of backend/) is importable so that the
# scripts package and its seed_db module resolve.
_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from scripts.seed_db import SAMPLE_PLATE, SEED_USERS, seed_demo_hotlist, seed_users  # noqa: E402

from app.models.complaint import Complaint  # noqa: E402
from app.models.hotlist import Hotlist  # noqa: E402
from app.models.user import User  # noqa: E402


def _seed_all(db: Session) -> None:
    """Run the full seeding sequence.

    Args:
        db: Active database session.
    """
    seed_users(db)
    seed_demo_hotlist(db)


def test_seed_db_is_idempotent(db_session: Session) -> None:
    """Running the seed script twice creates no duplicate rows.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If the second run changes any row count.
    """
    _seed_all(db_session)

    assert db_session.query(User).count() == len(SEED_USERS)
    assert db_session.query(User).filter(User.role.is_not(None)).count() == len(SEED_USERS)
    assert db_session.query(Hotlist).count() == 1
    assert db_session.query(Complaint).count() == 1

    _seed_all(db_session)

    assert db_session.query(User).count() == len(SEED_USERS)
    assert db_session.query(Hotlist).filter(Hotlist.plate == SAMPLE_PLATE).count() == 1
    assert db_session.query(Complaint).filter(Complaint.plate == SAMPLE_PLATE).count() == 1


def test_seed_hotlist_requires_citizen(db_session: Session) -> None:
    """seed_demo_hotlist skips gracefully when the citizen user is absent.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If a hotlist row is created without a citizen user.
    """
    seed_demo_hotlist(db_session)

    assert db_session.query(Hotlist).count() == 0


def test_seed_users_skip_existing_email(db_session: Session) -> None:
    """A user whose email already exists is not duplicated.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If a duplicate email row is created.
    """
    seed_users(db_session)
    password_hash_before = db_session.query(User.password_hash).first()

    seed_users(db_session)

    assert db_session.query(User).count() == len(SEED_USERS)
    assert db_session.query(User.password_hash).first() == password_hash_before