"""Complaint verification service — approve/reject complaints and manage hotlist entries.

Provides ``verify_complaint`` which handles the COP/ADMIN verification
workflow: approving creates a hotlist entry with ACTIVE_UNCONFIRMED status
and a 48-hour FIR deadline; rejecting marks the complaint as REJECTED with
an optional reason.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIR_DEADLINE_HOURS = 48
APPROVE_DECISION = "approve"
REJECT_DECISION = "reject"

logger = structlog.get_logger(__name__)


def _ensure_pending_verification(complaint: Complaint) -> None:
    """Assert that a complaint is still awaiting verification.

    Args:
        complaint: The complaint about to be verified.

    Raises:
        ValueError: If the complaint is not PENDING_VERIFICATION.
    """
    if complaint.status == ComplaintStatus.PENDING_VERIFICATION:
        return
    logger.info(
        "verify_complaint_invalid_state",
        complaint_id=str(complaint.id),
        current_status=complaint.status.value,
    )
    raise ValueError(
        f"Complaint {complaint.id} is not pending verification "
        f"(current status: {complaint.status.value})"
    )

def verify_complaint(
    db: Session,
    complaint: Complaint,
    decision: str,
    reason: str | None = None,
) -> Complaint:
    """Verify a complaint by approving or rejecting it.

    On approve: sets complaint status to VERIFIED and creates a hotlist
    entry with status ACTIVE_UNCONFIRMED and ``fir_deadline`` set to
    now + 48 hours.

    On reject: sets complaint status to REJECTED and stores the
    rejection reason.

    Args:
        db: Database session for persistence.
        complaint: The complaint ORM instance to verify.
        decision: Either ``"approve"`` or ``"reject"``.
        reason: Optional rejection reason (required when rejecting).

    Returns:
        Complaint: The updated complaint instance.

    Raises:
        ValueError: If the complaint is not in PENDING_VERIFICATION state,
            or if rejecting without a reason.
    """
    _ensure_pending_verification(complaint)

    if decision == APPROVE_DECISION:
        return _approve_complaint(db, complaint)
    if decision == REJECT_DECISION:
        return _reject_complaint(db, complaint, reason)
    raise ValueError(
        f"Invalid decision: {decision}. Must be '{APPROVE_DECISION}' or '{REJECT_DECISION}'."
    )


def _approve_complaint(db: Session, complaint: Complaint) -> Complaint:
    """Approve a complaint and create the corresponding hotlist entry.

    Sets the complaint status to VERIFIED and creates a hotlist entry
    with ACTIVE_UNCONFIRMED status and a 48-hour FIR deadline.

    Args:
        db: Database session for persistence.
        complaint: The complaint to approve.

    Returns:
        Complaint: The updated complaint instance.
    """
    complaint.status = ComplaintStatus.VERIFIED
    complaint.updated_at = datetime.now(timezone.utc)

    fir_deadline = datetime.now(timezone.utc) + timedelta(hours=FIR_DEADLINE_HOURS)

    hotlist_entry = Hotlist(
        plate=complaint.plate,
        complaint_id=complaint.id,
        status=HotlistStatus.ACTIVE_UNCONFIRMED,
        fir_deadline=fir_deadline,
    )
    db.add(hotlist_entry)
    db.commit()
    db.refresh(complaint)

    logger.info(
        "complaint_approved",
        complaint_id=str(complaint.id),
        hotlist_entry_id=str(hotlist_entry.id),
        fir_deadline=fir_deadline.isoformat(),
    )

    return complaint


def _reject_complaint(
    db: Session,
    complaint: Complaint,
    reason: str | None,
) -> Complaint:
    """Reject a complaint with an optional reason.

    Sets the complaint status to REJECTED and stores the rejection
    reason if provided.

    Args:
        db: Database session for persistence.
        complaint: The complaint to reject.
        reason: Optional rejection reason.

    Returns:
        Complaint: The updated complaint instance.

    Raises:
        ValueError: If no rejection reason is provided.
    """
    if not reason or not reason.strip():
        raise ValueError("A rejection reason is required when rejecting a complaint")

    complaint.status = ComplaintStatus.REJECTED
    complaint.rejection_reason = reason.strip()
    complaint.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(complaint)

    logger.info(
        "complaint_rejected",
        complaint_id=str(complaint.id),
        reason=complaint.rejection_reason,
    )

    return complaint
