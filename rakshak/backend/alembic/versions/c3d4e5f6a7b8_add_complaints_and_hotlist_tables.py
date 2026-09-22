"""add_complaints_and_hotlist_tables

Creates the complaints and hotlist tables with their ENUM types,
indexes, and foreign key constraints.

Revision ID: c3d4e5f6a7b8
Revises: b2c51247221b
Create Date: 2026-09-21 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c51247221b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_if_not_exists(bind, type_name: str, values: list[str]) -> None:
    """Create a PostgreSQL ENUM type if it does not already exist.

    Args:
        bind: SQLAlchemy connection or engine.
        type_name: Name of the ENUM type to create.
        values: List of allowed ENUM values.
    """
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": type_name},
    ).first()
    if row is None:
        placeholders = ", ".join(f":v{i}" for i in range(len(values)))
        params = {f"v{i}": v for i, v in enumerate(values)}
        bind.execute(
            sa.text(f"CREATE TYPE {type_name} AS ENUM ({placeholders})"),
            params,
        )


COMPLAINT_STATUS_VALUES = ["PENDING_VERIFICATION", "VERIFIED", "REJECTED"]
HOTLIST_STATUS_VALUES = [
    "PENDING_VERIFICATION",
    "ACTIVE_UNCONFIRMED",
    "ACTIVE_CONFIRMED",
    "EXPIRED",
    "CLOSED",
    "REJECTED",
]


def _create_status_enums(conn) -> None:
    """Create the complaint and hotlist ENUM types when missing.

    Args:
        conn: SQLAlchemy connection bound to the migration.
    """
    _create_enum_if_not_exists(conn, "complaint_status", COMPLAINT_STATUS_VALUES)
    _create_enum_if_not_exists(conn, "hotlist_status", HOTLIST_STATUS_VALUES)


def _create_complaints_table() -> None:
    """Create the complaints table with its lookup indexes."""
    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS complaints (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id),
                plate VARCHAR(20) NOT NULL,
                proof_ref VARCHAR(500),
                status complaint_status NOT NULL DEFAULT 'PENDING_VERIFICATION',
                rejection_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_user_id_created_at "
            "ON complaints (user_id, created_at DESC)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_plate "
            "ON complaints (plate)"
        )
    )


def _create_hotlist_table() -> None:
    """Create the hotlist table with its lookup indexes."""
    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS hotlist (
                id UUID PRIMARY KEY,
                plate VARCHAR(20) NOT NULL,
                complaint_id UUID NOT NULL REFERENCES complaints(id),
                status hotlist_status NOT NULL DEFAULT 'PENDING_VERIFICATION',
                added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                fir_deadline TIMESTAMPTZ,
                fir_ref VARCHAR(100),
                fir_verified_at TIMESTAMPTZ,
                cooldown_until TIMESTAMPTZ,
                recovered_at TIMESTAMPTZ,
                last_seen_at TIMESTAMPTZ,
                last_seen_lat DOUBLE PRECISION,
                last_seen_lng DOUBLE PRECISION,
                dismissed BOOLEAN NOT NULL DEFAULT FALSE,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_hotlist_plate "
            "ON hotlist (plate)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_hotlist_status "
            "ON hotlist (status)"
        )
    )


def upgrade() -> None:
    """Create complaints and hotlist tables with ENUM types and indexes."""
    _create_status_enums(op.get_bind())
    _create_complaints_table()
    _create_hotlist_table()


def downgrade() -> None:
    """Drop hotlist and complaints tables and their ENUM types."""
    op.execute(sa.text("DROP TABLE IF EXISTS hotlist"))
    op.execute(sa.text("DROP TABLE IF EXISTS complaints"))
    op.execute(sa.text("DROP TYPE IF EXISTS hotlist_status"))
    op.execute(sa.text("DROP TYPE IF EXISTS complaint_status"))
