"""Admin endpoints — user management and audit-log access.

Routes under ``/api/v1/admin`` are ADMIN-only:

- ``GET  /admin/users``               paginated user listing with role filter
- ``PATCH /admin/users/{id}/role``    change a user's role
- ``GET  /admin/audit``               paginated audit-log query
"""

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.audit_log import AuditLog
from app.models.user import Role, User
from app.schemas.audit import AuditLogPageResponse, AuditLogResponse
from app.schemas.auth import UserResponse
from app.schemas.user import RoleUpdateRequest, UserListResponse
from app.services.audit import (
    ACTION_USER_ROLE_CHANGE,
    TARGET_USER,
    write_audit_log,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/admin", tags=["admin"])

logger = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

_ADMIN_ONLY = require_role(Role.ADMIN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_to_response(user: User) -> UserResponse:
    """Convert a User ORM instance to the public response schema.

    Args:
        user: The user ORM instance.

    Returns:
        UserResponse: Pydantic model safe for external responses.
    """
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
    )


def _audit_to_response(entry: AuditLog) -> AuditLogResponse:
    """Convert an AuditLog ORM instance to the response schema.

    Args:
        entry: The audit-log ORM instance.

    Returns:
        AuditLogResponse: Pydantic model safe for external responses.
    """
    return AuditLogResponse(
        id=entry.id,
        actor_id=entry.actor_id,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        metadata=entry.metadata_json,
        created_at=entry.created_at,
    )


def _parse_role_filter(raw_role: str | None) -> Role | None:
    """Parse an optional role query parameter.

    Args:
        raw_role: Raw role string from the query string, or None.

    Returns:
        Role | None: The parsed role, or None when no filter was supplied.

    Raises:
        HTTPException: 400 when the value is not a known role.
    """
    if raw_role is None:
        return None
    try:
        return Role(raw_role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {raw_role}. "
            f"Valid values: {[role.value for role in Role]}",
        )


def _load_user(db: Session, user_id: uuid.UUID) -> User:
    """Load a user by id or fail with 404.

    Args:
        db: Database session.
        user_id: UUID of the user.

    Returns:
        User: The matching ORM user.

    Raises:
        HTTPException: 404 when no such user exists.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=UserListResponse,
)
def list_users(
    current_user: Annotated[User, Depends(_ADMIN_ONLY)],
    db: Annotated[Session, Depends(get_db)],
    role: str | None = Query(None, description="Filter by role"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"
    ),
) -> UserListResponse:
    """List user accounts with optional role filtering. ADMIN only.

    Args:
        current_user: Authenticated ADMIN user.
        db: Database session.
        role: Optional role filter.
        page: Page number (1-indexed).
        per_page: Items per page (max 100).

    Returns:
        UserListResponse: The matching users and the total count.
    """
    query = db.query(User)

    role_filter = _parse_role_filter(role)
    if role_filter is not None:
        query = query.filter(User.role == role_filter)

    total = query.count()
    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return UserListResponse(
        items=[_user_to_response(user) for user in users],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse,
)
def update_user_role(
    user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: Annotated[User, Depends(_ADMIN_ONLY)],
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    """Change a user's role. ADMIN only.

    Args:
        user_id: UUID of the user whose role changes.
        payload: The new role.
        current_user: Authenticated ADMIN user.
        db: Database session.

    Returns:
        UserResponse: The updated user.

    Raises:
        HTTPException: 404 when the user does not exist.
    """
    user = _load_user(db, user_id)
    previous_role = user.role.value

    user.role = payload.role
    db.commit()
    db.refresh(user)

    write_audit_log(
        db=db,
        actor_id=current_user.id,
        action=ACTION_USER_ROLE_CHANGE,
        target_type=TARGET_USER,
        target_id=user.id,
        metadata={"from": previous_role, "to": payload.role.value},
    )

    logger.info(
        "user_role_changed",
        user_id=str(user.id),
        actor_id=str(current_user.id),
        new_role=payload.role.value,
    )

    return _user_to_response(user)


@router.get(
    "/audit",
    response_model=AuditLogPageResponse,
)
def list_audit_entries(
    current_user: Annotated[User, Depends(_ADMIN_ONLY)],
    db: Annotated[Session, Depends(get_db)],
    actor_id: uuid.UUID | None = Query(None, description="Filter by actor UUID"),
    action: str | None = Query(None, description="Filter by action label"),
    from_date: datetime | None = Query(None, description="Filter entries after"),
    to_date: datetime | None = Query(None, description="Filter entries before"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"
    ),
) -> AuditLogPageResponse:
    """List audit-log entries with filtering. ADMIN only.

    Args:
        current_user: Authenticated ADMIN user.
        db: Database session.
        actor_id: Optional actor UUID filter.
        action: Optional action-label filter.
        from_date: Optional inclusive lower bound on ``created_at``.
        to_date: Optional inclusive upper bound on ``created_at``.
        page: Page number (1-indexed).
        per_page: Items per page (max 100).

    Returns:
        AuditLogPageResponse: The matching entries and the total count.
    """
    query = db.query(AuditLog)

    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if action is not None:
        query = query.filter(AuditLog.action == action)
    if from_date is not None:
        query = query.filter(AuditLog.created_at >= from_date)
    if to_date is not None:
        query = query.filter(AuditLog.created_at <= to_date)

    total = query.count()
    entries = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return AuditLogPageResponse(
        items=[_audit_to_response(entry) for entry in entries],
        total=total,
        page=page,
        per_page=per_page,
    )
