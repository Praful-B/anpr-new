"""add_devices_table

Creates the devices table with device_type ENUM, indexes, and
foreign key constraint to the users table.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
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


def upgrade() -> None:
    """Create the devices table with device_type ENUM and indexes."""
    conn = op.get_bind()

    _create_enum_if_not_exists(
        conn, "device_type",
        ["FLEET", "VOLUNTEER"],
    )

    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS devices (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id),
                type device_type NOT NULL DEFAULT 'VOLUNTEER',
                token_hash VARCHAR(255) NOT NULL UNIQUE,
                encryption_key_wrapped VARCHAR(512) NOT NULL,
                key_version INTEGER NOT NULL DEFAULT 0,
                revoked BOOLEAN NOT NULL DEFAULT FALSE,
                last_sync_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_devices_user_id "
            "ON devices (user_id)"
        )
    )


def downgrade() -> None:
    """Drop the devices table and the device_type ENUM type."""
    op.execute(sa.text("DROP TABLE IF EXISTS devices"))
    op.execute(sa.text("DROP TYPE IF EXISTS device_type"))
