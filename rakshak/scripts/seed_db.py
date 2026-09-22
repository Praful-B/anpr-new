"""Seed script — populates the database with initial RBAC users and demo data.

Creates one user per role: admin, cop, citizen, and volunteer.
Creates a sample complaint and approved hotlist entry for plate MH12AB1234
so the device simulator has something to hit during demo.

Designed to be idempotent: skips creation if the email already exists.

Usage:
    make seed
    # or, directly inside the backend container:
    docker compose exec backend python scripts/seed_db.py
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

# Ensure the backend package is importable from both supported layouts:
# <repo>/backend (running from the host) and the mounted /app (container,
# where the volume places this file at /app/scripts/seed_db.py).
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
for _candidate in (PROJECT_ROOT / "backend", PROJECT_ROOT, SCRIPT_DIR):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine, Base  # noqa: E402
from app.models.complaint import Complaint, ComplaintStatus  # noqa: E402
from app.models.hotlist import Hotlist, HotlistStatus  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger("seed_db")

SEED_USERS = [
    {
        "name": "Admin User",
        "email": "admin@rakshak.local",
        "phone": "9000000001",
        "password": "Admin@123",
        "role": Role.ADMIN,
    },
    {
        "name": "Police Officer",
        "email": "cop@rakshak.local",
        "phone": "9000000002",
        "password": "Cop@12345",
        "role": Role.COP,
    },
    {
        "name": "Citizen User",
        "email": "citizen@rakshak.local",
        "phone": "9000000003",
        "password": "Cit@12345",
        "role": Role.CITIZEN,
    },
    {
        "name": "Volunteer User",
        "email": "volunteer@rakshak.local",
        "phone": "9000000004",
        "password": "Vol@12345",
        "role": Role.VOLUNTEER,
    },
]

SAMPLE_PLATE = "MH12AB1234"


def seed_users(db: Session) -> None:
    """Insert seed users that do not already exist.

    Args:
        db: Active database session.
    """
    for data in SEED_USERS:
        existing = db.query(User).filter(User.email == data["email"]).first()
        if existing is not None:
            logger.info("seed_skip", email=data["email"], reason="already exists")
            continue

        user = User(
            name=data["name"],
            email=data["email"],
            phone=data["phone"],
            password_hash=hash_password(data["password"]),
            role=data["role"],
        )
        db.add(user)
        db.commit()
        logger.info(
            "seed_user_created",
            role=data["role"].value,
            email=data["email"],
        )


def seed_demo_hotlist(db: Session) -> None:
    """Create a sample complaint and approved hotlist entry for MH12AB1234.

    The complaint is filed by the citizen user and immediately approved,
    creating an ACTIVE_UNCONFIRMED hotlist entry with a 48-hour FIR
    deadline. This gives the device simulator a live target.

    Args:
        db: Active database session.
    """
    existing_hotlist = db.query(Hotlist).filter(Hotlist.plate == SAMPLE_PLATE).first()
    if existing_hotlist is not None:
        logger.info("seed_skip", plate=SAMPLE_PLATE, reason="hotlist entry exists")
        return

    citizen = db.query(User).filter(User.email == "citizen@rakshak.local").first()
    if citizen is None:
        logger.warning("seed_warn", reason="citizen user not found, skipping hotlist seed")
        return

    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=citizen.id,
        plate=SAMPLE_PLATE,
        proof_ref="demo-seed-001",
        status=ComplaintStatus.VERIFIED,
    )
    db.add(complaint)
    db.flush()

    fir_deadline = datetime.now(timezone.utc) + timedelta(hours=48)

    hotlist_entry = Hotlist(
        id=uuid.uuid4(),
        plate=SAMPLE_PLATE,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        fir_deadline=fir_deadline,
    )
    db.add(hotlist_entry)
    db.commit()

    logger.info(
        "seed_hotlist_created",
        complaint_id=str(complaint.id),
        hotlist_id=str(hotlist_entry.id),
        plate=SAMPLE_PLATE,
    )


def main() -> None:
    """Entry point: create tables if needed, then seed users and demo data.

    Returns:
        None.
    """
    logger.info("seed_start")
    logger.info("ensuring_tables_exist")
    Base.metadata.create_all(bind=engine)

    logger.info("seeding_users")
    db = SessionLocal()
    try:
        seed_users(db)
        logger.info("seeding_demo_hotlist")
        seed_demo_hotlist(db)
    finally:
        db.close()

    logger.info("seed_complete")
    logger.info("credentials_summary", user_count=len(SEED_USERS), demo_plate=SAMPLE_PLATE)


if __name__ == "__main__":
    main()
