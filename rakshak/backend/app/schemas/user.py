"""Pydantic schemas for admin user-management payloads.

Defines the paginated user listing and the role-change request used by the
``/api/v1/admin`` endpoints. The single-user representation is
``app.schemas.auth.UserResponse``.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import Role
from app.schemas.auth import UserResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PAGE_SIZE = 100


class UserListResponse(BaseModel):
    """Paginated list of user accounts.

    Attributes:
        items: The users on the requested page.
        total: Total number of users matching the filter.
        page: The 1-indexed page number returned.
        per_page: Maximum number of users per page.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[UserResponse] = Field(..., description="Users on this page")
    total: int = Field(..., gt=0, description="Total matching users")
    page: int = Field(..., gt=0, description="Current page number")
    per_page: int = Field(..., gt=0, description="Page size")


class RoleUpdateRequest(BaseModel):
    """Request body for changing a user's role.

    Attributes:
        role: The new role to assign.
    """

    model_config = ConfigDict(extra="forbid")

    role: Role = Field(..., description="New role for the user")
