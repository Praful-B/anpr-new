"""Audit logging service — durable record of privileged mutations.

Every COP or ADMIN write operation (complaint verification, hotlist update
and soft-delete, device revocation, role changes) calls
:func:`write_audit_log` so the action is attributable after the fact.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

ACTION_COMPLAINT_VERIFY = "complaint.verify"
ACTION_HOTLIST_UPDATE = "hotlist.update"
ACTION_HOTLIST_DELETE = "hotlist.delete"
ACTION_DEVICE_REVOKE = "device.revoke"
ACTION_USER_ROLE_CHANGE = "user.role_change"

TARGET_COMPLAINT = "complaint"
TARGET_HOTLIST = "hotlist"
TARGET_DEVICE = "device"
TARGET_USER = "user"


def write_audit_log(
    db: Session,
    actor_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist an audit-log row for a privileged mutation.

    The row is committed immediately so the trail survives even when the
    caller's later work fails.

    Args:
        db: Database session.
        actor_id: UUID of the user who performed the action.
        action: Machine-readable action label.
        target_type: Type of the affected entity.
        target_id: UUID of the affected entity.
        metadata: Optional structured context for the action.

    Returns:
        AuditLog: The persisted audit entry.
    """
    entry = AuditLog(
        id=uuid.uuid4(),
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=metadata,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    logger.info(
        "audit_log_written",
        action=action,
        actor_id=str(actor_id),
        target_type=target_type,
        target_id=str(target_id),
    )
    return entry
