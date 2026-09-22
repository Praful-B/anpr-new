"""Shared SQLAlchemy mixin for timestamp columns.

Provides ``created_at`` and ``updated_at`` columns that every model
inherits from a single source of truth, avoiding duplication.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Mixin that adds ``created_at`` and ``updated_at`` UTC timestamp columns.

    ``created_at`` is set on row creation; ``updated_at`` is set on
    creation and on every subsequent update.
    """

    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
