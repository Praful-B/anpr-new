"""Custom exception classes and standard error response formatting.

Provides typed exceptions for domain-specific error handling and a
helper to build the standard RAKSHAK error response shape:
``{"error": {"code": "...", "message": "...", "field": null}}``.
"""

from typing import Any


class InvalidStateTransition(Exception):
    """Raised when a hotlist entry state transition is not permitted.

    Attributes:
        from_state: The current state of the entry.
        to_state: The requested target state.
    """

    def __init__(self, from_state: str, to_state: str) -> None:
        """Record the rejected transition and build its message.

        Args:
            from_state: The current state of the entry.
            to_state: The requested target state.

        Returns:
            None.
        """
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition from {from_state} to {to_state}"
        )


class AppError(Exception):
    """Standard application error with machine code and optional field.

    Attributes:
        code: Machine-readable error code (e.g. ``EMAIL_TAKEN``).
        message: Human-readable error description.
        field: Name of the offending field for validation errors, else None.
        status_code: HTTP status code (default 400).
    """

    def __init__(
        self,
        code: str,
        message: str,
        field: str | None = None,
        status_code: int = 400,
    ) -> None:
        """Store the machine code, message, field, and status code.

        Args:
            code: Machine-readable error code (e.g. ``EMAIL_TAKEN``).
            message: Human-readable error description.
            field: Name of the offending field for validation errors.
            status_code: HTTP status code to return (default 400).

        Returns:
            None.
        """
        self.code = code
        self.message = message
        self.field = field
        self.status_code = status_code
        super().__init__(message)


def error_response(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    """Build the standard RAKSHAK error response body.

    Args:
        code: Machine-readable error code.
        message: Human-readable description.
        field: Offending field name for validation errors, else None.

    Returns:
        dict: ``{"error": {"code": ..., "message": ..., "field": ...}}``.
    """
    return {"error": {"code": code, "message": message, "field": field}}
