"""FIR expiry scheduler tests.

Covers the expire_unconfirmed_entries job: creating entries with past
FIR deadlines, running the scheduler job manually, and asserting that
status transitions to EXPIRED with cooldown set.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus
from app.services.scheduler import expire_unconfirmed_entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_hotlist_entry_with_past_deadline(
    db_session: Session,
    user_id: uuid.UUID,
    plate: str = "MH12AB1234",
) -> Hotlist:
    """Create a complaint and hotlist entry with a FIR deadline in the past.

    Args:
        db_session: Test database session.
        user_id: UUID of the owning user.
        plate: Licence plate string.

    Returns:
        Hotlist: The created hotlist entry.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=user_id,
        plate=plate,
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    past_deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    hotlist_entry = Hotlist(
        id=uuid.uuid4(),
        plate=plate,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        fir_deadline=past_deadline,
    )
    db_session.add(hotlist_entry)
    db_session.commit()
    db_session.refresh(hotlist_entry)

    return hotlist_entry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_expire_unconfirmed_sets_expired_status(
    db_session: Session,
    citizen_user,
) -> None:
    """Entries with past fir_deadline are set to EXPIRED by the scheduler job.

    Args:
        db_session: Test database session.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If status is not EXPIRED after job execution.
    """
    entry = _create_hotlist_entry_with_past_deadline(
        db_session, citizen_user.id, "MH12AB1234"
    )
    assert entry.status == HotlistStatus.ACTIVE_UNCONFIRMED

    expire_unconfirmed_entries(db=db_session)

    db_session.refresh(entry)
    assert entry.status == HotlistStatus.EXPIRED
    assert entry.cooldown_until is not None

    now = datetime.now(timezone.utc)
    cooldown = entry.cooldown_until
    if cooldown.tzinfo is None:
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    expected_cooldown = now + timedelta(days=7)
    diff = abs((cooldown - expected_cooldown).total_seconds())
    assert diff < 5, f"Cooldown should be ~7d from now, diff was {diff}s"


def test_expire_unconfirmed_does_not_touch_active_deadline(
    db_session: Session,
    citizen_user,
) -> None:
    """Entries with future fir_deadline are not expired by the scheduler job.

    Args:
        db_session: Test database session.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If entry status changes when it should not.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=citizen_user.id,
        plate="MH12AB5678",
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    future_deadline = datetime.now(timezone.utc) + timedelta(hours=24)
    entry = Hotlist(
        id=uuid.uuid4(),
        plate="MH12AB5678",
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        fir_deadline=future_deadline,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    expire_unconfirmed_entries(db=db_session)

    db_session.refresh(entry)
    assert entry.status == HotlistStatus.ACTIVE_UNCONFIRMED
    assert entry.cooldown_until is None


def test_expire_unconfirmed_skips_confirmed_entries(
    db_session: Session,
    citizen_user,
) -> None:
    """ACTIVE_CONFIRMED entries are not expired even if past deadline.

    Args:
        db_session: Test database session.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If a confirmed entry is accidentally expired.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=citizen_user.id,
        plate="MH12AB9999",
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    past_deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    entry = Hotlist(
        id=uuid.uuid4(),
        plate="MH12AB9999",
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_CONFIRMED,
        fir_deadline=past_deadline,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    expire_unconfirmed_entries(db=db_session)

    db_session.refresh(entry)
    assert entry.status == HotlistStatus.ACTIVE_CONFIRMED
    assert entry.cooldown_until is None


def test_expire_unconfirmed_handles_no_deadline(
    db_session: Session,
    citizen_user,
) -> None:
    """Entries with no fir_deadline are not expired.

    Args:
        db_session: Test database session.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If entry without deadline is expired.
    """
    complaint = Complaint(
        id=uuid.uuid4(),
        user_id=citizen_user.id,
        plate="MH12AB0000",
        status=ComplaintStatus.VERIFIED,
    )
    db_session.add(complaint)
    db_session.flush()

    entry = Hotlist(
        id=uuid.uuid4(),
        plate="MH12AB0000",
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        fir_deadline=None,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    expire_unconfirmed_entries(db=db_session)

    db_session.refresh(entry)
    assert entry.status == HotlistStatus.ACTIVE_UNCONFIRMED


def test_expire_unconfirmed_handles_multiple_entries(
    db_session: Session,
    citizen_user,
) -> None:
    """Multiple entries past deadline are all expired in one batch.

    Args:
        db_session: Test database session.
        citizen_user: The CITIZEN user fixture.

    Returns:
        None.

    Raises:
        AssertionError: If not all entries are expired.
    """
    entries = []
    for i in range(3):
        entry = _create_hotlist_entry_with_past_deadline(
            db_session, citizen_user.id, f"MH12AB100{i}"
        )
        entries.append(entry)

    expire_unconfirmed_entries(db=db_session)

    for entry in entries:
        db_session.refresh(entry)
        assert entry.status == HotlistStatus.EXPIRED
        assert entry.cooldown_until is not None
