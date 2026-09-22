"""§10 data retention purge tests.

Proves the nightly purge job enforces the PROJECT_INFO §10 policy:
sightings > 90 days (with their photos), rejected complaints > 30 days,
expired/closed hotlist entries > 180 days past cooldown, and audit logs
older than 1 year.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.complaint import Complaint, ComplaintStatus
from app.models.device import Device, DeviceType
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.sighting import Sighting
from app.services.scheduler import purge_old_data


class FakeStorage:
    """In-memory storage that records every deleted photo url."""

    def __init__(self) -> None:
        """Initialise an empty deletion list."""
        self.deleted: list[str] = []

    def put(self, data: bytes, content_type: str = "image/jpeg") -> str:
        """Return a synthetic URL and ignore the data."""
        return "/sightings/fake.jpg"

    def get(self, url: str) -> bytes:
        """Return empty bytes."""
        return b""

    def delete(self, url: str) -> None:
        """Record the deleted url."""
        self.deleted.append(url)


def _days_ago(now: datetime, days: int) -> datetime:
    """Subtract a day count from a timestamp.

    Args:
        now: Base timestamp.
        days: Number of days to subtract.

    Returns:
        datetime: The offset timestamp.
    """
    return now - timedelta(days=days)


def _create_verified_hotlist(
    db_session: Session,
    plate: str,
    status: HotlistStatus,
    cooldown_until: datetime | None = None,
) -> Hotlist:
    """Create a verified complaint and a hotlist entry with the given state.

    Args:
        db_session: Test database session.
        plate: Normalised licence plate string.
        status: Hotlist status for the entry.
        cooldown_until: Optional cooldown expiry timestamp.

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
        status=status,
        cooldown_until=cooldown_until,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _create_device(db_session: Session) -> Device:
    """Create and return a minimal device row.

    Args:
        db_session: Test database session.

    Returns:
        Device: The created device.
    """
    device = Device(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=DeviceType.VOLUNTEER,
        token_hash="hash",
        encryption_key_wrapped="{}",
        revoked=False,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


def _create_sighting(
    db_session: Session,
    hotlist: Hotlist,
    device: Device,
    captured_at: datetime,
    photo_url: str,
) -> Sighting:
    """Create and return a sighting row at the given capture time.

    Args:
        db_session: Test database session.
        hotlist: The matched hotlist entry.
        device: The reporting device.
        captured_at: UTC detection timestamp.
        photo_url: Photo url to record for later deletion.

    Returns:
        Sighting: The created sighting.
    """
    sighting = Sighting(
        id=uuid.uuid4(),
        hotlist_id=hotlist.id,
        device_id=device.id,
        lat=19.076,
        lng=72.877,
        captured_at=captured_at,
        photo_url=photo_url,
        confidence=82,
    )
    db_session.add(sighting)
    db_session.commit()
    db_session.refresh(sighting)
    return sighting


def _create_audit_log(
    db_session: Session,
    created_at: datetime,
) -> AuditLog:
    """Create and return an audit log row with the given creation time.

    Args:
        db_session: Test database session.
        created_at: UTC timestamp to stamp on the row.

    Returns:
        AuditLog: The created audit log entry.
    """
    log = AuditLog(
        id=uuid.uuid4(),
        action="hotlist.update",
        target_type="hotlist",
        target_id=uuid.uuid4(),
        created_at=created_at,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


def test_purge_removes_old_sightings_and_their_photos(
    db_session: Session,
) -> None:
    """Sightings older than 90 days are removed together with their photos.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If the purge leaves stale rows or photo blobs.
    """
    now = datetime.now(timezone.utc)
    hotlist = _create_verified_hotlist(
        db_session, "MH12AB1234", HotlistStatus.ACTIVE_CONFIRMED
    )
    device = _create_device(db_session)
    old = _create_sighting(
        db_session, hotlist, device, _days_ago(now, 100), "/sightings/old.jpg"
    )
    recent = _create_sighting(
        db_session, hotlist, device, _days_ago(now, 10), "/sightings/recent.jpg"
    )
    storage = FakeStorage()
    old_id = old.id
    recent_id = recent.id

    purge_old_data(db=db_session, storage=storage)

    remaining_ids = {sighting.id for sighting in db_session.query(Sighting).all()}
    assert old_id not in remaining_ids
    assert recent_id in remaining_ids
    assert "/sightings/old.jpg" in storage.deleted
    assert "/sightings/recent.jpg" not in storage.deleted


def test_purge_removes_audit_logs_older_than_one_year(db_session: Session) -> None:
    """Audit logs older than 365 days are removed; newer logs are kept.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If the retention boundary is not respected.
    """
    now = datetime.now(timezone.utc)
    old = _create_audit_log(db_session, _days_ago(now, 400))
    recent = _create_audit_log(db_session, _days_ago(now, 30))
    old_id = old.id
    recent_id = recent.id

    purge_old_data(db=db_session, storage=FakeStorage())

    remaining_ids = {log.id for log in db_session.query(AuditLog).all()}
    assert old_id not in remaining_ids
    assert recent_id in remaining_ids


def test_purge_removes_rejected_complaints_older_than_30_days(
    db_session: Session,
) -> None:
    """Rejected complaints older than 30 days are removed; others are kept.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If the complaint retention boundary is violated.
    """
    now = datetime.now(timezone.utc)
    old = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate="DL01CD5678",
        status=ComplaintStatus.REJECTED,
        created_at=_days_ago(now, 40),
    )
    recent = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate="KA01EF9012",
        status=ComplaintStatus.REJECTED,
        created_at=_days_ago(now, 10),
    )
    verified = Complaint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plate="GJ01XX0001",
        status=ComplaintStatus.VERIFIED,
        created_at=_days_ago(now, 40),
    )
    db_session.add_all([old, recent, verified])
    db_session.commit()
    old_id = old.id
    recent_id = recent.id
    verified_id = verified.id

    purge_old_data(db=db_session, storage=FakeStorage())

    remaining = {complaint.id for complaint in db_session.query(Complaint).all()}
    assert old_id not in remaining
    assert recent_id in remaining
    assert verified_id in remaining


def test_purge_removes_expired_hotlist_past_cooldown(db_session: Session) -> None:
    """Expired entries past cooldown + 180 days are removed; recent are kept.

    Args:
        db_session: Test database session.

    Raises:
        AssertionError: If the hotlist retention boundary is violated.
    """
    now = datetime.now(timezone.utc)
    expired_old = _create_verified_hotlist(
        db_session,
        "MH12AB1234",
        HotlistStatus.EXPIRED,
        cooldown_until=_days_ago(now, 200),
    )
    expired_recent = _create_verified_hotlist(
        db_session,
        "DL01CD5678",
        HotlistStatus.EXPIRED,
        cooldown_until=_days_ago(now, 10),
    )
    active = _create_verified_hotlist(
        db_session, "KA01EF9012", HotlistStatus.ACTIVE_CONFIRMED
    )
    expired_old_id = expired_old.id
    expired_recent_id = expired_recent.id
    active_id = active.id

    purge_old_data(db=db_session, storage=FakeStorage())

    remaining = {entry.id for entry in db_session.query(Hotlist).all()}
    assert expired_old_id not in remaining
    assert expired_recent_id in remaining
    assert active_id in remaining