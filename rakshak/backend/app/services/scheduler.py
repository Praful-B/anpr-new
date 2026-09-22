"""Scheduled jobs for FIR expiry and nightly data purge.

Uses APScheduler (in-process) to run:
1. Every 5 minutes: expire ACTIVE_UNCONFIRMED entries past their fir_deadline.
2. Nightly at 02:00 UTC: purge old sightings, rejected complaints, and
   expired hotlist entries per the data retention policy (§10).
"""

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIR_EXPIRY_INTERVAL_MINUTES = 5
COOLDOWN_HOURS = 7 * 24
REJECTED_COMPLAINT_RETENTION_DAYS = 30
EXPIRED_HOTLIST_RETENTION_DAYS = 180
NIGHTLY_PURGE_HOUR = 2
NIGHTLY_PURGE_MINUTE = 0

logger = structlog.get_logger(__name__)


def _find_expired_entries(db: Session, now: datetime) -> list[Hotlist]:
    """Fetch ACTIVE_UNCONFIRMED entries whose FIR deadline has passed.

    Args:
        db: Database session.
        now: Current UTC timestamp.

    Returns:
        list[Hotlist]: Entries that must transition to EXPIRED.
    """
    return (
        db.query(Hotlist)
        .filter(
            Hotlist.status == HotlistStatus.ACTIVE_UNCONFIRMED,
            Hotlist.fir_deadline.isnot(None),
            Hotlist.fir_deadline < now,
        )
        .all()
    )


def _mark_expired(entry: Hotlist, now: datetime) -> None:
    """Flip one hotlist entry to EXPIRED and start its cooldown.

    Args:
        entry: The hotlist entry to expire.
        now: Current UTC timestamp used for cooldown and audit fields.
    """
    entry.status = HotlistStatus.EXPIRED
    entry.cooldown_until = now + timedelta(hours=COOLDOWN_HOURS)
    entry.updated_at = now
    logger.info(
        "hotlist_entry_expired",
        hotlist_entry_id=str(entry.id),
        plate=entry.plate,
        fir_deadline=entry.fir_deadline.isoformat(),
        cooldown_until=entry.cooldown_until.isoformat(),
    )


def expire_unconfirmed_entries(db: Session | None = None) -> None:
    """Expire ACTIVE_UNCONFIRMED hotlist entries past their FIR deadline.

    Sets status to EXPIRED and ``cooldown_until`` to now + 7 days.
    Runs every 5 minutes via APScheduler.

    Args:
        db: Optional database session. When ``None``, a new session is
            created from ``SessionLocal``. Pass a session explicitly for
            unit testing against an in-memory database.
    """
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired_entries = _find_expired_entries(db, now)
        if not expired_entries:
            return
        for entry in expired_entries:
            _mark_expired(entry, now)
        db.commit()
        logger.info("fir_expiry_batch_complete", count=len(expired_entries))
    except Exception:
        logger.exception("fir_expiry_job_failed")
        db.rollback()
    finally:
        if owns_session:
            db.close()


def purge_old_data() -> None:
    """Nightly purge of old data per the retention policy (§10).

    - Rejected complaints older than 30 days: delete.
    - Expired/CLOSED hotlist entries past cooldown + 180 days: delete.
    Runs nightly at 02:00 UTC via APScheduler.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        _purge_rejected_complaints(db, now)
        _purge_expired_hotlist_entries(db, now)

        db.commit()
        logger.info("nightly_purge_complete")
    except Exception:
        logger.exception("nightly_purge_job_failed")
        db.rollback()
    finally:
        db.close()


def _purge_rejected_complaints(db: Session, now: datetime) -> None:
    """Delete rejected complaints older than the retention period.

    Args:
        db: Database session.
        now: Current UTC timestamp.
    """
    cutoff = now - timedelta(days=REJECTED_COMPLAINT_RETENTION_DAYS)
    deleted = (
        db.query(Complaint)
        .filter(
            Complaint.status == ComplaintStatus.REJECTED,
            Complaint.created_at < cutoff,
        )
        .delete(synchronize_session="fetch")
    )
    if deleted:
        logger.info("purged_rejected_complaints", count=deleted)


def _purge_expired_hotlist_entries(db: Session, now: datetime) -> None:
    """Delete expired/closed hotlist entries past cooldown + retention period.

    Args:
        db: Database session.
        now: Current UTC timestamp.
    """
    cutoff = now - timedelta(days=EXPIRED_HOTLIST_RETENTION_DAYS)
    deleted = (
        db.query(Hotlist)
        .filter(
            Hotlist.status.in_([HotlistStatus.EXPIRED, HotlistStatus.CLOSED]),
            Hotlist.cooldown_until.isnot(None),
            Hotlist.cooldown_until < cutoff,
        )
        .delete(synchronize_session="fetch")
    )
    if deleted:
        logger.info("purged_expired_hotlist_entries", count=deleted)


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the APScheduler instance.

    Registers the FIR expiry job (every 5 minutes) and the nightly
    purge job (02:00 UTC daily).

    Returns:
        BackgroundScheduler: Configured but not yet started scheduler.
    """
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        expire_unconfirmed_entries,
        "interval",
        minutes=FIR_EXPIRY_INTERVAL_MINUTES,
        id="fir_expiry",
        replace_existing=True,
    )

    scheduler.add_job(
        purge_old_data,
        "cron",
        hour=NIGHTLY_PURGE_HOUR,
        minute=NIGHTLY_PURGE_MINUTE,
        id="nightly_purge",
        replace_existing=True,
    )

    logger.info(
        "scheduler_configured",
        fir_expiry_interval=FIR_EXPIRY_INTERVAL_MINUTES,
        nightly_purge_hour=NIGHTLY_PURGE_HOUR,
    )

    return scheduler
