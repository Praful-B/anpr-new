"""Pydantic schemas for audit-log responses.

Defines the representation of a single audit entry and the paginated
listing returned by ``GET /api/v1/admin/audit``.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    """A single audit-log entry.

    Attributes:
        id: UUID of the audit entry.
        actor_id: UUID of the user who performed the action (None for system).
        action: Machine-readable action label (e.g. ``hotlist.update``).
        target_type: Type of the affected entity.
        target_id: UUID of the affected entity.
        metadata: Arbitrary structured context for the action.
        created_at: UTC timestamp when the action was recorded.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Audit entry UUID")
    actor_id: UUID | None = Field(None, description="Acting user UUID (None for system)")
    action: str = Field(..., description="Action label")
    target_type: str = Field(..., description="Affected entity type")
    target_id: UUID = Field(..., description="Affected entity UUID")
    metadata: dict[str, Any] | None = Field(
        None, description="Structured context for the action"
    )
    created_at: datetime = Field(..., description="Recorded timestamp")


class AuditLogPageResponse(BaseModel):
    """Paginated list of audit-log entries.

    Attributes:
        items: The entries on the requested page.
        total: Total number of entries matching the filter.
        page: The 1-indexed page number returned.
        per_page: Maximum number of entries per page.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[AuditLogResponse] = Field(..., description="Entries on this page")
    total: int = Field(..., gt=0, description="Total matching entries")
    page: int = Field(..., gt=0, description="Current page number")
    per_page: int = Field(..., gt=0, description="Page size")
